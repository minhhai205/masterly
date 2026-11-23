"""Models & services: the shared model catalog behind the settings pages.

One catalog serves every account. Only the administrator reads or changes it;
a learner calling these endpoints gets 403, except ``GET /api/settings`` which
answers them with their interface preferences only.

Edits are staged in a draft first and reach the runtime when applied. Secrets
leave the server masked and are restored from the stored copy by ID when a
masked value comes back.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
import contextlib
from copy import deepcopy
import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from masterly.multi_user.context import get_current_user
from masterly.services.codex_auth import (
    CodexAuthError,
    get_codex_oauth_service,
    reconcile_codex_catalog_update,
)
from masterly.services.config import (
    CATALOG_SECRET_MASK,
    get_config_test_runner,
    get_model_catalog_service,
    redact_catalog_secrets,
    restore_catalog_secrets,
)
from masterly.services.config.settings_draft import (
    get_settings_draft_service,
    is_empty_draft,
    merge_draft_secrets,
    redact_draft,
)
from masterly.services.llm.config import clear_llm_config_cache
from masterly.services.settings.interface_settings import get_ui_settings

logger = logging.getLogger(__name__)

router = APIRouter()

ServiceName = Literal["llm", "task", "embedding", "search"]


class CatalogPayload(BaseModel):
    catalog: dict[str, Any]


class ProviderEditPayload(BaseModel):
    service: ServiceName
    profile: dict[str, Any]
    connection: dict[str, Any] | None = None
    active_model_id: str | None = None
    activate: bool = False


class RegistryEditPayload(BaseModel):
    kind: Literal["provider", "model", "default", "task_choice"]
    task: dict[str, Any] | None = None
    ref: dict[str, Any] | None = None
    fields: dict[str, Any] | None = None
    service: ServiceName | None = None
    profile_id: str | None = None
    model_id: str | None = None
    model: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    delete: bool = False


class CatalogServicePayload(BaseModel):
    """One model-catalog service to promote without touching other drafts."""

    service: ServiceName
    config: dict[str, Any]


class SettingsDraftPayload(BaseModel):
    """The unapplied settings envelope, as the settings UI holds it."""

    catalog: dict[str, Any] | None = None
    # Opaque per-page state, keyed by the string the page registers with.
    extensions: dict[str, Any] = Field(default_factory=dict)


class CodexOAuthCallbackPayload(BaseModel):
    callback_url: str


class CodexReasoningEffortUpdate(BaseModel):
    model: str = Field(min_length=1)
    reasoning_effort: str | None = None


class FetchModelsPayload(BaseModel):
    binding: str = ""
    base_url: str = ""
    api_key: str | None = None
    profile_id: str | None = None
    # Which LLM-shaped service the profile lives in (for resolving a masked key).
    service: Literal["llm", "task"] = "llm"
    # The profile's API format; decides whether /models takes Anthropic headers.
    api_format: str | None = None


class ModelCapabilitiesQuery(BaseModel):
    binding: str = ""
    model: str = ""


class ProviderProbePayload(BaseModel):
    binding: str = "openai"
    base_url: str = ""
    api_key: str | list[str] | None = None
    api_format: str = "auto"
    api_version: str = ""
    extra_headers: dict[str, str] | str | None = None
    service: ServiceName = "llm"
    profile_id: str | None = None
    connection_id: str | None = None


@contextlib.contextmanager
def _runtime_catalog_write() -> Iterator[None]:
    """Bracket a write to the model catalog, resetting clients if it landed.

    The LLM and embedding clients are process-wide singletons that resolve from
    this one file. Resetting them only when the file actually changed keeps a
    settings visit that re-applies the same configuration from dropping an
    in-flight turn into the provider retry ladder.
    """
    service = get_model_catalog_service()
    before = service.load()
    yield
    if service.load() == before:
        return
    logger.warning(
        "Admin applied catalog; resetting global LLM/embedding clients. "
        "In-flight user turns may flip backend client mid-call."
    )
    from masterly.services.embedding.client import reset_embedding_client
    from masterly.services.llm.client import reset_llm_client

    clear_llm_config_cache()
    reset_llm_client()
    reset_embedding_client()


def _require_owner() -> None:
    if not get_current_user().is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Model configuration is managed by the group owner.",
        )


def _llm_provider_label(name: str, label: str) -> str:
    if name == "custom":
        return "Custom (OpenAI API)"
    if name == "custom_anthropic":
        return "Custom (Anthropic API)"
    return label


def _provider_choices() -> dict[str, list[dict[str, Any]]]:
    """Build dropdown options for provider selection, keyed by service type."""
    from masterly.services.config.provider_runtime import (
        DEPRECATED_SEARCH_PROVIDERS,
        EMBEDDING_PROVIDERS,
        SEARCH_PROVIDERS,
    )
    from masterly.services.provider_registry import PROVIDERS

    llm = sorted(
        [
            {
                "value": s.name,
                "label": _llm_provider_label(s.name, s.label),
                "base_url": s.default_api_base,
                "auth_mode": s.auth_mode,
                "supports_wire_api_selection": s.supports_wire_api_selection,
                # Which protocols a profile on this vendor may pick, and the
                # vendor endpoint each one lives at when that differs.
                "api_formats": list(s.api_formats),
                "default_api_format": s.default_api_format,
                "base_urls": {
                    api_format: s.default_api_base_for(api_format)
                    for api_format in s.api_formats
                    if s.default_api_base_for(api_format)
                },
                # Legacy entries stay resolvable for stored catalogs but are
                # not offered for new profiles.
                "status": "legacy" if s.is_legacy else "supported",
            }
            for s in PROVIDERS
        ],
        key=lambda p: p["label"].lower(),
    )
    embedding = sorted(
        [
            {
                "value": name,
                "label": spec.label,
                "base_url": spec.default_api_base,
                "default_dim": str(spec.default_dim) if spec.default_dim else "",
            }
            for name, spec in EMBEDDING_PROVIDERS.items()
            if name != "custom_openai_sdk"
        ],
        key=lambda p: p["label"].lower(),
    )
    # No search provider ships a default base_url: only SearXNG takes one, and
    # it is the operator's own instance.
    search = [
        {
            "value": name,
            "label": spec.label,
            "base_url": "",
            "requires_api_key": spec.requires_api_key,
            "requires_base_url": spec.requires_base_url,
            "soft_fallback": spec.soft_fallback,
            "status": "supported",
        }
        for name, spec in SEARCH_PROVIDERS.items()
    ]
    # Retired providers ride along marked rather than offered, so a stale
    # catalog can be told apart from a typo. The dropdown filters them out.
    search += [
        {
            "value": name,
            "label": name,
            "base_url": "",
            "requires_api_key": False,
            "requires_base_url": False,
            "soft_fallback": True,
            "status": "deprecated",
        }
        for name in sorted(DEPRECATED_SEARCH_PROVIDERS)
    ]
    return {
        "llm": llm,
        # Same shape, same vendors: the task service stands in for the LLM.
        "task": llm,
        "embedding": embedding,
        "search": search,
    }


def _match_service_provider(provider: str, table: dict[str, Any]) -> tuple[str, Any] | None:
    """Find *provider*'s entry in one service's provider table.

    Vendors are not named identically across tables, so an exact key miss falls
    back to the spec's own keywords.
    """
    if provider in table:
        return provider, table[provider]
    for name, spec in table.items():
        if provider in getattr(spec, "keywords", ()):
            return name, spec
    return None


def _connection_targets() -> list[dict[str, Any]]:
    """Which services one vendor credential can configure, and with what.

    Answers "if I paste this vendor's key here, what does it get me?" by joining
    the LLM registry with the embedding table on the vendor.
    """
    from masterly.services.config.provider_runtime import EMBEDDING_PROVIDERS
    from masterly.services.provider_registry import PROVIDERS

    embedding_table = {k: v for k, v in EMBEDDING_PROVIDERS.items() if k != "custom_openai_sdk"}
    targets: list[dict[str, Any]] = []
    for spec in PROVIDERS:
        # OAuth vendors sign in through their own flow; there is no key to share.
        if spec.is_oauth:
            continue
        services: dict[str, dict[str, Any]] = {
            "llm": {
                "provider": spec.name,
                "base_url": spec.default_api_base,
                "default_model": "",
            }
        }
        match = _match_service_provider(spec.name, embedding_table)
        if match is not None:
            name, service_spec = match
            services["embedding"] = {
                "provider": name,
                "base_url": service_spec.default_api_base,
                "default_model": service_spec.default_model,
                "default_dim": str(service_spec.default_dim) if service_spec.default_dim else "",
            }
        targets.append(
            {
                "provider": spec.name,
                "label": _llm_provider_label(spec.name, spec.label),
                "default_base_url": spec.default_api_base,
                "services": services,
            }
        )
    return sorted(targets, key=lambda item: str(item["label"]).lower())


@router.get("")
async def get_settings():
    if not get_current_user().is_owner:
        # Learners never see the catalog (provider URLs or keys).
        return {"ui": get_ui_settings()}
    from masterly.services.model_selection.tasks import task_kind_payload

    return {
        "ui": get_ui_settings(),
        "catalog": redact_catalog_secrets(get_model_catalog_service().load()),
        "providers": _provider_choices(),
        "connection_targets": _connection_targets(),
        # What actually runs on the background task model, from the call sites.
        "task_kinds": task_kind_payload(),
    }


@router.post("/apply/registry")
async def apply_registry_edit(payload: RegistryEditPayload):
    """Promote one provider, model, or default without replacing other drafts."""
    _require_owner()
    from masterly.services.settings.registry_edit import merge_registry_edit

    service = get_model_catalog_service()
    draft_service = get_settings_draft_service()
    stored = draft_service.load()
    current = service.load()
    edit = payload.model_dump(exclude_none=True)
    try:
        proposed = merge_registry_edit(current, edit, stored_draft=stored.get("catalog"))
        proposed = reconcile_codex_catalog_update(current, proposed)
        draft_catalog = stored.get("catalog")
        if isinstance(draft_catalog, dict):
            stored["catalog"] = merge_registry_edit(draft_catalog, edit, stored_draft=proposed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with _runtime_catalog_write():
        service.apply(proposed)
    catalog = service.load()
    if stored.get("catalog") == catalog:
        stored["catalog"] = None
    if is_empty_draft(stored):
        draft_service.clear()
        public_draft = None
    else:
        public_draft = redact_draft(draft_service.save(stored))
    return {"catalog": redact_catalog_secrets(catalog), "draft": public_draft}


@router.post("/apply/provider")
async def apply_provider_edit(payload: ProviderEditPayload):
    """Save the provider on screen, preserving every unrelated live/draft entry."""
    _require_owner()
    from masterly.services.settings.provider_edit import merge_provider_edit

    service = get_model_catalog_service()
    draft_service = get_settings_draft_service()
    stored = draft_service.load()
    current = service.load()
    try:
        proposed = merge_provider_edit(
            current,
            payload.service,
            payload.profile,
            connection=payload.connection,
            active_model_id=payload.active_model_id,
            activate=payload.activate,
            stored_draft=stored.get("catalog"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reconciled = reconcile_codex_catalog_update(current, proposed)
    with _runtime_catalog_write():
        service.apply(reconciled)
    catalog = service.load()
    draft_catalog = stored.get("catalog")
    if isinstance(draft_catalog, dict):
        # Advance only the addressed profile in a saved draft, preserving edits
        # to its sibling providers and to all non-model settings.
        saved_profile = next(
            item
            for item in catalog["services"][payload.service]["profiles"]
            if item["id"] == payload.profile["id"]
        )
        saved_connection = next(
            (
                item
                for item in catalog.get("connections", [])
                if item["id"] == (payload.connection or {}).get("id")
            ),
            None,
        )
        stored["catalog"] = merge_provider_edit(
            draft_catalog,
            payload.service,
            saved_profile,
            connection=saved_connection,
            activate=payload.activate,
            active_model_id=payload.active_model_id,
        )
        if stored["catalog"] == catalog:
            stored["catalog"] = None
    if is_empty_draft(stored):
        draft_service.clear()
        public_draft = None
    else:
        public_draft = redact_draft(draft_service.save(stored))
    return {"catalog": redact_catalog_secrets(catalog), "draft": public_draft}


@router.post("/apply/service")
async def apply_catalog_service(payload: CatalogServicePayload):
    """Apply one model service while leaving every other draft untouched."""
    _require_owner()
    service = get_model_catalog_service()
    current = service.load()
    draft_service = get_settings_draft_service()
    stored_draft = draft_service.load()
    proposed = deepcopy(current)
    proposed.setdefault("services", {})[payload.service] = deepcopy(payload.config)
    restored = restore_catalog_secrets(proposed, stored_draft.get("catalog") or current)
    restored = restore_catalog_secrets(restored, current)
    if payload.service == "task" and payload.config.get("mode") == "reference":
        from masterly.services.model_selection import apply_llm_selection_to_catalog

        try:
            selection = payload.config.get("selection")
            if not selection or not selection.get("profile_id") or not selection.get("model_id"):
                raise ValueError("Choose a configured task model first.")
            apply_llm_selection_to_catalog(restored, selection)
        except (ValueError, AttributeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    reconciled = reconcile_codex_catalog_update(current, restored)
    with _runtime_catalog_write():
        runtime = service.apply(reconciled)
    catalog = service.load()

    # A saved draft holds a full catalog. Keep it, but advance this one service
    # to the value that is now live, so reloading the page does not bring the
    # pre-apply configuration back over the live one.
    draft_catalog = stored_draft.get("catalog")
    if isinstance(draft_catalog, dict):
        draft_catalog.setdefault("services", {})[payload.service] = deepcopy(
            catalog["services"][payload.service]
        )
        stored_draft["catalog"] = None if draft_catalog == catalog else draft_catalog

    if is_empty_draft(stored_draft):
        draft_service.clear()
        public_draft = None
    else:
        public_draft = redact_draft(draft_service.save(stored_draft))

    return {
        "message": f"{payload.service} settings applied to runtime.",
        "catalog": redact_catalog_secrets(catalog),
        "draft": public_draft,
        "runtime": runtime,
    }


@router.get("/draft")
async def get_settings_draft():
    """Return the unapplied draft, or nothing when there is none.

    Nothing that resolves runtime configuration reads the draft: that is the
    whole difference between saving a draft and applying it.
    """
    _require_owner()
    draft = get_settings_draft_service().load()
    if is_empty_draft(draft):
        return {"draft": None}
    return {"draft": redact_draft(draft)}


@router.put("/draft")
async def update_settings_draft(payload: SettingsDraftPayload):
    _require_owner()
    service = get_settings_draft_service()
    stored = service.load()
    merged = merge_draft_secrets(
        payload.model_dump(),
        stored,
        get_model_catalog_service().load(),
    )
    if is_empty_draft(merged):
        service.clear()
        return {"draft": None}
    saved = service.save(merged)
    return {"draft": redact_draft(saved)}


@router.delete("/draft")
async def discard_settings_draft():
    _require_owner()
    get_settings_draft_service().clear()
    return {"draft": None}


@router.post("/apply")
async def apply_catalog(payload: CatalogPayload | None = None):
    """Move settings into the files the runtime reads, and clear the draft.

    With no body this promotes the stored draft's catalog, which is how the
    settings UI applies: credentials that only ever existed in a draft would
    otherwise have to round-trip through the browser as placeholders.
    """
    _require_owner()
    service = get_model_catalog_service()
    draft_service = get_settings_draft_service()
    current = service.load()
    if payload is not None:
        proposed = restore_catalog_secrets(payload.catalog, current)
    else:
        draft_catalog = draft_service.load().get("catalog")
        proposed = (
            restore_catalog_secrets(draft_catalog, current)
            if isinstance(draft_catalog, dict)
            else current
        )
    catalog = reconcile_codex_catalog_update(current, proposed)
    with _runtime_catalog_write():
        applied = service.apply(catalog)
    catalog_after = service.load()
    draft_service.clear()
    return {
        "message": "Catalog applied to runtime settings.",
        "catalog": redact_catalog_secrets(catalog_after),
        "runtime": applied,
    }


@router.post("/test-provider")
async def test_provider_connection(payload: ProviderProbePayload):
    """Test current form credentials, resolving masks from draft/live settings by ID."""
    _require_owner()
    from masterly.services.settings.provider_probe import probe_provider, probe_search_provider

    current = get_model_catalog_service().load()
    saved = get_settings_draft_service().load().get("catalog")
    source = restore_catalog_secrets(saved, current) if isinstance(saved, dict) else current
    fields = payload.model_dump()
    if payload.connection_id:
        fields["id"] = payload.connection_id
        proposed = {"connections": [fields]}
        resolved = restore_catalog_secrets(proposed, source)["connections"][0]
    else:
        fields["id"] = payload.profile_id
        proposed = {"services": {payload.service: {"profiles": [fields]}}}
        resolved = restore_catalog_secrets(proposed, source)["services"][payload.service][
            "profiles"
        ][0]
    from masterly.services.keypool import primary_api_key

    key = primary_api_key(resolved.get("api_key"))
    headers = resolved.get("extra_headers") or {}
    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid extra headers JSON.") from exc
    if not isinstance(headers, dict) or any(not isinstance(v, str) for v in headers.values()):
        raise HTTPException(status_code=400, detail="Extra headers must contain text values.")
    if (
        (payload.api_key == CATALOG_SECRET_MASK and not key)
        or key == CATALOG_SECRET_MASK
        or any(v == CATALOG_SECRET_MASK for v in headers.values())
    ):
        raise HTTPException(
            status_code=400, detail="Saved credentials were not found. Enter the key again."
        )
    if payload.service == "search":
        return await probe_search_provider(payload.binding, payload.base_url, key)
    return await probe_provider(
        payload.binding, payload.base_url, key, payload.api_format, headers, payload.api_version
    )


@router.post("/fetch-models")
async def fetch_models_from_provider(payload: FetchModelsPayload):
    """List the model IDs an OpenAI-compatible provider exposes.

    Thin HTTP surface over ``factory.fetch_models`` so the settings UI can
    populate a model picker from ``base_url`` + ``api_key`` instead of making
    the user type model IDs by hand.
    """
    _require_owner()
    from masterly.services.llm.factory import fetch_models as fetch_llm_models

    base_url = (payload.base_url or "").strip()
    binding = (payload.binding or "").strip().lower() or "openai"
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url is required for this provider.",
        )

    api_key = payload.api_key
    api_format = (payload.api_format or "").strip().lower()
    if payload.profile_id and (api_key == CATALOG_SECRET_MASK or not api_format):
        service = get_model_catalog_service().load().get("services", {}).get(payload.service, {})
        profile = next(
            (item for item in service.get("profiles", []) if item.get("id") == payload.profile_id),
            None,
        )
        if api_key == CATALOG_SECRET_MASK:
            api_key = profile.get("api_key") if profile else None
        if not api_format and profile:
            api_format = str(profile.get("api_format") or "")

    try:
        model_ids = await fetch_llm_models(binding, base_url, api_key, api_format or "auto")
    except Exception as exc:  # noqa: BLE001 — surface any provider error as 502
        logger.exception("Failed to fetch models from %s", base_url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider request failed: {exc}",
        ) from exc

    return {"models": [{"id": model_id, "name": model_id} for model_id in model_ids]}


@router.post("/model-capabilities")
async def resolve_model_capabilities(payload: ModelCapabilitiesQuery):
    """What the built-in capability tables assume for one provider/model pair.

    The settings UI shows these as the value "Auto" resolves to next to each
    per-model override, so a user can see what they are overriding.
    """
    _require_owner()
    from masterly.services.llm.capabilities import effective_capabilities

    binding = (payload.binding or "").strip().lower() or "openai"
    model = (payload.model or "").strip()
    return {
        "binding": binding,
        "model": model,
        "defaults": effective_capabilities(binding, model),
    }


@router.post("/tests/{service}/start")
async def start_service_test(service: ServiceName, payload: CatalogPayload | None = None):
    _require_owner()
    catalog = None
    if payload is not None:
        catalog_service = get_model_catalog_service()
        current = catalog_service.load()
        saved = get_settings_draft_service().load().get("catalog")
        catalog = (
            restore_catalog_secrets(payload.catalog, saved)
            if isinstance(saved, dict)
            else payload.catalog
        )
        catalog = restore_catalog_secrets(catalog, current)
        catalog = catalog_service.resolve_connections(catalog)
    run = get_config_test_runner().start(service, catalog)
    return {"run_id": run.id}


@router.get("/tests/{service}/{run_id}/events")
async def stream_service_test_events(service: str, run_id: str, request: Request):
    _require_owner()
    runner = get_config_test_runner()
    run = runner.get(run_id)

    async def event_stream():
        sent = 0
        while True:
            if await request.is_disconnected():
                return
            events = run.snapshot(sent)
            if events:
                for event in events:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                sent += len(events)
                if events[-1]["type"] in {"completed", "failed"}:
                    return
            else:
                yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(0.35)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/tests/{service}/{run_id}/cancel")
async def cancel_service_test(service: str, run_id: str):
    _require_owner()
    get_config_test_runner().cancel(run_id)
    return {"message": "Cancelled"}


# --- ChatGPT (Codex) sign-in -------------------------------------------------
# One login for the whole deployment: the administrator signs in, every account
# runs on it (see ``services.codex_auth.service``).


def _codex_http_exception(error: CodexAuthError) -> HTTPException:
    return HTTPException(
        status_code=error.http_status,
        detail={"code": error.code, "message": error.public_message},
    )


@router.post("/providers/openai-codex/oauth/start")
async def start_openai_codex_oauth() -> dict[str, Any]:
    _require_owner()
    try:
        return await get_codex_oauth_service().start_login()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.get("/providers/openai-codex/oauth/status")
async def get_openai_codex_oauth_status() -> dict[str, Any]:
    _require_owner()
    try:
        return get_codex_oauth_service().public_status()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.post("/providers/openai-codex/oauth/complete")
async def complete_openai_codex_oauth(payload: CodexOAuthCallbackPayload) -> dict[str, Any]:
    """Finish a waiting login from a callback address the administrator pasted.

    The provider redirects the browser to a loopback listener on the server.
    When the browser runs on another machine that address fails to load while
    the sign-in waits; pasting it here completes the same exchange.
    """
    _require_owner()
    try:
        return await get_codex_oauth_service().complete_login_with_callback_url(
            payload.callback_url
        )
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.post("/providers/openai-codex/oauth/cancel")
async def cancel_openai_codex_oauth() -> dict[str, Any]:
    _require_owner()
    try:
        return await get_codex_oauth_service().cancel_login()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.post("/providers/openai-codex/oauth/logout")
async def logout_openai_codex_oauth() -> dict[str, Any]:
    _require_owner()
    try:
        return await get_codex_oauth_service().logout()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.post("/providers/openai-codex/models/refresh")
async def refresh_openai_codex_models() -> dict[str, Any]:
    _require_owner()
    try:
        return await get_codex_oauth_service().refresh_models()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.post("/providers/openai-codex/models/reasoning-effort")
async def update_openai_codex_reasoning_effort(
    payload: CodexReasoningEffortUpdate,
) -> dict[str, Any]:
    _require_owner()
    # The Codex service writes the catalog the runtime resolves against; bracket
    # it like every other catalog write so the next turn uses the new effort.
    with _runtime_catalog_write():
        try:
            return await get_codex_oauth_service().set_reasoning_effort(
                payload.model,
                payload.reasoning_effort,
            )
        except CodexAuthError as exc:
            raise _codex_http_exception(exc) from None

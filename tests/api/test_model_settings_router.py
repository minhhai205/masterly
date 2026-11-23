"""Models & services API: provider choices, secrets, draft/apply, admin-only access."""

from __future__ import annotations

import contextlib
from copy import deepcopy
import json
from typing import Any

from fastapi.testclient import TestClient
import pytest

from masterly.api.routers import model_settings as settings_router
from masterly.services.config import CATALOG_SECRET_MASK
from masterly.services.config.provider_runtime import (
    ResolvedEmbeddingConfig,
    ResolvedLLMConfig,
)
from masterly.services.embedding import client as embedding_client_module
from masterly.services.embedding import config as embedding_config_module
from masterly.services.llm import client as llm_client_module
from masterly.services.llm import config as llm_config_module
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME

LEARNER = ("learner-f03", "learner-pass")


class _FakeEmbeddingAdapter:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    async def embed(self, request):
        return type("EmbeddingResponse", (), {"embeddings": [[] for _ in request.texts]})()


class _FakeCatalogService:
    def __init__(self, catalog: dict[str, Any]):
        self._catalog = deepcopy(catalog)

    def save(self, catalog: dict[str, Any]) -> dict[str, Any]:
        self._catalog = deepcopy(catalog)
        return deepcopy(self._catalog)

    def load(self) -> dict[str, Any]:
        return deepcopy(self._catalog)

    def apply(self, catalog: dict[str, Any]) -> dict[str, Any]:
        current = self.save(catalog)
        return {
            "catalog_path": "memory://model_catalog.json",
            "services": list(current["services"]),
        }


def _build_catalog(
    *,
    llm_model: str,
    llm_base_url: str,
    llm_api_key: str,
    embedding_model: str,
    embedding_base_url: str,
    embedding_api_key: str,
) -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-profile-default",
                "active_model_id": "llm-model-default",
                "profiles": [
                    {
                        "id": "llm-profile-default",
                        "name": "Default LLM Endpoint",
                        "binding": "openai",
                        "base_url": llm_base_url,
                        "api_key": llm_api_key,
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {"id": "llm-model-default", "name": llm_model, "model": llm_model}
                        ],
                    }
                ],
            },
            "embedding": {
                "active_profile_id": "embedding-profile-default",
                "active_model_id": "embedding-model-default",
                "profiles": [
                    {
                        "id": "embedding-profile-default",
                        "name": "Default Embedding Endpoint",
                        "binding": "openai",
                        "base_url": embedding_base_url,
                        "api_key": embedding_api_key,
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "embedding-model-default",
                                "name": embedding_model,
                                "model": embedding_model,
                                "dimension": "1536",
                            }
                        ],
                    }
                ],
            },
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


def _catalog(tag: str) -> dict[str, Any]:
    return _build_catalog(
        llm_model=f"gpt-{tag}",
        llm_base_url=f"https://{tag}-llm.example/v1",
        llm_api_key=f"{tag}-llm-key",
        embedding_model=f"text-embedding-{tag}",
        embedding_base_url=f"https://{tag}-embedding.example/v1/embeddings",
        embedding_api_key=f"{tag}-embedding-key",
    )


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, service: _FakeCatalogService) -> None:
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(
        embedding_client_module, "_resolve_adapter_class", lambda _binding: _FakeEmbeddingAdapter
    )

    def _resolve_llm_runtime_config() -> ResolvedLLMConfig:
        profile = service.load()["services"]["llm"]["profiles"][0]
        model = profile["models"][0]
        return ResolvedLLMConfig(
            model=model["model"],
            provider_name=profile["binding"],
            provider_mode="standard",
            binding_hint=profile["binding"],
            binding=profile["binding"],
            api_key=profile["api_key"],
            base_url=profile["base_url"],
            effective_url=profile["base_url"],
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
        )

    def _resolve_embedding_runtime_config() -> ResolvedEmbeddingConfig:
        profile = service.load()["services"]["embedding"]["profiles"][0]
        model = profile["models"][0]
        return ResolvedEmbeddingConfig(
            model=model["model"],
            provider_name=profile["binding"],
            provider_mode="standard",
            binding_hint=profile["binding"],
            binding=profile["binding"],
            api_key=profile["api_key"],
            base_url=profile["base_url"],
            effective_url=profile["base_url"],
            api_version=None,
            extra_headers={},
            dimension=int(model["dimension"]),
            request_timeout=60,
            batch_size=10,
        )

    monkeypatch.setattr(llm_config_module, "resolve_llm_runtime_config", _resolve_llm_runtime_config)
    monkeypatch.setattr(
        embedding_config_module,
        "resolve_embedding_runtime_config",
        _resolve_embedding_runtime_config,
    )


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    llm_config_module.clear_llm_config_cache()
    llm_client_module.reset_llm_client()
    embedding_client_module.reset_embedding_client()
    yield
    llm_config_module.clear_llm_config_cache()
    llm_client_module.reset_llm_client()
    embedding_client_module.reset_embedding_client()


@pytest.fixture(autouse=True)
def _as_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings_router, "_require_settings_admin", lambda: None)


# --- Provider choices -------------------------------------------------------


def test_only_the_four_masterly_services_are_offered() -> None:
    assert set(settings_router._provider_choices()) == {"llm", "task", "embedding", "search"}


def test_embedding_provider_choices_use_full_endpoint_urls() -> None:
    embedding = {item["value"]: item for item in settings_router._provider_choices()["embedding"]}

    assert embedding["openrouter"]["base_url"] == "https://openrouter.ai/api/v1/embeddings"
    assert embedding["ollama"]["base_url"] == "http://localhost:11434/api/embed"
    assert embedding["openai"]["base_url"] == "https://api.openai.com/v1/embeddings"
    assert "custom_openai_sdk" not in embedding


def test_codex_provider_choice_is_advertised_as_oauth() -> None:
    llm = {item["value"]: item for item in settings_router._provider_choices()["llm"]}

    assert llm["openai_codex"] == {
        "value": "openai_codex",
        "label": "OpenAI Codex",
        "base_url": "https://chatgpt.com/backend-api",
        "auth_mode": "oauth",
        "supports_wire_api_selection": False,
        # OAuth fixes the protocol: nothing for a profile to choose.
        "api_formats": [],
        "default_api_format": "auto",
        "base_urls": {},
        "status": "supported",
    }
    assert llm["openai"]["auth_mode"] == "api_key"


def test_dropped_providers_are_not_offered() -> None:
    llm = {item["value"] for item in settings_router._provider_choices()["llm"]}

    assert "codebuddy" not in llm
    assert "github_copilot" not in llm


def test_provider_choices_advertise_wire_api_support_from_backend_metadata() -> None:
    llm = {item["value"]: item for item in settings_router._provider_choices()["llm"]}

    assert llm["custom"]["supports_wire_api_selection"] is True
    assert llm["openai"]["supports_wire_api_selection"] is True
    assert llm["azure_openai"]["supports_wire_api_selection"] is False
    assert llm["custom_anthropic"]["supports_wire_api_selection"] is False


def test_connection_targets_cover_llm_and_embedding_only() -> None:
    targets = {item["provider"]: item for item in settings_router._connection_targets()}

    assert "openai_codex" not in targets  # OAuth: no key to share
    assert set(targets["openai"]["services"]) == {"llm", "embedding"}


# --- Secrets and runtime clients -------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_never_returns_catalog_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from masterly.multi_user.models import LOCAL_ADMIN_ID, CurrentUser
    from masterly.multi_user.paths import admin_scope

    catalog = _catalog("secret")
    catalog["services"]["llm"]["profiles"][0]["extra_headers"] = {"Authorization": "Bearer secret"}
    monkeypatch.setattr(
        settings_router, "get_model_catalog_service", lambda: _FakeCatalogService(catalog)
    )
    monkeypatch.setattr(
        settings_router,
        "get_current_user",
        lambda: CurrentUser(id=LOCAL_ADMIN_ID, username="admin", role="admin", scope=admin_scope()),
    )

    response = await settings_router.get_settings()

    llm_profile = response["catalog"]["services"]["llm"]["profiles"][0]
    embedding_profile = response["catalog"]["services"]["embedding"]["profiles"][0]
    assert llm_profile["api_key"] == CATALOG_SECRET_MASK
    assert llm_profile["extra_headers"]["Authorization"] == CATALOG_SECRET_MASK
    assert embedding_profile["api_key"] == CATALOG_SECRET_MASK
    assert "secret-llm-key" not in json.dumps(response)
    assert "secret-embedding-key" not in json.dumps(response)
    assert [kind["group"] for kind in response["task_kinds"]] == [
        "chat",
        "chat",
        "chat",
        "mastery",
        "mastery",
    ]


@pytest.mark.asyncio
async def test_apply_catalog_invalidates_runtime_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _FakeCatalogService(_catalog("before"))
    _patch_runtime(monkeypatch, service)
    applied_catalog = _catalog("after")

    llm_config_module.get_llm_config()
    old_llm_client = llm_client_module.get_llm_client()
    old_embedding_client = embedding_client_module.get_embedding_client()

    response = await settings_router.apply_catalog(
        settings_router.CatalogPayload(catalog=applied_catalog)
    )

    new_llm_client = llm_client_module.get_llm_client()
    new_embedding_client = embedding_client_module.get_embedding_client()
    assert response["catalog"] == settings_router.redact_catalog_secrets(applied_catalog)
    assert service.load() == applied_catalog
    assert llm_config_module.get_llm_config().model == "gpt-after"
    assert new_llm_client is not old_llm_client
    assert new_llm_client.config.base_url == "https://after-llm.example/v1"
    assert new_embedding_client is not old_embedding_client
    assert new_embedding_client.config.model == "text-embedding-after"


@pytest.mark.asyncio
async def test_reapplying_an_unchanged_catalog_keeps_the_runtime_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An apply that changes nothing must not reset the shared clients."""
    catalog = _catalog("same")
    service = _FakeCatalogService(catalog)
    _patch_runtime(monkeypatch, service)

    llm_config_module.get_llm_config()
    old_llm_client = llm_client_module.get_llm_client()
    old_embedding_client = embedding_client_module.get_embedding_client()

    await settings_router.apply_catalog(settings_router.CatalogPayload(catalog=catalog))

    assert llm_client_module.get_llm_client() is old_llm_client
    assert embedding_client_module.get_embedding_client() is old_embedding_client


@pytest.mark.asyncio
async def test_reapplying_one_unchanged_service_keeps_the_runtime_clients(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from masterly.services.config.settings_draft import SettingsDraftService

    catalog = _catalog("service")
    service = _FakeCatalogService(catalog)
    _patch_runtime(monkeypatch, service)
    draft_service = SettingsDraftService(tmp_path / "settings_draft.json")
    monkeypatch.setattr(settings_router, "get_settings_draft_service", lambda: draft_service)

    old_llm_client = llm_client_module.get_llm_client()
    old_embedding_client = embedding_client_module.get_embedding_client()

    await settings_router.apply_catalog_service(
        settings_router.CatalogServicePayload(service="llm", config=catalog["services"]["llm"])
    )

    assert llm_client_module.get_llm_client() is old_llm_client
    assert embedding_client_module.get_embedding_client() is old_embedding_client


@pytest.mark.asyncio
async def test_apply_catalog_service_only_promotes_the_selected_service_and_updates_saved_draft(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from masterly.services.config.settings_draft import SettingsDraftService

    live = _catalog("live")
    draft = deepcopy(live)
    draft["services"]["embedding"]["profiles"][0]["base_url"] = "https://new-embedding.example/v1"
    draft["services"]["embedding"]["profiles"][0]["api_key"] = "new-embedding-key"
    draft["services"]["llm"]["profiles"][0]["name"] = "Unapplied LLM edit"

    catalog_service = _FakeCatalogService(live)
    draft_service = SettingsDraftService(tmp_path / "settings_draft.json")
    draft_service.save({"catalog": draft, "extensions": {}})
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: catalog_service)
    monkeypatch.setattr(settings_router, "get_settings_draft_service", lambda: draft_service)
    monkeypatch.setattr(settings_router, "_runtime_catalog_write", contextlib.nullcontext)

    response = await settings_router.apply_catalog_service(
        settings_router.CatalogServicePayload(
            service="embedding", config=draft["services"]["embedding"]
        )
    )

    applied = catalog_service.load()
    embedding = applied["services"]["embedding"]["profiles"][0]
    assert embedding["base_url"] == "https://new-embedding.example/v1"
    assert embedding["api_key"] == "new-embedding-key"
    assert applied["services"]["llm"]["profiles"][0]["name"] == "Default LLM Endpoint"

    remaining = draft_service.load()
    assert remaining["catalog"]["services"]["embedding"] == applied["services"]["embedding"]
    assert remaining["catalog"]["services"]["llm"]["profiles"][0]["name"] == "Unapplied LLM edit"
    assert response["draft"] is not None
    assert response["catalog"]["services"]["embedding"]["profiles"][0]["api_key"] == (
        CATALOG_SECRET_MASK
    )


# --- Model listing ---------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_models_returns_picker_options(monkeypatch: pytest.MonkeyPatch) -> None:
    import masterly.services.llm.factory as factory_module

    async def _fake_fetch(
        binding: str, base_url: str, api_key: str | None = None, api_format: str = "auto"
    ):
        assert binding == "openai"  # "OpenAI" is normalized to lowercase
        assert base_url == "https://api.example.com/v1"
        assert api_key == "sk-x"
        return ["gpt-4o", "gpt-4o-mini"]

    monkeypatch.setattr(factory_module, "fetch_models", _fake_fetch)

    response = await settings_router.fetch_models_from_provider(
        settings_router.FetchModelsPayload(
            binding="OpenAI", base_url="https://api.example.com/v1", api_key="sk-x"
        )
    )

    assert response == {
        "models": [
            {"id": "gpt-4o", "name": "gpt-4o"},
            {"id": "gpt-4o-mini", "name": "gpt-4o-mini"},
        ]
    }


@pytest.mark.asyncio
async def test_fetch_models_resolves_masked_key_server_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import masterly.services.llm.factory as factory_module

    catalog = _build_catalog(
        llm_model="gpt-4o-mini",
        llm_base_url="https://llm.example/v1",
        llm_api_key="stored-secret",
        embedding_model="text-embedding-3-small",
        embedding_base_url="https://emb.example/v1/embeddings",
        embedding_api_key="emb-key",
    )
    service = _FakeCatalogService(catalog)
    monkeypatch.setattr(settings_router, "get_model_catalog_service", lambda: service)

    async def _fake_fetch(
        binding: str, base_url: str, api_key: str | None = None, api_format: str = "auto"
    ):
        assert (binding, base_url, api_key) == (
            "openai",
            "https://llm.example/v1",
            "stored-secret",
        )
        return ["gpt-4o-mini"]

    monkeypatch.setattr(factory_module, "fetch_models", _fake_fetch)

    response = await settings_router.fetch_models_from_provider(
        settings_router.FetchModelsPayload(
            binding="openai",
            base_url="https://llm.example/v1",
            api_key=CATALOG_SECRET_MASK,
            profile_id="llm-profile-default",
        )
    )

    assert response == {"models": [{"id": "gpt-4o-mini", "name": "gpt-4o-mini"}]}


@pytest.mark.asyncio
async def test_fetch_models_requires_base_url() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.fetch_models_from_provider(
            settings_router.FetchModelsPayload(base_url="   ")
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_fetch_models_maps_provider_error_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    import masterly.services.llm.factory as factory_module

    async def _boom(binding: str, base_url: str, api_key: str | None = None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(factory_module, "fetch_models", _boom)

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.fetch_models_from_provider(
            settings_router.FetchModelsPayload(binding="custom", base_url="https://x/v1")
        )
    assert exc_info.value.status_code == 502



# --- ChatGPT (Codex) sign-in -------------------------------------------------


class _FakeCodexOAuthService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start_login(self) -> dict[str, Any]:
        self.calls.append("start")
        return {
            "operation_id": "operation-1",
            "authorize_url": "https://auth.openai.com/oauth/authorize?state=opaque",
            "expires_in": 300,
        }

    def public_status(self) -> dict[str, Any]:
        self.calls.append("status")
        return {
            "connection": "connected",
            "operation_id": None,
            "operation_state": None,
            "model_count": 1,
            "catalog_source": "live",
            "catalog_fetched_at": 1_000,
            "active_model": "gpt-5.6-sol",
            "activated": False,
            "error_code": None,
        }

    async def cancel_login(self) -> dict[str, Any]:
        self.calls.append("cancel")
        return self.public_status()

    async def logout(self) -> dict[str, Any]:
        self.calls.append("logout")
        return self.public_status()

    async def refresh_models(self) -> dict[str, Any]:
        self.calls.append("refresh")
        return self.public_status()


@pytest.mark.asyncio
async def test_codex_oauth_routes_return_only_public_service_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCodexOAuthService()
    monkeypatch.setattr(settings_router, "get_codex_oauth_service", lambda: fake)

    started = await settings_router.start_openai_codex_oauth()
    status_payload = await settings_router.get_openai_codex_oauth_status()
    cancelled = await settings_router.cancel_openai_codex_oauth()
    refreshed = await settings_router.refresh_openai_codex_models()
    logged_out = await settings_router.logout_openai_codex_oauth()

    assert set(started) == {"operation_id", "authorize_url", "expires_in"}
    assert (
        "token"
        not in json.dumps([started, status_payload, cancelled, refreshed, logged_out]).lower()
    )
    assert fake.calls == [
        "start",
        "status",
        "cancel",
        "status",
        "refresh",
        "status",
        "logout",
        "status",
    ]


@pytest.mark.asyncio
async def test_codex_oauth_error_maps_to_sanitized_http_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from masterly.services.codex_auth.contracts import CodexAuthError

    class FailingService:
        async def start_login(self) -> dict[str, Any]:
            raise CodexAuthError(
                "token_exchange_failed",
                "Codex sign-in could not be completed.",
                502,
            )

    monkeypatch.setattr(settings_router, "get_codex_oauth_service", lambda: FailingService())

    with pytest.raises(HTTPException) as exc_info:
        await settings_router.start_openai_codex_oauth()

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == {
        "code": "token_exchange_failed",
        "message": "Codex sign-in could not be completed.",
    }


# --- Access through the real app -------------------------------------------


@pytest.fixture(scope="module")
def app():
    from masterly.api.main import app as fastapi_app
    from masterly.services.auth import add_user

    add_user(*LEARNER)
    return fastapi_app


@contextlib.contextmanager
def _signed_in(app, username: str, password: str):
    with TestClient(app) as client:
        resp = client.post("/api/auth/login", json={"username": username, "password": password})
        assert resp.status_code == 200
        yield client


def test_model_settings_need_a_session(app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.undo()  # real admin check
    with TestClient(app) as client:
        assert client.get("/api/settings").status_code == 401
        assert client.get("/api/settings/draft").status_code == 401


def test_learner_sees_only_interface_preferences_and_cannot_touch_models(
    app, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.undo()
    with _signed_in(app, *LEARNER) as client:
        body = client.get("/api/settings").json()
        assert set(body) == {"ui"}
        assert client.get("/api/settings/draft").status_code == 403
        assert client.put("/api/settings/draft", json={"catalog": {}}).status_code == 403
        assert client.delete("/api/settings/draft").status_code == 403
        assert client.post("/api/settings/apply").status_code == 403
        # The ChatGPT login is shared, so only the administrator manages it.
        assert client.get("/api/settings/providers/openai-codex/oauth/status").status_code == 403
        assert client.post("/api/settings/providers/openai-codex/oauth/start").status_code == 403
        assert client.post("/api/settings/providers/openai-codex/oauth/logout").status_code == 403
        assert (
            client.post(
                "/api/settings/apply/service", json={"service": "llm", "config": {}}
            ).status_code
            == 403
        )


def test_admin_reads_the_masked_catalog_and_stages_a_draft(app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.undo()
    with _signed_in(app, ADMIN_USERNAME, ADMIN_PASSWORD) as client:
        body = client.get("/api/settings").json()
        assert set(body["catalog"]["services"]) == {"llm", "task", "embedding", "search"}
        assert {"providers", "connection_targets", "task_kinds"} <= set(body)

        draft = _catalog("staged")
        saved = client.put("/api/settings/draft", json={"catalog": draft}).json()["draft"]
        assert saved["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == (
            CATALOG_SECRET_MASK
        )
        # A draft is not live: the runtime catalog is unchanged until applied.
        live = client.get("/api/settings").json()["catalog"]
        assert live["services"]["llm"]["profiles"] == []
        assert client.delete("/api/settings/draft").json() == {"draft": None}

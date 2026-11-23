"""Models & services API: provider choices, secrets, immediate saves, owner-only access."""

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
from tests.conftest import _DB_UNAVAILABLE, new_learner, new_owner


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
    monkeypatch.setattr(settings_router, "_require_owner", lambda: None)


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
    from masterly.multi_user.models import CurrentUser
    from masterly.multi_user.paths import admin_scope

    catalog = _catalog("secret")
    catalog["services"]["llm"]["profiles"][0]["extra_headers"] = {"Authorization": "Bearer secret"}
    monkeypatch.setattr(
        settings_router, "get_model_catalog_service", lambda: _FakeCatalogService(catalog)
    )
    monkeypatch.setattr(
        settings_router,
        "get_current_user",
        lambda: CurrentUser(
            id="owner",
            email="o@example.com",
            display_name="o",
            role="owner",
            group_id="g",
            scope=admin_scope(),
        ),
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


def _model_edit(model: str) -> settings_router.RegistryEditPayload:
    return settings_router.RegistryEditPayload(
        kind="model",
        service="llm",
        profile_id="llm-profile-default",
        model_id="llm-model-default",
        model={"id": "llm-model-default", "name": model, "model": model},
    )


@pytest.mark.asyncio
async def test_saving_a_model_applies_it_and_resets_runtime_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeCatalogService(_catalog("before"))
    _patch_runtime(monkeypatch, service)

    llm_config_module.get_llm_config()
    old_llm_client = llm_client_module.get_llm_client()
    old_embedding_client = embedding_client_module.get_embedding_client()

    response = await settings_router.apply_registry_edit(_model_edit("gpt-after"))

    assert llm_config_module.get_llm_config().model == "gpt-after"
    assert llm_client_module.get_llm_client() is not old_llm_client
    assert embedding_client_module.get_embedding_client() is not old_embedding_client
    saved = service.load()
    assert saved["services"]["llm"]["profiles"][0]["api_key"] == "before-llm-key"
    assert saved["services"]["embedding"] == _catalog("before")["services"]["embedding"]
    assert response["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == (
        CATALOG_SECRET_MASK
    )
    assert set(response) == {"catalog"}


@pytest.mark.asyncio
async def test_resaving_an_unchanged_model_keeps_the_runtime_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A save that changes nothing must not reset the shared clients."""
    service = _FakeCatalogService(_catalog("same"))
    _patch_runtime(monkeypatch, service)

    llm_config_module.get_llm_config()
    old_llm_client = llm_client_module.get_llm_client()
    old_embedding_client = embedding_client_module.get_embedding_client()

    await settings_router.apply_registry_edit(_model_edit("gpt-same"))

    assert llm_client_module.get_llm_client() is old_llm_client
    assert embedding_client_module.get_embedding_client() is old_embedding_client


@pytest.mark.asyncio
async def test_an_invalid_edit_leaves_the_catalog_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    service = _FakeCatalogService(_catalog("kept"))
    _patch_runtime(monkeypatch, service)
    edit = settings_router.RegistryEditPayload(
        kind="model", service="llm", profile_id="llm-profile-default", model={"id": "x"}
    )

    with pytest.raises(HTTPException) as exc:
        await settings_router.apply_registry_edit(edit)

    assert exc.value.status_code == 400
    assert service.load() == _catalog("kept")


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

    if _DB_UNAVAILABLE is not None:
        pytest.skip("PostgreSQL is not reachable")
    return fastapi_app


@pytest.fixture(scope="module")
def owner(app):
    return new_owner(password="owner-pass")


@pytest.fixture(scope="module")
def learner(owner):
    return new_learner(owner.group_id, password="learner-pass")


@contextlib.contextmanager
def _signed_in(app, account, password: str):
    with TestClient(app) as client:
        resp = client.post("/api/auth/login", json={"email": account.email, "password": password})
        assert resp.status_code == 200
        yield client


def test_model_settings_need_a_session(app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.undo()  # real owner check
    with TestClient(app) as client:
        assert client.get("/api/settings").status_code == 401
        assert client.post("/api/settings/apply/registry", json={"kind": "default"}).status_code == 401


def test_learner_sees_only_interface_preferences_and_cannot_touch_models(
    app, learner, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.undo()
    with _signed_in(app, learner, "learner-pass") as client:
        body = client.get("/api/settings").json()
        assert set(body) == {"ui"}
        assert (
            client.post("/api/settings/apply/registry", json={"kind": "default"}).status_code
            == 403
        )
        # The ChatGPT login belongs to the whole group, so only its owner manages it.
        assert client.get("/api/settings/providers/openai-codex/oauth/status").status_code == 403
        assert client.post("/api/settings/providers/openai-codex/oauth/start").status_code == 403
        assert client.post("/api/settings/providers/openai-codex/oauth/logout").status_code == 403


def test_owner_saves_a_provider_and_reads_it_back_masked(
    app, owner, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.undo()
    with _signed_in(app, owner, "owner-pass") as client:
        body = client.get("/api/settings").json()
        assert set(body["catalog"]["services"]) == {"llm", "task", "embedding", "search"}
        assert {"providers", "connection_targets", "task_kinds"} <= set(body)

        ref = {"connection_id": "conn-router-test"}
        saved = client.post(
            "/api/settings/apply/registry",
            json={
                "kind": "provider",
                "ref": ref,
                "fields": {"name": "Gateway", "provider": "openai", "api_key": "sk-test"},
            },
        )
        assert saved.status_code == 200
        # Saved means live: the next read already has it, with the key masked.
        live = client.get("/api/settings").json()["catalog"]
        connection = next(c for c in live["connections"] if c["id"] == "conn-router-test")
        assert connection["name"] == "Gateway"
        assert connection["api_key"] == CATALOG_SECRET_MASK

        removed = client.post(
            "/api/settings/apply/registry",
            json={"kind": "provider", "ref": ref, "delete": True},
        )
        assert removed.status_code == 200
        live = client.get("/api/settings").json()["catalog"]
        assert all(c["id"] != "conn-router-test" for c in live.get("connections", []))

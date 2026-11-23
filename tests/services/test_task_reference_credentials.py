"""A task model that references a language model reuses its credentials."""

from copy import deepcopy

from masterly.services.config.model_catalog import ModelCatalogService
from masterly.services.config.provider_runtime import resolve_llm_runtime_config


def legacy(tmp_path):
    store = ModelCatalogService(tmp_path / "model_catalog.json")
    catalog = store.load()
    catalog["future_extension"] = {"keep": True}
    for service in ("llm", "task", "embedding"):
        catalog["services"][service].update(
            {
                "active_profile_id": service + "-first",
                "active_model_id": service + "-model",
                "profiles": [
                    {
                        "id": service + "-first",
                        "name": "My account",
                        "binding": "custom",
                        "api_key": "test-old-key",
                        "base_url": "https://example.invalid/v1",
                        "extra_headers": {"X-Account": "test-secret-header"},
                        "future_profile": [1, 2],
                        "models": [
                            {
                                "id": service + "-model",
                                "model": "existing-model",
                                "context_window": "65536",
                                "future_model": {"temperature": 0.3},
                            }
                        ],
                    }
                ],
            }
        )
    return store, store.save(catalog)


def test_task_reference_reuses_credentials_and_keeps_legacy_models(tmp_path):
    store, current = legacy(tmp_path)
    before = deepcopy(current["services"]["task"]["profiles"])
    task = current["services"]["task"]
    task["mode"] = "reference"
    task["selection"] = {"profile_id": "llm-first", "model_id": "llm-model"}
    current["services"]["llm"]["profiles"][0]["api_key"] = "test-new-credential"
    saved = store.save(current)
    config = resolve_llm_runtime_config(saved, service=store, service_name="task")
    assert config.api_key == "test-new-credential"
    assert saved["services"]["task"]["profiles"] == before
    task["mode"] = "inherit"
    from masterly.services.model_selection.tasks import task_service_configured

    assert not task_service_configured(current)
    assert store.save(current)["services"]["task"]["profiles"] == before

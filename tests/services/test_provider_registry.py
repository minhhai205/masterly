from masterly.services.provider_registry import find_by_name, find_gateway


def test_openai_codex_is_not_detected_from_api_base() -> None:
    assert find_gateway(api_base="https://codex.example.com/v1") is None


def test_openai_codex_provider_is_oauth_backed() -> None:
    spec = find_by_name("openai_codex")

    assert spec is not None
    assert spec.auth_mode == "oauth"
    assert spec.env_key == ""



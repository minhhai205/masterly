"""Provider registry for Masterly LLM routing.

Single source of truth for provider metadata. Adding a new provider:
  1. Add a ProviderSpec to PROVIDERS below.
  Done. Env vars, config matching, status display all derive from here.

Order matters — it controls match priority and fallback. Gateways first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic.alias_generators import to_snake


@dataclass(frozen=True)
class ProviderSpec:
    """Single provider metadata entry.

    Placeholders in env_extras values:
      {api_key}  — the user's API key
      {api_base} — api_base from config, or this spec's default_api_base
    """

    name: str
    keywords: tuple[str, ...]
    env_key: str
    display_name: str = ""

    # Which provider implementation to use:
    # "openai_compat" | "anthropic" | "azure_openai" | "openai_codex"
    backend: str = "openai_compat"

    env_extras: tuple[tuple[str, str], ...] = ()
    is_gateway: bool = False
    is_local: bool = False
    detect_by_key_prefix: str = ""
    detect_by_base_keyword: str = ""
    default_api_base: str = ""
    strip_model_prefix: bool = False
    supports_max_completion_tokens: bool = False
    supports_prompt_caching: bool = False
    supports_stream_options: bool = True
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()
    # Bare model-id families too short or generic for substring-based vendor
    # detection. See ``_matches_model_family`` for what a family covers.
    model_id_families: tuple[str, ...] = ()
    is_oauth: bool = False
    is_direct: bool = False
    thinking_style: str = ""
    # Substring patterns (case-insensitive) marking models whose native
    # reasoning trace should be surfaced. When the caller does not pass an
    # explicit reasoning_effort, the provider auto-injects "high" so the
    # thinking_style flag (e.g. extra_body.thinking.type=enabled) is sent.
    reasoning_model_patterns: tuple[str, ...] = ()
    # Exact model ids whose Responses API executes `web_search` server-side.
    # Exact matching is intentional: providers often expose Responses only on
    # one model even when sibling models share the same family prefix.
    native_web_search_models: tuple[str, ...] = ()
    # Endpoints a vendor exposes for a *non-default* API format, e.g. MiniMax
    # serving Anthropic Messages at ``/anthropic`` next to its OpenAI-style
    # ``/v1``. ``default_api_base`` stays the default format's endpoint.
    api_base_by_format: tuple[tuple[str, str], ...] = ()
    # Set on entries kept only so stored catalogs keep resolving: the pair is
    # the (provider, api_format) that expresses the same thing today. Pickers
    # hide these; ``binding`` values in existing files are never rewritten.
    legacy_of: tuple[str, ...] = ()

    @property
    def mode(self) -> str:
        if self.is_oauth:
            return "oauth"
        if self.is_direct:
            return "direct"
        if self.is_gateway:
            return "gateway"
        if self.is_local:
            return "local"
        return "standard"

    @property
    def auth_mode(self) -> str:
        return "oauth" if self.is_oauth else "api_key"

    @property
    def supports_wire_api_selection(self) -> bool:
        """Whether profiles may select an OpenAI wire protocol explicitly."""
        return self.backend == "openai_compat" and not self.is_oauth

    @property
    def is_legacy(self) -> bool:
        return bool(self.legacy_of)

    @property
    def api_formats(self) -> tuple[str, ...]:
        """API formats a profile on this provider may choose between.

        Empty means the format is fixed by the backend (OAuth vendors, Azure)
        and the UI has nothing to offer. Anthropic-backed vendors speak only
        Anthropic Messages. OpenAI-compatible vendors get the OpenAI pair, plus
        Anthropic Messages when the vendor is known to serve it too or when
        the endpoint is user-supplied and could be anything.
        """
        if self.is_oauth or self.backend in {"azure_openai", "openai_codex"}:
            return ()
        if self.backend == "anthropic":
            return ("anthropic",)
        if self.backend != "openai_compat":
            return ()
        formats: tuple[str, ...] = OPENAI_API_FORMATS
        if self.name == "custom" or "anthropic" in dict(self.api_base_by_format):
            formats = (*formats, "anthropic")
        return formats

    @property
    def default_api_format(self) -> str:
        return "anthropic" if self.backend == "anthropic" else "auto"

    def default_api_base_for(self, api_format: str | None) -> str:
        """The vendor endpoint for *api_format*, falling back to the default one."""
        return dict(self.api_base_by_format).get(api_format or "", self.default_api_base)

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()


PROVIDER_ALIASES = {
    "azure": "azure_openai",
    "azure-openai": "azure_openai",
    "azureopenai": "azure_openai",
    "google": "gemini",
    "google_genai": "gemini",
    "claude": "anthropic",
    "openai_compatible": "custom",
    "openai-compatible": "custom",
    "anthropic_compatible": "custom_anthropic",
    "anthropic-compatible": "custom_anthropic",
    "openai-codex": "openai_codex",
}


def canonical_provider_name(name: str | None) -> str | None:
    """Normalize incoming provider names and legacy aliases."""
    if not name:
        return None
    key = name.strip()
    if not key:
        return None
    key = to_snake(key.replace("-", "_"))
    return PROVIDER_ALIASES.get(key, key)


# These Claude families reject explicit temperature and use adaptive thinking.
# Keep one family list for direct Anthropic calls and OpenAI-compatible gateways.
# Older Opus/Sonnet families still accept temperature and budget-token thinking.
ANTHROPIC_EFFORT_BASED_FAMILIES: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)


# ---------------------------------------------------------------------------
# PROVIDERS — the registry.  Order = priority.
# ---------------------------------------------------------------------------

PROVIDERS: tuple[ProviderSpec, ...] = (
    # === Direct (user supplies everything, no auto-detection) ===============
    ProviderSpec(
        name="custom",
        keywords=(),
        env_key="",
        display_name="Custom",
        backend="openai_compat",
        is_direct=True,
    ),
    ProviderSpec(
        name="custom_anthropic",
        keywords=(),
        env_key="",
        display_name="Custom (Anthropic API)",
        backend="anthropic",
        is_direct=True,
        legacy_of=("custom", "anthropic"),
    ),
    ProviderSpec(
        name="azure_openai",
        keywords=("azure", "azure_openai"),
        env_key="",
        display_name="Azure OpenAI",
        backend="azure_openai",
        is_direct=True,
    ),
    # === Gateways (detected by api_key / api_base, route any model) ========
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        backend="openai_compat",
        is_gateway=True,
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
        default_api_base="https://openrouter.ai/api/v1",
        supports_prompt_caching=True,
    ),
    # === Standard providers (matched by model-name keywords) ===============
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        backend="anthropic",
        default_api_base="https://api.anthropic.com/v1",
        supports_prompt_caching=True,
        # This model rule also applies when Claude is reached through a
        # generic OpenAI-compatible binding or gateway.
        model_overrides=tuple(
            (family, {"temperature": None}) for family in ANTHROPIC_EFFORT_BASED_FAMILIES
        ),
    ),
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        backend="openai_compat",
        default_api_base="https://api.openai.com/v1",
        supports_max_completion_tokens=True,
    ),
    ProviderSpec(
        name="openai_codex",
        keywords=("openai-codex",),
        env_key="",
        display_name="OpenAI Codex",
        backend="openai_codex",
        is_oauth=True,
        default_api_base="https://chatgpt.com/backend-api",
    ),
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        backend="openai_compat",
        default_api_base="https://api.deepseek.com",
        thinking_style="thinking_type",
        reasoning_model_patterns=("deepseek-v4-pro", "deepseek-reasoner"),
        native_web_search_models=("deepseek-v4-flash", "deepseek-v4-pro"),
    ),
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        env_key="GEMINI_API_KEY",
        display_name="Gemini",
        backend="openai_compat",
        default_api_base="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    # === Local deployment ==================================================
    ProviderSpec(
        name="ollama",
        keywords=("ollama", "nemotron"),
        env_key="OLLAMA_API_KEY",
        display_name="Ollama",
        backend="openai_compat",
        is_local=True,
        detect_by_base_keyword="11434",
        default_api_base="http://localhost:11434/v1",
    ),
    # === Auxiliary ==========================================================
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        env_key="GROQ_API_KEY",
        display_name="Groq",
        backend="openai_compat",
        default_api_base="https://api.groq.com/openai/v1",
    ),
)


NANOBOT_LLM_PROVIDERS: tuple[str, ...] = tuple(spec.name for spec in PROVIDERS)

WireAPI = Literal["auto", "responses", "chat_completions"]
WIRE_API_VALUES: frozenset[str] = frozenset({"auto", "responses", "chat_completions"})

# The protocol a profile's endpoint speaks. This is the user-facing concept;
# ``backend`` (which SDK class talks) and ``wire_api`` (which OpenAI endpoint)
# are derived from it. ``auto`` keeps the historical heuristics: Chat
# Completions everywhere except reasoning models on api.openai.com.
ApiFormat = Literal["auto", "openai_chat", "openai_responses", "anthropic"]
API_FORMAT_VALUES: frozenset[str] = frozenset(
    {"auto", "openai_chat", "openai_responses", "anthropic"}
)
OPENAI_API_FORMATS: tuple[str, ...] = ("auto", "openai_chat", "openai_responses")
_WIRE_API_BY_FORMAT: dict[str, WireAPI] = {
    "openai_responses": "responses",
    "openai_chat": "chat_completions",
}
_FORMAT_BY_WIRE_API: dict[str, ApiFormat] = {
    "responses": "openai_responses",
    "chat_completions": "openai_chat",
}


def find_by_name(name: str | None) -> ProviderSpec | None:
    canonical = canonical_provider_name(name)
    if not canonical:
        return None
    for spec in PROVIDERS:
        if spec.name == canonical:
            return spec
    return None


def normalize_wire_api(value: Any) -> WireAPI:
    """Normalize untrusted catalog values to a supported wire protocol."""
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in WIRE_API_VALUES else "auto"  # type: ignore[return-value]


def wire_api_for_provider(
    value: Any,
    provider: ProviderSpec | str | None,
) -> WireAPI:
    """Return a protocol override only for OpenAI-compatible backends."""
    spec = find_by_name(provider) if isinstance(provider, str) else provider
    if spec is None or not spec.supports_wire_api_selection:
        return "auto"
    return normalize_wire_api(value)


def normalize_api_format(value: Any) -> ApiFormat:
    """Normalize untrusted catalog values to a known API format."""
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in API_FORMAT_VALUES else "auto"  # type: ignore[return-value]


def api_format_for_provider(
    value: Any,
    provider: ProviderSpec | str | None,
) -> ApiFormat:
    """Clamp a requested format to what *provider* can actually speak.

    A vendor with no choice (OAuth, Azure, Anthropic-only) always resolves to
    its own default, so a stray value in a hand-edited file cannot route an
    Anthropic key at an OpenAI SDK.
    """
    spec = find_by_name(provider) if isinstance(provider, str) else provider
    requested = normalize_api_format(value)
    if spec is None:
        return requested
    choices = spec.api_formats
    if not choices:
        return spec.default_api_format  # type: ignore[return-value]
    return requested if requested in choices else spec.default_api_format  # type: ignore[return-value]


def api_format_from_legacy(
    provider: ProviderSpec | str | None,
    wire_api: Any,
) -> ApiFormat:
    """Derive the format a pre-``api_format`` profile has been running with.

    Anthropic-backed bindings (including the legacy ``custom_anthropic`` /
    ``minimax_anthropic`` entries) were always Anthropic Messages; everything
    else expressed its protocol choice through ``wire_api``.
    """
    spec = find_by_name(provider) if isinstance(provider, str) else provider
    if spec is not None and spec.backend == "anthropic":
        return "anthropic"
    return _FORMAT_BY_WIRE_API.get(normalize_wire_api(wire_api), "auto")


def wire_api_from_api_format(api_format: Any) -> WireAPI:
    """The OpenAI endpoint choice an explicit format implies (``auto`` otherwise)."""
    return _WIRE_API_BY_FORMAT.get(normalize_api_format(api_format), "auto")


def effective_backend(spec: ProviderSpec | None, api_format: Any = "auto") -> str:
    """Which provider implementation serves *spec* under *api_format*.

    The only format that changes the backend is Anthropic Messages on an
    OpenAI-compatible vendor; the OpenAI formats differ in ``wire_api``, not
    in backend.
    """
    if spec is None:
        return "openai_compat"
    if api_format_for_provider(api_format, spec) == "anthropic" and spec.backend == "openai_compat":
        return "anthropic"
    return spec.backend


def find_by_model(model: str | None) -> ProviderSpec | None:
    if not model:
        return None
    model_lower = model.lower()
    model_normalized = model_lower.replace("-", "_")
    model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
    normalized_prefix = model_prefix.replace("-", "_")
    standard_specs = [s for s in PROVIDERS if not s.is_gateway and not s.is_local]

    for spec in standard_specs:
        if model_prefix and normalized_prefix == spec.name:
            return spec
    for spec in standard_specs:
        if any(_matches_model_family(family, model_lower) for family in spec.model_id_families):
            return spec
    for spec in standard_specs:
        if any(
            kw in model_lower or kw.replace("-", "_") in model_normalized for kw in spec.keywords
        ):
            return spec
    return None


def _matches_model_family(family: str, model_lower: str) -> bool:
    """Whether *model_lower* is the bare id ``family`` or a variant of it.

    A vendor ships a family under one short id plus siblings distinguished by
    a dash suffix — ``k3`` alongside ``k3-256k``. Enumerating each sibling is
    how #1227 happened: ``k3`` had a rule, ``k3-256k`` shipped later, missed
    it, and got exactly the HTTP 400 the rule exists to prevent. Naming the
    family covers the siblings that do not exist yet, while a short id still
    cannot capture an unrelated one — ``sk3``, ``k30`` and ``k3x`` are all
    different models, and none of them is in this family.
    """
    return model_lower == family or model_lower.startswith(f"{family}-")


def _matching_overrides(spec: ProviderSpec, model_lower: str) -> dict[str, Any]:
    for pattern, overrides in spec.model_overrides:
        # ``^name`` is a bare model-id family; every other pattern is a
        # vendor-family substring.
        matched = (
            _matches_model_family(pattern[1:], model_lower)
            if pattern.startswith("^")
            else pattern in model_lower
        )
        if matched:
            return dict(overrides)
    return {}


def model_overrides_for(model: str | None, spec: ProviderSpec | None) -> dict[str, Any]:
    """Request-parameter overrides *model* needs, whatever route serves it.

    ``model_overrides`` are intrinsic to the model rather than to the route: a
    Kimi model rejects an explicit ``temperature`` whether the caller reached
    it through the ``moonshot`` binding, through an OpenAI-compatible router,
    or through a gateway. Resolving them from the configured binding alone
    loses them for everyone who picked a generic binding — which is the common
    case — so #938 still got HTTP 400 ``invalid temperature: only 1 is allowed
    for this model`` from ``kimi-k3`` under ``binding="openai"``, two months
    after the override itself landed.

    The configured spec is consulted first so an explicit binding always wins.
    When it says nothing about this model, the model's own vendor spec does;
    ``find_by_model`` skips gateway and local entries, so that lookup lands on
    the vendor whose API is the thing actually enforcing the limit.

    A value of ``None`` means "send this parameter as absent", which differs
    from sending a fixed value.
    """
    model_lower = (model or "").strip().lower()
    if not model_lower:
        return {}

    if spec is not None:
        configured = _matching_overrides(spec, model_lower)
        if configured:
            return configured

    vendor = find_by_model(model_lower)
    if vendor is None or vendor is spec:
        return {}
    return _matching_overrides(vendor, model_lower)


def find_gateway(
    provider_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> ProviderSpec | None:
    spec = find_by_name(provider_name)
    if spec and (spec.is_gateway or spec.is_local):
        return spec

    for spec in PROVIDERS:
        if spec.detect_by_key_prefix and api_key and api_key.startswith(spec.detect_by_key_prefix):
            return spec
        if spec.detect_by_base_keyword and api_base and spec.detect_by_base_keyword in api_base:
            return spec
    return None


def strip_provider_prefix(model: str, spec: ProviderSpec | None) -> str:
    """Strip the provider/ prefix from a model name if applicable."""
    if not model or not spec:
        return model
    if spec.strip_model_prefix and "/" in model:
        return model.split("/", 1)[1]
    return model


__all__ = [
    "API_FORMAT_VALUES",
    "ApiFormat",
    "OPENAI_API_FORMATS",
    "ProviderSpec",
    "PROVIDERS",
    "NANOBOT_LLM_PROVIDERS",
    "PROVIDER_ALIASES",
    "WIRE_API_VALUES",
    "WireAPI",
    "api_format_for_provider",
    "api_format_from_legacy",
    "canonical_provider_name",
    "effective_backend",
    "find_by_name",
    "find_by_model",
    "find_gateway",
    "normalize_api_format",
    "normalize_wire_api",
    "strip_provider_prefix",
    "wire_api_for_provider",
    "wire_api_from_api_format",
]

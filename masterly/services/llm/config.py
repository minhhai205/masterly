"""
LLM Configuration
=================

Configuration management for LLM services, resolved from the model catalog of
the signed-in account's group and cached per group.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
import logging
import re
from typing import TYPE_CHECKING, TypedDict

from masterly.services.config import resolve_llm_runtime_config
from masterly.services.keypool import primary_api_key
from masterly.services.provider_registry import (
    api_format_for_provider,
    api_format_from_legacy,
    find_by_name,
    normalize_api_format,
    wire_api_for_provider,
    wire_api_from_api_format,
)

from .exceptions import LLMConfigError

if TYPE_CHECKING:
    from .traffic_control import TrafficController


class LLMConfigUpdate(TypedDict, total=False):
    """Fields allowed when cloning an LLMConfig instance."""

    model: str
    api_key: str | list[str]
    base_url: str | None
    effective_url: str | None
    binding: str
    provider_name: str
    provider_mode: str
    api_version: str | None
    extra_headers: dict[str, str]
    wire_api: str
    api_format: str
    reasoning_effort: str | None
    context_window: int | None
    max_tokens: int
    temperature: float
    max_concurrency: int
    requests_per_minute: int
    traffic_controller: "TrafficController" | None


logger = logging.getLogger(__name__)



@dataclass
class LLMConfig:
    """LLM configuration dataclass."""

    model: str
    api_key: str | list[str]
    base_url: str | None = None
    effective_url: str | None = None
    binding: str = "openai"
    provider_name: str = "routing"
    provider_mode: str = "standard"
    api_version: str | None = None
    extra_headers: dict[str, str] | None = None
    wire_api: str = "auto"
    api_format: str = "auto"
    reasoning_effort: str | None = None
    context_window: int | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    max_concurrency: int = 20
    requests_per_minute: int = 600
    traffic_controller: TrafficController | None = None

    def __post_init__(self) -> None:
        if self.effective_url is None:
            self.effective_url = self.base_url
        spec = find_by_name(self.provider_name) or find_by_name(self.binding)
        # ``api_format`` is the user-facing protocol choice; ``wire_api`` is the
        # OpenAI endpoint it implies. Callers that still speak only ``wire_api``
        # get the format derived from it, so both fields always agree.
        if normalize_api_format(self.api_format) == "auto":
            self.api_format = api_format_from_legacy(spec, self.wire_api)
            self.wire_api = wire_api_for_provider(self.wire_api, spec)
        else:
            self.api_format = api_format_for_provider(self.api_format, spec)
            self.wire_api = wire_api_for_provider(wire_api_from_api_format(self.api_format), spec)

    def model_copy(self, update: LLMConfigUpdate | None = None) -> "LLMConfig":
        """Return a copy of the config with optional updates."""
        return replace(self, **(update or {}))

    def get_api_key(self) -> str:
        """Return the API key string for provider consumers.

        The empty string, not ``None``, because callers here test it for
        truthiness and pass it straight into a provider argument.
        """
        return primary_api_key(self.api_key) or ""


# Resolved config per group ("" outside any group). Each group runs on its own
# catalog, so one cached config for the whole process would hand one group's
# model and key to another.
_LLM_CONFIG_CACHE: dict[str, LLMConfig] = {}
_SCOPED_LLM_CONFIG: ContextVar[LLMConfig | None] = ContextVar(
    "masterly_scoped_llm_config",
    default=None,
)


def set_scoped_llm_config(config: LLMConfig | None) -> Token[LLMConfig | None]:
    """Set the LLM config for the current async context."""
    return _SCOPED_LLM_CONFIG.set(config)


def reset_scoped_llm_config(token: Token[LLMConfig | None]) -> None:
    """Reset a scoped LLM config token returned by ``set_scoped_llm_config``."""
    _SCOPED_LLM_CONFIG.reset(token)


def _get_llm_config_from_resolver() -> LLMConfig:
    """Resolve LLM config from the TutorBot-style runtime adapter."""
    resolved = resolve_llm_runtime_config()
    if not resolved.model:
        raise LLMConfigError(
            "No active LLM model is configured. Please set it in Settings > Catalog."
        )
    if not resolved.effective_url and resolved.provider_mode != "oauth":
        raise LLMConfigError(
            "No effective LLM endpoint resolved. Please configure base_url or provider defaults."
        )
    # api_key may be a list (key pool); only the resolved primary key counts
    # for the placeholder check — set membership on the raw list raises
    # TypeError for unhashable list (PR #962 semantics).
    primary_key = primary_api_key(resolved.api_key)
    is_placeholder_key = primary_key in {None, "", "no-key", "sk-no-key-required"}
    if (
        resolved.provider_name == "openai"
        and resolved.provider_mode == "standard"
        and is_placeholder_key
    ):
        raise LLMConfigError(
            "OpenAI API key is not configured. Set it in Settings > Catalog, "
            "or select a local provider such as Ollama."
        )
    return LLMConfig(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        effective_url=resolved.effective_url,
        binding=resolved.binding,
        provider_name=resolved.provider_name,
        provider_mode=resolved.provider_mode,
        api_version=resolved.api_version,
        extra_headers=resolved.extra_headers,
        wire_api=resolved.wire_api,
        api_format=resolved.api_format,
        reasoning_effort=resolved.reasoning_effort,
        context_window=resolved.context_window,
    )


def get_llm_config() -> LLMConfig:
    """
    Load LLM configuration.

    Returns:
        LLMConfig: Configuration dataclass

    Raises:
        LLMConfigError: If required configuration is missing
    """
    scoped = _SCOPED_LLM_CONFIG.get()
    if scoped is not None:
        return scoped

    key = catalog_group_key()
    cached = _LLM_CONFIG_CACHE.get(key)
    if cached is None:
        cached = _LLM_CONFIG_CACHE[key] = _get_llm_config_from_resolver()
    return cached


async def get_llm_config_async() -> LLMConfig:
    """
    Async wrapper for get_llm_config.

    Useful for consistency in async contexts, though the underlying load is synchronous.

    Returns:
        LLMConfig: Configuration dataclass
    """
    return get_llm_config()


def catalog_group_key() -> str:
    """Which group's catalog the current code resolves against; "" for none."""
    from masterly.multi_user.context import get_current_user

    return get_current_user().group_id or ""


def clear_llm_config_cache(group_key: str | None = None) -> None:
    """Forget the resolved config of one group, or of every group."""
    if group_key is None:
        _LLM_CONFIG_CACHE.clear()
    else:
        _LLM_CONFIG_CACHE.pop(group_key, None)


def reload_config() -> LLMConfig:
    """Reload and return the LLM configuration."""
    clear_llm_config_cache()
    return get_llm_config()


def uses_max_completion_tokens(model: str) -> bool:
    """
    Check if the model uses max_completion_tokens instead of max_tokens.

    Newer OpenAI models (o1, o3, gpt-4o, gpt-5.x, etc.) require max_completion_tokens
    while older models use max_tokens.

    Args:
        model: The model name

    Returns:
        True if the model requires max_completion_tokens, False otherwise
    """
    model_lower = model.lower()

    # Models that require max_completion_tokens:
    # - o1, o3 series (reasoning models)
    # - gpt-4o series
    # - gpt-5.x and later
    patterns = [
        r"^o\d",  # o1, o3, o4-mini, o4, and future o-series models
        r"^gpt-4o",  # gpt-4o models
        r"^gpt-[5-9]",  # gpt-5.x and later
        r"^gpt-\d{2,}",  # gpt-10+ (future proofing)
    ]

    for pattern in patterns:
        if re.match(pattern, model_lower):
            return True

    return False


def get_token_limit_kwargs(model: str, max_tokens: int) -> dict[str, int]:
    """
    Get the appropriate token limit parameter for the model.

    Args:
        model: The model name
        max_tokens: The desired token limit

    Returns:
        Dictionary with either {"max_tokens": value} or {"max_completion_tokens": value}
    """
    if uses_max_completion_tokens(model):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


__all__ = [
    "LLMConfig",
    "get_llm_config",
    "get_llm_config_async",
    "catalog_group_key",
    "clear_llm_config_cache",
    "reload_config",
    "uses_max_completion_tokens",
    "get_token_limit_kwargs",
]

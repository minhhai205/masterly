"""
LLM Client
==========

Unified LLM client for all Masterly services.

Note: This is a legacy interface. Prefer using the factory functions directly:
    from masterly.services.llm import complete, stream
"""

from collections.abc import Awaitable, Callable
import logging
from typing import Any, cast

from .capabilities import supports_vision
from .config import LLMConfig, catalog_group_key, get_llm_config


def build_model_func_for_config(
    config: LLMConfig,
    *,
    allow_multimodal: bool,
) -> Callable[..., object]:
    """Build a model callable owned solely by one resolved configuration."""
    from . import factory

    def _resolve_messages(
        prompt: str,
        system_prompt: str | None,
        history_messages: list[dict[str, object]] | None,
        messages: list[dict[str, object]] | None,
    ) -> list[dict[str, Any]] | None:
        if messages:
            return cast(list[dict[str, Any]], messages)
        if not history_messages:
            return None

        full_messages: list[dict[str, Any]] = []
        if system_prompt and not (history_messages and history_messages[0].get("role") == "system"):
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(cast(list[dict[str, Any]], history_messages))
        if prompt:
            full_messages.append({"role": "user", "content": prompt})
        return full_messages or None

    async def model_func(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, object]] | None = None,
        image_data: str | None = None,
        messages: list[dict[str, object]] | None = None,
        **kwargs: object,
    ) -> str:
        payload_kwargs: dict[str, object] = dict(kwargs)
        for alias in ("history_messages", "messages", "prompt", "system_prompt"):
            payload_kwargs.pop(alias, None)

        default_system_prompt = system_prompt or "You are a helpful assistant."
        resolved_messages = _resolve_messages(
            prompt,
            default_system_prompt,
            history_messages,
            messages,
        )
        if allow_multimodal and image_data is not None:
            payload_kwargs["image_data"] = image_data

        factory_complete = cast(Callable[..., Awaitable[str]], factory.complete_with_config)
        return await factory_complete(
            config=config,
            prompt=prompt,
            system_prompt=default_system_prompt,
            messages=resolved_messages,
            **payload_kwargs,
        )

    return model_func


class LLMClient:
    """
    Unified LLM client for all services.

    Wraps the LLM Factory with a class-based interface.
    Prefer using factory functions (complete, stream) directly for new code.
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        """
        Initialize LLM client.

        Args:
            config: LLM configuration. If None, resolves the current group's.
        """

        self.config = config or get_llm_config()
        self.logger = logging.getLogger(__name__)

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: object,
    ) -> str:
        """
        Call LLM completion via Factory.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            history: Optional conversation history
            **kwargs: Additional arguments passed to the API

        Returns:
            LLM response text
        """
        from . import factory

        factory_complete = cast(Callable[..., Awaitable[str]], factory.complete)
        messages = history or None
        return await factory_complete(
            prompt=prompt,
            system_prompt=system_prompt or "You are a helpful assistant.",
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            api_version=getattr(self.config, "api_version", None),
            binding=getattr(self.config, "binding", "openai"),
            reasoning_effort=getattr(self.config, "reasoning_effort", None),
            extra_headers=getattr(self.config, "extra_headers", None),
            messages=messages,
            **kwargs,
        )

    def complete_sync(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: object,
    ) -> str:
        """
        Synchronous wrapper for complete().

        Use this when you need to call from non-async context.
        """
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop -> safe to run synchronously.
            return asyncio.run(self.complete(prompt, system_prompt, history, **kwargs))

        raise RuntimeError(
            "LLMClient.complete_sync() cannot be called from a running event loop. "
            "Use `await llm.complete(...)` instead."
        )

    def get_model_func(self) -> Callable[..., object]:
        """
        Get an async callable compatible with generic llm_model_func hooks.

        Returns:
            Callable that can be used as llm_model_func
        """
        return build_model_func_for_config(self.config, allow_multimodal=False)

    def get_vision_model_func(self) -> Callable[..., object]:
        """
        Get an async callable compatible with vision_model_func hooks.

        Returns:
            Callable that can be used as vision_model_func
        """
        return build_model_func_for_config(self.config, allow_multimodal=True)

    def supports_multimodal_images(self) -> bool:
        """Return whether the configured LLM can accept image input."""
        return supports_vision(getattr(self.config, "binding", "openai"), self.config.model)


# One client per group ("" outside any group), built from that group's catalog.
_clients: dict[str, LLMClient] = {}


def get_llm_client(config: LLMConfig | None = None) -> LLMClient:
    """
    Get or create the current group's LLM client.

    Args:
        config: Optional configuration. Only used when the client is first built.

    Returns:
        LLMClient instance
    """
    key = catalog_group_key()
    client = _clients.get(key)
    if client is None:
        client = _clients[key] = LLMClient(config)
    return client


def reset_llm_client(group_key: str | None = None) -> None:
    """Forget one group's LLM client, or every group's."""
    if group_key is None:
        _clients.clear()
    else:
        _clients.pop(group_key, None)
    # The services-layer factory owns the actual SDK connection pools. Keep a
    # settings reload authoritative by retiring clients built from the old
    # credentials/base URL as well as this legacy facade.
    from .provider_factory import reset_runtime_provider_pool

    reset_runtime_provider_pool()

"""Embedding adapter implementations and backend registry."""

from .base import (
    BaseEmbeddingAdapter,
    EmbeddingProviderError,
    EmbeddingRequest,
    EmbeddingResponse,
)
from .cohere import CohereEmbeddingAdapter
from .gemini import GeminiEmbeddingAdapter
from .jina import JinaEmbeddingAdapter
from .ollama import OllamaEmbeddingAdapter
from .openai_compatible import OpenAICompatibleEmbeddingAdapter
from .openai_sdk import OpenAISDKEmbeddingAdapter

ADAPTER_BACKENDS: dict[str, type[BaseEmbeddingAdapter]] = {
    "openai_compat": OpenAICompatibleEmbeddingAdapter,
    "openai_sdk": OpenAISDKEmbeddingAdapter,
    "cohere": CohereEmbeddingAdapter,
    "jina": JinaEmbeddingAdapter,
    "ollama": OllamaEmbeddingAdapter,
    "gemini": GeminiEmbeddingAdapter,
}

__all__ = [
    "ADAPTER_BACKENDS",
    "BaseEmbeddingAdapter",
    "EmbeddingProviderError",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "OpenAICompatibleEmbeddingAdapter",
    "OpenAISDKEmbeddingAdapter",
    "GeminiEmbeddingAdapter",
    "JinaEmbeddingAdapter",
    "CohereEmbeddingAdapter",
    "OllamaEmbeddingAdapter",
]

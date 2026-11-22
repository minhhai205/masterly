"""Default settings files written on first start.

``agents.yaml`` owns every LLM budget (temperature, max_tokens). It is written
once with the defaults below and never overwritten, so an administrator's edits
stay. A section missing from an older file falls back to the default here (see
``services.config.loader.get_agent_params``). Each function adds its own section
when it is built.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from masterly.services.path_service import get_path_service

logger = logging.getLogger(__name__)

DEFAULT_AGENTS_SETTINGS: dict[str, Any] = {
    # Settings' "test this model" probe. A reasoning model spends its budget
    # thinking before it answers, so a 1024-token budget returned an empty
    # completion and the probe reported the model broken.
    "diagnostics": {
        "llm_probe": {"temperature": 0.1, "max_tokens": 4096},
    },
}


def _write_yaml_if_missing(file_path: Path, payload: dict[str, Any]) -> None:
    """Write YAML defaults once; never overwrite a file the administrator manages."""
    if file_path.exists():
        return
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
        logger.info("Created default settings: %s", file_path)
    except Exception as exc:
        logger.warning("Failed to create default YAML file %s: %s", file_path, exc)


def ensure_agents_settings() -> None:
    """Create ``agents.yaml`` with the defaults if it does not exist yet."""
    _write_yaml_if_missing(
        get_path_service().get_runtime_config_file("agents"), DEFAULT_AGENTS_SETTINGS
    )

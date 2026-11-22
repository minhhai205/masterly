"""First-run setup: default settings files that other modules read."""

from .init import DEFAULT_AGENTS_SETTINGS, ensure_agents_settings

__all__ = ["DEFAULT_AGENTS_SETTINGS", "ensure_agents_settings"]

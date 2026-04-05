#!/usr/bin/env python3
"""
Configuration loader for Token Tracker.
Supports ~/.config/token-tracker/config.toml with fallback to defaults.
"""

import os
import tomllib
from pathlib import Path
from typing import Any, Optional

# Default configuration values
DEFAULTS = {
    "display": {
        "poll_interval": 10,
        "context_limit": 256000,
        "warn_pct": 60,
        "critical_pct": 85,
        "active_window": 1800,  # seconds — session considered active if modified within this window
        "include_subagents": False,  # whether to include subagent sessions in the list
        "label_style": "path2",  # "basename", "path2", "full", "custom"
        "custom_label_template": "",  # e.g., "{cwd}" or "{basename} - {pct}%"
    },
    "storage": {
        "min_tokens_for_snapshot": 5000,
        "retention_days": 90,
    },
    "graphs": {
        "default_days": 30,
        "enable_notifications": True,
    },
    "ui": {
        "max_session_items": 5,
        "max_files_to_scan": 50,
        "poll_budget_sec": 8,
        "file_op_timeout": 5,
        "tail_read_bytes": 524288,  # 512 * 1024
    },
    "handoff": {
        "handoff_root": "",  # Path to session-handoffs folder (e.g., ~/.claude/session-handoffs)
    },
}

class Config:
    """Loads and provides configuration with fallback to defaults."""

    def __init__(self):
        self._config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load config from file, merging with defaults."""
        config_path = Path.home() / ".config" / "token-tracker" / "config.toml"
        config = DEFAULTS.copy()

        if config_path.exists():
            try:
                with open(config_path, "rb") as f:
                    user_config = tomllib.load(f)
                # Deep merge: user values override defaults per section
                for section, values in user_config.items():
                    if section in config:
                        config[section].update(values)
                    else:
                        config[section] = values
            except Exception as e:
                print(f"[token-tracker] Warning: failed to load config from {config_path}: {e}")

        return config

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a config value by section and key."""
        return self._config.get(section, {}).get(key, default)

    @property
    def POLL_INTERVAL(self) -> int:
        return self.get("display", "poll_interval")

    @property
    def CONTEXT_LIMIT(self) -> int:
        return self.get("display", "context_limit")

    @property
    def WARN_PCT(self) -> int:
        return self.get("display", "warn_pct")

    @property
    def CRITICAL_PCT(self) -> int:
        return self.get("display", "critical_pct")

    @property
    def ACTIVE_WINDOW(self) -> int:
        return self.get("display", "active_window")

    @property
    def INCLUDE_SUBAGENTS(self) -> bool:
        return self.get("display", "include_subagents", False)

    @property
    def MIN_TOKENS_FOR_SNAPSHOT(self) -> int:
        return self.get("storage", "min_tokens_for_snapshot")

    @property
    def RETENTION_DAYS(self) -> int:
        return self.get("storage", "retention_days")

    @property
    def GRAPHS_DEFAULT_DAYS(self) -> int:
        return self.get("graphs", "default_days")

    @property
    def ENABLE_NOTIFICATIONS(self) -> bool:
        return self.get("graphs", "enable_notifications")

    @property
    def MAX_SESSION_ITEMS(self) -> int:
        return self.get("ui", "max_session_items")

    @property
    def MAX_FILES_TO_SCAN(self) -> int:
        return self.get("ui", "max_files_to_scan")

    @property
    def POLL_BUDGET_SEC(self) -> int:
        return self.get("ui", "poll_budget_sec")

    @property
    def FILE_OP_TIMEOUT(self) -> int:
        return self.get("ui", "file_op_timeout")

    @property
    def TAIL_READ_BYTES(self) -> int:
        return self.get("ui", "tail_read_bytes")

    @property
    def LABEL_STYLE(self) -> str:
        return self.get("display", "label_style")

    @property
    def CUSTOM_LABEL_TEMPLATE(self) -> str:
        return self.get("display", "custom_label_template")

    @property
    def HANDOFF_ROOT(self) -> Optional[Path]:
        """Return handoff root path if configured, else None."""
        path_str = self.get("handoff", "handoff_root", "")
        if path_str:
            try:
                return Path(path_str).expanduser()
            except Exception:
                return None
        return None

    @property
    def config_path(self) -> Path:
        """Return the path to the config file."""
        return Path.home() / ".config" / "token-tracker" / "config.toml"

# Global config instance
_config_instance: Config | None = None

def get_config() -> Config:
    """Get the global config instance (singleton)."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance

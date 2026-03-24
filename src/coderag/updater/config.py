"""Update configuration management for CodeRAG."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".coderag"
DEFAULT_CACHE_FILE = DEFAULT_CONFIG_DIR / "update-cache.json"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"


@dataclass
class UpdateConfig:
    """Configuration for the auto-update system."""

    auto_check: bool = True
    auto_install: bool = False
    channel: str = "stable"
    check_interval: int = 3600
    github_repo: str = "dmnkhorvath/coderag-cli"

    @classmethod
    def load(cls, config_path: Path | None = None) -> UpdateConfig:
        """Load config from file, or return defaults."""
        path = config_path or DEFAULT_CONFIG_FILE
        if path.exists():
            try:
                data = json.loads(path.read_text())
                update_data = data.get("update", {})
                return cls(**{k: v for k, v in update_data.items() if k in cls.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self, config_path: Path | None = None) -> None:
        """Save config to file."""
        path = config_path or DEFAULT_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text())
            except json.JSONDecodeError:
                pass
        existing["update"] = {
            "auto_check": self.auto_check,
            "auto_install": self.auto_install,
            "channel": self.channel,
            "check_interval": self.check_interval,
            "github_repo": self.github_repo,
        }
        path.write_text(json.dumps(existing, indent=2))

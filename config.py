"""Configuration settings for Claude Session Orchestrator."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ServerConfig:
    """Server configuration."""
    host: str = "127.0.0.1"
    port: int = 8000


@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str = "sqlite:///orchestrator.db"


@dataclass
class TmuxConfig:
    """Tmux session configuration."""
    session_prefix: str = "claude"
    poll_interval: float = 1.0


@dataclass
class StatusPollingConfig:
    """Status polling configuration."""
    enabled: bool = True
    interval: float = 5.0  # Poll every 5 seconds
    frozen_threshold: float = 300.0  # Warn if busy > 5 minutes


@dataclass
class StatusPatterns:
    """Status detection patterns."""
    idle: list[str] = field(default_factory=lambda: [
        r">\s*$",
        r"claude>\s*$",
    ])
    waiting: list[str] = field(default_factory=lambda: [
        r"\(y/n\)",
        r"Allow\?",
        r"Do you want to",
        r"Proceed\?",
        r"Press Enter",
        r"Continue\?",
    ])


@dataclass
class NotificationsConfig:
    """Desktop notifications configuration."""
    enabled: bool = True


@dataclass
class Config:
    """Main configuration container."""
    server: ServerConfig = field(default_factory=ServerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    tmux: TmuxConfig = field(default_factory=TmuxConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    status_polling: StatusPollingConfig = field(default_factory=StatusPollingConfig)
    editor: str = "vim"
    document_patterns: list[str] = field(default_factory=lambda: [
        "*.md",
        "docs/**/*.md",
        ".claude/**/*.md",
        "plans/**/*.md",
        "specs/**/*.md",
    ])
    status_patterns: StatusPatterns = field(default_factory=StatusPatterns)
    project_root: Path = field(default_factory=lambda: Path.cwd())


def _get_nested(data: dict, *keys: str, default: Any = None) -> Any:
    """Get nested value from dict."""
    for key in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(key, {})
    return data if data != {} else default


def load_config(config_path: Path | str, project_root: Path | str) -> Config:
    """Load configuration from TOML file.

    Args:
        config_path: Path to the TOML configuration file.
        project_root: Absolute path to the project directory.

    Returns:
        Config object with loaded settings.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        tomllib.TOMLDecodeError: If config file is invalid TOML.
    """
    config_path = Path(config_path)
    project_root = Path(project_root)

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    return Config(
        project_root=project_root,
        server=ServerConfig(
            host=_get_nested(data, "server", "host", default="127.0.0.1"),
            port=int(_get_nested(data, "server", "port", default=8000)),
        ),
        database=DatabaseConfig(
            url=_get_nested(data, "database", "url", default="sqlite:///orchestrator.db"),
        ),
        tmux=TmuxConfig(
            session_prefix=_get_nested(data, "tmux", "session_prefix", default="claude"),
            poll_interval=float(_get_nested(data, "tmux", "poll_interval", default=1.0)),
        ),
        notifications=NotificationsConfig(
            enabled=_get_nested(data, "notifications", "enabled", default=True),
        ),
        status_polling=StatusPollingConfig(
            enabled=_get_nested(data, "status_polling", "enabled", default=True),
            interval=float(_get_nested(data, "status_polling", "interval", default=5.0)),
            frozen_threshold=float(_get_nested(data, "status_polling", "frozen_threshold", default=300.0)),
        ),
        editor=_get_nested(data, "editor", "command", default="vim"),
        document_patterns=_get_nested(data, "documents", "patterns", default=[
            "*.md",
            "docs/**/*.md",
            ".claude/**/*.md",
            "plans/**/*.md",
            "specs/**/*.md",
        ]),
        status_patterns=StatusPatterns(
            idle=_get_nested(data, "status", "idle", "patterns", default=[
                r">\s*$",
                r"claude>\s*$",
            ]),
            waiting=_get_nested(data, "status", "waiting", "patterns", default=[
                r"\(y/n\)",
                r"Allow\?",
                r"Do you want to",
                r"Proceed\?",
                r"Press Enter",
                r"Continue\?",
            ]),
        ),
    )


def default_config() -> Config:
    """Create configuration with default values."""
    return Config()


# Global config instance - set by main.py at startup
_config: Config | None = None


def get_config() -> Config:
    """Get the current configuration.

    Returns:
        The current Config instance.

    Raises:
        RuntimeError: If config hasn't been initialized.
    """
    if _config is None:
        raise RuntimeError("Configuration not initialized. Call set_config() first.")
    return _config


def set_config(config: Config) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config


# Legacy exports for backwards compatibility during migration
# These will raise RuntimeError if accessed before config is set
def __getattr__(name: str) -> Any:
    """Provide backwards-compatible access to config values."""
    legacy_map = {
        "PROJECT_ROOT": lambda c: c.project_root,
        "SESSION_PREFIX": lambda c: c.tmux.session_prefix,
        "POLL_INTERVAL": lambda c: c.tmux.poll_interval,
        "DATABASE_URL": lambda c: c.database.url,
        "HOST": lambda c: c.server.host,
        "PORT": lambda c: c.server.port,
        "EDITOR": lambda c: c.editor,
        "DOCUMENT_PATTERNS": lambda c: c.document_patterns,
        "STATUS_PATTERNS": lambda c: {"idle": c.status_patterns.idle, "waiting": c.status_patterns.waiting},
    }

    if name in legacy_map:
        return legacy_map[name](get_config())
    raise AttributeError(f"module 'config' has no attribute {name!r}")

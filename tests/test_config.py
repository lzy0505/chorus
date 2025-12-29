"""Tests for configuration module."""

import re
from pathlib import Path

import pytest

from config import (
    Config,
    ServerConfig,
    DatabaseConfig,
    TmuxConfig,
    StatusPatterns,
    load_config,
    default_config,
    set_config,
    get_config,
)


@pytest.fixture
def reset_config():
    """Reset global config after test."""
    import config
    original = config._config
    yield
    config._config = original


class TestConfigDefaults:
    """Tests for default configuration values."""

    def test_default_config_creation(self):
        """Test default config can be created."""
        cfg = default_config()
        assert isinstance(cfg, Config)

    def test_session_prefix_default(self):
        """Test default session prefix."""
        cfg = default_config()
        assert cfg.tmux.session_prefix == "claude"

    def test_poll_interval_default(self):
        """Test default poll interval."""
        cfg = default_config()
        assert cfg.tmux.poll_interval == 1.0

    def test_host_default(self):
        """Test default host."""
        cfg = default_config()
        assert cfg.server.host == "127.0.0.1"

    def test_port_default(self):
        """Test default port."""
        cfg = default_config()
        assert cfg.server.port == 8000

    def test_editor_default(self):
        """Test default editor."""
        cfg = default_config()
        assert cfg.editor == "vim"


class TestDocumentPatterns:
    """Tests for document discovery patterns."""

    def test_document_patterns_exist(self):
        """Test document patterns are defined."""
        cfg = default_config()
        assert isinstance(cfg.document_patterns, list)
        assert len(cfg.document_patterns) > 0

    def test_markdown_pattern_included(self):
        """Test markdown patterns are included."""
        cfg = default_config()
        assert "*.md" in cfg.document_patterns

    def test_docs_pattern_included(self):
        """Test docs directory pattern is included."""
        cfg = default_config()
        assert "docs/**/*.md" in cfg.document_patterns


class TestStatusPatterns:
    """Tests for status detection patterns."""

    def test_status_patterns_exist(self):
        """Test status patterns are defined."""
        cfg = default_config()
        assert isinstance(cfg.status_patterns, StatusPatterns)
        assert len(cfg.status_patterns.idle) > 0
        assert len(cfg.status_patterns.waiting) > 0

    def test_idle_patterns(self):
        """Test idle patterns are valid regex."""
        cfg = default_config()
        for pattern in cfg.status_patterns.idle:
            # Should compile without error
            re.compile(pattern)

    def test_waiting_patterns(self):
        """Test waiting patterns are valid regex."""
        cfg = default_config()
        for pattern in cfg.status_patterns.waiting:
            # Should compile without error
            re.compile(pattern)

    def test_idle_pattern_matches_prompt(self):
        """Test idle patterns match expected prompts."""
        cfg = default_config()
        test_cases = [
            ">",
            "> ",
            "claude>",
            "claude> ",
        ]

        for text in test_cases:
            matched = any(
                re.search(pattern, text)
                for pattern in cfg.status_patterns.idle
            )
            assert matched, f"Idle pattern should match: {text!r}"

    def test_waiting_pattern_matches_prompts(self):
        """Test waiting patterns match expected prompts."""
        cfg = default_config()
        test_cases = [
            "Allow write? (y/n)",
            "Do you want to proceed?",
            "Allow?",
            "Continue?",
            "Press Enter to confirm",
        ]

        for text in test_cases:
            matched = any(
                re.search(pattern, text)
                for pattern in cfg.status_patterns.waiting
            )
            assert matched, f"Waiting pattern should match: {text!r}"


class TestProjectRoot:
    """Tests for PROJECT_ROOT configuration."""

    def test_project_root_is_path(self):
        """Test project_root is a Path object."""
        cfg = default_config()
        assert isinstance(cfg.project_root, Path)

    def test_project_root_from_load_config(self, tmp_path):
        """Test project_root is set from load_config argument."""
        config_file = tmp_path / "test.toml"
        config_file.write_text("[server]\nport = 8000\n")

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        cfg = load_config(config_file, project_root=project_dir)
        assert cfg.project_root == project_dir


class TestTomlLoading:
    """Tests for TOML configuration loading."""

    def test_load_config_from_file(self, tmp_path):
        """Test loading config from TOML file."""
        config_file = tmp_path / "test.toml"
        config_file.write_text("""
[server]
host = "0.0.0.0"
port = 9000

[database]
url = "sqlite:///test.db"

[tmux]
session_prefix = "test"
poll_interval = 2.0

[editor]
command = "nano"
""")
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        cfg = load_config(config_file, project_root=project_dir)
        assert cfg.server.host == "0.0.0.0"
        assert cfg.server.port == 9000
        assert cfg.database.url == "sqlite:///test.db"
        assert cfg.tmux.session_prefix == "test"
        assert cfg.tmux.poll_interval == 2.0
        assert cfg.editor == "nano"
        assert cfg.project_root == project_dir

    def test_load_config_with_defaults(self, tmp_path):
        """Test loading partial config uses defaults."""
        config_file = tmp_path / "partial.toml"
        config_file.write_text("""
[server]
port = 8080
""")
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        cfg = load_config(config_file, project_root=project_dir)
        assert cfg.server.port == 8080
        assert cfg.server.host == "127.0.0.1"  # default
        assert cfg.tmux.session_prefix == "claude"  # default

    def test_load_config_file_not_found(self, tmp_path):
        """Test loading non-existent config raises error."""
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.toml", project_root=tmp_path)


class TestGlobalConfig:
    """Tests for global config management."""

    def test_get_config_without_set_raises(self, reset_config):
        """Test getting config before setting raises error."""
        import config
        config._config = None
        with pytest.raises(RuntimeError, match="not initialized"):
            get_config()

    def test_set_and_get_config(self, reset_config):
        """Test setting and getting global config."""
        cfg = default_config()
        set_config(cfg)
        assert get_config() is cfg

    def test_legacy_attribute_access(self, reset_config):
        """Test legacy module-level attribute access."""
        import config
        cfg = default_config()
        set_config(cfg)

        assert config.HOST == "127.0.0.1"
        assert config.PORT == 8000
        assert config.SESSION_PREFIX == "claude"
        assert config.POLL_INTERVAL == 1.0
        assert config.EDITOR == "vim"
        assert isinstance(config.DOCUMENT_PATTERNS, list)
        assert isinstance(config.STATUS_PATTERNS, dict)

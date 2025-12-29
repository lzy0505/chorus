"""Tests for configuration module."""

import os
from pathlib import Path


class TestConfigDefaults:
    """Tests for default configuration values."""

    def test_session_prefix_default(self):
        """Test default session prefix."""
        from config import SESSION_PREFIX
        assert SESSION_PREFIX == "claude"

    def test_poll_interval_default(self):
        """Test default poll interval."""
        from config import POLL_INTERVAL
        assert POLL_INTERVAL == 1.0

    def test_host_default(self):
        """Test default host."""
        from config import HOST
        assert HOST == "127.0.0.1"

    def test_port_default(self):
        """Test default port."""
        from config import PORT
        assert PORT == 8000

    def test_editor_default(self):
        """Test default editor."""
        from config import EDITOR
        assert EDITOR == "vim"


class TestDocumentPatterns:
    """Tests for document discovery patterns."""

    def test_document_patterns_exist(self):
        """Test document patterns are defined."""
        from config import DOCUMENT_PATTERNS
        assert isinstance(DOCUMENT_PATTERNS, list)
        assert len(DOCUMENT_PATTERNS) > 0

    def test_markdown_pattern_included(self):
        """Test markdown patterns are included."""
        from config import DOCUMENT_PATTERNS
        assert "*.md" in DOCUMENT_PATTERNS

    def test_docs_pattern_included(self):
        """Test docs directory pattern is included."""
        from config import DOCUMENT_PATTERNS
        assert "docs/**/*.md" in DOCUMENT_PATTERNS


class TestStatusPatterns:
    """Tests for status detection patterns."""

    def test_status_patterns_exist(self):
        """Test status patterns are defined."""
        from config import STATUS_PATTERNS
        assert isinstance(STATUS_PATTERNS, dict)
        assert "idle" in STATUS_PATTERNS
        assert "waiting" in STATUS_PATTERNS

    def test_idle_patterns(self):
        """Test idle patterns are valid regex."""
        import re
        from config import STATUS_PATTERNS

        for pattern in STATUS_PATTERNS["idle"]:
            # Should compile without error
            re.compile(pattern)

    def test_waiting_patterns(self):
        """Test waiting patterns are valid regex."""
        import re
        from config import STATUS_PATTERNS

        for pattern in STATUS_PATTERNS["waiting"]:
            # Should compile without error
            re.compile(pattern)

    def test_idle_pattern_matches_prompt(self):
        """Test idle patterns match expected prompts."""
        import re
        from config import STATUS_PATTERNS

        test_cases = [
            ">",
            "> ",
            "claude>",
            "claude> ",
        ]

        for text in test_cases:
            matched = any(
                re.search(pattern, text)
                for pattern in STATUS_PATTERNS["idle"]
            )
            assert matched, f"Idle pattern should match: {text!r}"

    def test_waiting_pattern_matches_prompts(self):
        """Test waiting patterns match expected prompts."""
        import re
        from config import STATUS_PATTERNS

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
                for pattern in STATUS_PATTERNS["waiting"]
            )
            assert matched, f"Waiting pattern should match: {text!r}"


class TestProjectRoot:
    """Tests for PROJECT_ROOT configuration."""

    def test_project_root_is_path(self):
        """Test PROJECT_ROOT is a Path object."""
        from config import PROJECT_ROOT
        assert isinstance(PROJECT_ROOT, Path)

    def test_project_root_from_env(self, monkeypatch, tmp_path):
        """Test PROJECT_ROOT can be set via environment."""
        monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

        # Need to reimport to get new value
        import importlib
        import config
        importlib.reload(config)

        assert config.PROJECT_ROOT == tmp_path

        # Reset for other tests
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        importlib.reload(config)

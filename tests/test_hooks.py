"""Tests for Claude Code hooks service."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from services.hooks import (
    HookPayload,
    HooksService,
    generate_hooks_config,
    generate_hooks_config_with_handler,
    ensure_hooks_config,
    clear_hooks_config,
    get_chorus_url,
    get_hooks_config_dir,
)


class TestHookPayload:
    """Tests for HookPayload dataclass."""

    def test_from_json(self):
        """Test creating HookPayload from JSON dict."""
        data = {
            "session_id": "abc123",
            "hook_event_name": "Stop",
            "transcript_path": "/path/to/transcript.jsonl",
            "cwd": "/path/to/project",
        }

        payload = HookPayload.from_json(data)

        assert payload.session_id == "abc123"
        assert payload.hook_event_name == "Stop"
        assert payload.transcript_path == "/path/to/transcript.jsonl"
        assert payload.cwd == "/path/to/project"

    def test_from_json_minimal(self):
        """Test creating HookPayload with minimal data."""
        data = {
            "session_id": "xyz789",
            "hook_event_name": "SessionStart",
        }

        payload = HookPayload.from_json(data)

        assert payload.session_id == "xyz789"
        assert payload.hook_event_name == "SessionStart"
        assert payload.transcript_path is None
        assert payload.cwd is None

    def test_from_json_missing_fields(self):
        """Test creating HookPayload with missing required fields."""
        data = {}

        payload = HookPayload.from_json(data)

        assert payload.session_id == ""
        assert payload.hook_event_name == ""

    def test_from_stdin(self):
        """Test parsing HookPayload from stdin JSON text."""
        stdin_text = json.dumps({
            "session_id": "session-123",
            "hook_event_name": "PermissionRequest",
            "cwd": "/home/user/project",
        })

        payload = HookPayload.from_stdin(stdin_text)

        assert payload.session_id == "session-123"
        assert payload.hook_event_name == "PermissionRequest"
        assert payload.cwd == "/home/user/project"

    def test_from_stdin_invalid_json(self):
        """Test parsing invalid JSON raises error."""
        with pytest.raises(json.JSONDecodeError):
            HookPayload.from_stdin("not valid json")


class TestGetChorusUrl:
    """Tests for get_chorus_url function."""

    def test_default_url(self):
        """Test default URL generation."""
        # Uses config set up by conftest.py
        url = get_chorus_url()
        assert url == "http://127.0.0.1:8000"

    def test_custom_host_port(self):
        """Test URL with custom host and port."""
        from config import Config, ServerConfig, set_config, get_config

        # Save original
        original = get_config()

        # Set custom config
        custom = Config(
            server=ServerConfig(host="0.0.0.0", port=9000),
        )
        set_config(custom)

        try:
            url = get_chorus_url()
            assert url == "http://0.0.0.0:9000"
        finally:
            # Restore original
            set_config(original)


class TestGenerateHooksConfig:
    """Tests for generate_hooks_config function."""

    def test_generates_all_hook_types(self):
        """Test that all required hook types are generated."""
        config = generate_hooks_config(task_id=1, chorus_url="http://localhost:8000")

        assert "hooks" in config
        hooks = config["hooks"]

        # All required hook types should be present
        assert "SessionStart" in hooks
        assert "Stop" in hooks
        assert "PermissionRequest" in hooks
        assert "SessionEnd" in hooks
        assert "PostToolUse" in hooks

    def test_hook_structure(self):
        """Test the structure of each hook entry."""
        config = generate_hooks_config(task_id=1, chorus_url="http://localhost:8000")

        # No-matcher events use simple format
        no_matcher_events = ["SessionStart", "Stop", "SessionEnd"]
        # Matcher events use nested format with "hooks" array
        matcher_events = ["PermissionRequest", "PostToolUse"]

        for hook_name, hook_list in config["hooks"].items():
            assert isinstance(hook_list, list)
            assert len(hook_list) == 1

            hook = hook_list[0]
            if hook_name in no_matcher_events:
                # Simple format: {"type": "command", "command": "..."}
                assert hook["type"] == "command"
                assert "command" in hook
            else:
                # Nested format: {"matcher": "*", "hooks": [...]}
                assert "matcher" in hook
                assert "hooks" in hook
                assert hook["hooks"][0]["type"] == "command"
                assert "command" in hook["hooks"][0]

    def test_command_contains_url(self):
        """Test that hook commands contain the Chorus URL."""
        config = generate_hooks_config(task_id=42, chorus_url="http://test:9000")

        no_matcher_events = ["SessionStart", "Stop", "SessionEnd"]

        for hook_name, hook_list in config["hooks"].items():
            hook = hook_list[0]
            if hook_name in no_matcher_events:
                command = hook["command"]
            else:
                command = hook["hooks"][0]["command"]
            assert "http://test:9000" in command

    def test_command_posts_to_correct_endpoint(self):
        """Test that commands POST to the correct API endpoints."""
        config = generate_hooks_config(task_id=1, chorus_url="http://localhost:8000")

        # Each hook should POST to /api/hooks/{event_name_lower}
        session_start_cmd = config["hooks"]["SessionStart"][0]["command"]
        assert "/api/hooks/" in session_start_cmd


class TestGenerateHooksConfigWithHandler:
    """Tests for generate_hooks_config_with_handler function."""

    def test_uses_handler_script(self):
        """Test that handler script path is included in command."""
        config = generate_hooks_config_with_handler(
            task_id=1,
            handler_path="/path/to/handler.py",
            chorus_url="http://localhost:8000",
        )

        no_matcher_events = ["SessionStart", "Stop", "SessionEnd"]

        for hook_name, hook_list in config["hooks"].items():
            hook = hook_list[0]
            if hook_name in no_matcher_events:
                command = hook["command"]
            else:
                command = hook["hooks"][0]["command"]
            assert "/path/to/handler.py" in command

    def test_sets_environment_variables(self):
        """Test that env vars are set in command."""
        config = generate_hooks_config_with_handler(
            handler_path="handler.py",
            chorus_url="http://test:9000",
        )

        command = config["hooks"]["Stop"][0]["command"]
        assert "CHORUS_URL=http://test:9000" in command


class TestGetHooksConfigDir:
    """Tests for get_hooks_config_dir function."""

    def test_returns_correct_path(self):
        """Test that correct shared path is returned."""
        config_dir = get_hooks_config_dir()
        assert config_dir == Path("/tmp/chorus/hooks/.claude")

    def test_always_same_path(self):
        """Test that the same path is always returned."""
        dir1 = get_hooks_config_dir()
        dir2 = get_hooks_config_dir()
        assert dir1 == dir2


class TestEnsureHooksConfig:
    """Tests for ensure_hooks_config function."""

    def test_creates_config_directory(self, tmp_path, monkeypatch):
        """Test that config directory is created."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"
        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        result = ensure_hooks_config()

        assert test_dir.exists()
        assert test_dir.is_dir()
        assert result == test_dir

    def test_creates_settings_file(self, tmp_path, monkeypatch):
        """Test that settings.json is created."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"
        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        ensure_hooks_config()

        settings_path = test_dir / "settings.json"
        assert settings_path.exists()

    def test_settings_contains_hooks(self, tmp_path, monkeypatch):
        """Test that settings file contains hooks config."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"
        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        ensure_hooks_config(chorus_url="http://localhost:8000")

        settings_path = test_dir / "settings.json"
        settings = json.loads(settings_path.read_text())

        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]

    def test_returns_config_dir(self, tmp_path, monkeypatch):
        """Test that function returns path to config directory."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"
        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        result = ensure_hooks_config()

        assert result == test_dir

    def test_idempotent_does_not_overwrite(self, tmp_path, monkeypatch):
        """Test that ensure is idempotent and doesn't overwrite existing config."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"
        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        # First call creates the config
        ensure_hooks_config(chorus_url="http://first:8000")

        settings_path = test_dir / "settings.json"
        original_content = settings_path.read_text()

        # Second call should not overwrite
        ensure_hooks_config(chorus_url="http://second:9000")

        # Content should be unchanged
        assert settings_path.read_text() == original_content
        assert "http://first:8000" in settings_path.read_text()


class TestClearHooksConfig:
    """Tests for clear_hooks_config function."""

    def test_removes_config_directory(self, tmp_path, monkeypatch):
        """Test that config directory is removed."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"
        test_dir.mkdir(parents=True)
        (test_dir / "settings.json").write_text('{"hooks": {}}')

        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        clear_hooks_config()

        assert not test_dir.exists()

    def test_handles_missing_directory(self, tmp_path, monkeypatch):
        """Test handling when config directory doesn't exist."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"

        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        # Should not raise
        clear_hooks_config()

    def test_removes_entire_tree(self, tmp_path, monkeypatch):
        """Test that entire config tree is removed."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"
        test_dir.mkdir(parents=True)
        (test_dir / "settings.json").write_text('{"hooks": {}}')
        (test_dir / "other_file.json").write_text('{}')

        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        clear_hooks_config()

        assert not test_dir.exists()


class TestHooksService:
    """Tests for HooksService class."""

    def test_init_default(self):
        """Test initialization with defaults."""
        service = HooksService()
        assert service.chorus_url is None

    def test_init_custom_chorus_url(self):
        """Test initialization with custom Chorus URL."""
        service = HooksService(chorus_url="http://custom:9000")
        assert service.chorus_url == "http://custom:9000"

    def test_ensure_hooks(self, tmp_path, monkeypatch):
        """Test ensuring hooks configuration exists."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"
        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        service = HooksService(chorus_url="http://localhost:8000")
        result = service.ensure_hooks()

        assert result == test_dir
        assert test_dir.exists()

        settings_path = test_dir / "settings.json"
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings

    def test_ensure_hooks_idempotent(self, tmp_path, monkeypatch):
        """Test that ensure_hooks is idempotent."""
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"
        monkeypatch.setattr(
            "services.hooks.get_hooks_config_dir",
            lambda: test_dir
        )

        service = HooksService(chorus_url="http://localhost:8000")

        # Call multiple times
        result1 = service.ensure_hooks()
        result2 = service.ensure_hooks()

        assert result1 == result2
        assert test_dir.exists()

    def test_get_config_dir(self):
        """Test getting config directory path."""
        service = HooksService()
        config_dir = service.get_config_dir()
        assert config_dir == Path("/tmp/chorus/hooks/.claude")

    def test_get_hooks_config(self):
        """Test getting hooks configuration."""
        service = HooksService(chorus_url="http://localhost:8000")

        config = service.get_hooks_config()

        assert "hooks" in config
        assert "SessionStart" in config["hooks"]
        assert "Stop" in config["hooks"]

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
    write_hooks_config,
    clear_hooks_config,
    get_chorus_url,
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
            task_id=42,
            handler_path="handler.py",
            chorus_url="http://test:9000",
        )

        command = config["hooks"]["Stop"][0]["command"]
        assert "CHORUS_URL=http://test:9000" in command
        assert "CHORUS_TASK_ID=42" in command


class TestWriteHooksConfig:
    """Tests for write_hooks_config function."""

    def test_creates_claude_directory(self, tmp_path):
        """Test that .claude directory is created if missing."""
        assert not (tmp_path / ".claude").exists()

        write_hooks_config(tmp_path, task_id=1)

        assert (tmp_path / ".claude").exists()
        assert (tmp_path / ".claude").is_dir()

    def test_creates_settings_file(self, tmp_path):
        """Test that settings.json is created."""
        write_hooks_config(tmp_path, task_id=1)

        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()

    def test_settings_contains_hooks(self, tmp_path):
        """Test that settings file contains hooks config."""
        write_hooks_config(tmp_path, task_id=1, chorus_url="http://localhost:8000")

        settings_path = tmp_path / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())

        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]

    def test_preserves_existing_settings(self, tmp_path):
        """Test that existing settings are preserved."""
        # Create existing settings
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "model": "claude-3-opus",
            "temperature": 0.7,
        }))

        write_hooks_config(tmp_path, task_id=1)

        settings = json.loads(settings_path.read_text())
        assert settings["model"] == "claude-3-opus"
        assert settings["temperature"] == 0.7
        assert "hooks" in settings

    def test_overwrites_existing_hooks(self, tmp_path):
        """Test that existing hooks are overwritten."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {"OldHook": [{"type": "command", "command": "old"}]},
        }))

        write_hooks_config(tmp_path, task_id=1, chorus_url="http://localhost:8000")

        settings = json.loads(settings_path.read_text())
        assert "OldHook" not in settings["hooks"]
        assert "SessionStart" in settings["hooks"]

    def test_returns_settings_path(self, tmp_path):
        """Test that function returns path to settings file."""
        result = write_hooks_config(tmp_path, task_id=1)

        assert result == tmp_path / ".claude" / "settings.json"

    def test_handles_invalid_existing_json(self, tmp_path):
        """Test handling of invalid JSON in existing settings."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text("not valid json {")

        # Should not raise, should overwrite
        write_hooks_config(tmp_path, task_id=1)

        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings


class TestClearHooksConfig:
    """Tests for clear_hooks_config function."""

    def test_removes_hooks_section(self, tmp_path):
        """Test that hooks section is removed."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {"Stop": []},
            "model": "claude-3",
        }))

        clear_hooks_config(tmp_path)

        settings = json.loads(settings_path.read_text())
        assert "hooks" not in settings
        assert settings["model"] == "claude-3"

    def test_preserves_other_settings(self, tmp_path):
        """Test that other settings are preserved."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {"Stop": []},
            "model": "claude-3",
            "temperature": 0.5,
        }))

        clear_hooks_config(tmp_path)

        settings = json.loads(settings_path.read_text())
        assert settings["model"] == "claude-3"
        assert settings["temperature"] == 0.5

    def test_handles_missing_file(self, tmp_path):
        """Test handling when settings file doesn't exist."""
        # Should not raise
        clear_hooks_config(tmp_path)

    def test_handles_missing_hooks_section(self, tmp_path):
        """Test handling when hooks section doesn't exist."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({"model": "claude-3"}))

        # Should not raise
        clear_hooks_config(tmp_path)

        settings = json.loads(settings_path.read_text())
        assert settings["model"] == "claude-3"

    def test_handles_invalid_json(self, tmp_path):
        """Test handling of invalid JSON."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text("invalid json")

        # Should not raise
        clear_hooks_config(tmp_path)


class TestHooksService:
    """Tests for HooksService class."""

    def test_init_default_project_root(self):
        """Test initialization with default project root."""
        from config import get_config

        service = HooksService()
        # Should use project_root from the test config
        assert service.project_root == get_config().project_root

    def test_init_custom_project_root(self):
        """Test initialization with custom project root."""
        custom_path = Path("/custom/project")
        service = HooksService(project_root=custom_path)
        assert service.project_root == custom_path

    def test_init_custom_chorus_url(self):
        """Test initialization with custom Chorus URL."""
        service = HooksService(chorus_url="http://custom:9000")
        assert service.chorus_url == "http://custom:9000"

    def test_setup_hooks(self, tmp_path):
        """Test setting up hooks for a task."""
        service = HooksService(
            project_root=tmp_path,
            chorus_url="http://localhost:8000",
        )

        result = service.setup_hooks(task_id=42)

        assert result == tmp_path / ".claude" / "settings.json"
        assert result.exists()

        settings = json.loads(result.read_text())
        assert "hooks" in settings

    def test_teardown_hooks(self, tmp_path):
        """Test removing hooks configuration."""
        service = HooksService(project_root=tmp_path)

        # First set up hooks
        service.setup_hooks(task_id=1)

        # Verify hooks exist
        settings_path = tmp_path / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings

        # Teardown
        service.teardown_hooks()

        # Verify hooks removed
        settings = json.loads(settings_path.read_text())
        assert "hooks" not in settings

    def test_get_hooks_config(self, tmp_path):
        """Test getting hooks configuration."""
        service = HooksService(
            project_root=tmp_path,
            chorus_url="http://localhost:8000",
        )

        config = service.get_hooks_config(task_id=1)

        assert "hooks" in config
        assert "SessionStart" in config["hooks"]
        assert "Stop" in config["hooks"]

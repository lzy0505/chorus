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
    get_global_config_dir,
    get_global_config_path,
    deep_merge_hooks,
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
        config = generate_hooks_config(chorus_url="http://localhost:8000")

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
        config = generate_hooks_config(chorus_url="http://localhost:8000")

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
        config = generate_hooks_config(chorus_url="http://test:9000")

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
        config = generate_hooks_config(chorus_url="http://localhost:8000")

        # Each hook should POST to /api/hooks/{event_name_lower}
        session_start_cmd = config["hooks"]["SessionStart"][0]["command"]
        assert "/api/hooks/" in session_start_cmd


class TestGenerateHooksConfigWithHandler:
    """Tests for generate_hooks_config_with_handler function."""

    def test_uses_handler_script(self):
        """Test that handler script path is included in command."""
        config = generate_hooks_config_with_handler(
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


class TestGlobalConfigPaths:
    """Tests for global config path functions."""

    def test_get_global_config_dir(self):
        """Test that global config dir points to ~/.claude/."""
        config_dir = get_global_config_dir()
        assert config_dir == Path.home() / ".claude"

    def test_get_global_config_path(self):
        """Test that global config path points to ~/.claude/settings.json."""
        config_path = get_global_config_path()
        assert config_path == Path.home() / ".claude" / "settings.json"

    def test_get_global_credentials_path(self):
        """Test that global credentials path points to ~/.claude.json."""
        from services.hooks import get_global_credentials_path
        creds_path = get_global_credentials_path()
        assert creds_path == Path.home() / ".claude.json"


class TestDeepMergeHooks:
    """Tests for deep_merge_hooks function."""

    def test_merge_empty_base(self):
        """Test merging with empty base config."""
        base = {}
        overlay = {"hooks": {"SessionStart": [{"type": "command", "command": "test"}]}}

        result = deep_merge_hooks(base, overlay)

        assert result == overlay

    def test_merge_empty_overlay(self):
        """Test merging with empty overlay config."""
        base = {"foo": "bar", "hooks": {"Custom": [{"type": "command"}]}}
        overlay = {}

        result = deep_merge_hooks(base, overlay)

        assert result == base

    def test_merge_hooks_appends(self):
        """Test that hooks from overlay are appended to base hooks."""
        base = {
            "hooks": {
                "SessionStart": [{"type": "command", "command": "existing"}]
            }
        }
        overlay = {
            "hooks": {
                "SessionStart": [{"type": "command", "command": "new"}]
            }
        }

        result = deep_merge_hooks(base, overlay)

        # Both hooks should be present
        assert len(result["hooks"]["SessionStart"]) == 2
        assert result["hooks"]["SessionStart"][0]["command"] == "existing"
        assert result["hooks"]["SessionStart"][1]["command"] == "new"

    def test_merge_adds_new_events(self):
        """Test that new hook events are added."""
        base = {
            "hooks": {
                "SessionStart": [{"type": "command", "command": "existing"}]
            }
        }
        overlay = {
            "hooks": {
                "Stop": [{"type": "command", "command": "new"}]
            }
        }

        result = deep_merge_hooks(base, overlay)

        assert "SessionStart" in result["hooks"]
        assert "Stop" in result["hooks"]

    def test_merge_preserves_non_hooks_settings(self):
        """Test that non-hooks settings are preserved."""
        base = {
            "permissions": {"allow": ["Read", "Edit"]},
            "model": "claude-sonnet",
            "hooks": {}
        }
        overlay = {
            "hooks": {"SessionStart": [{"type": "command"}]}
        }

        result = deep_merge_hooks(base, overlay)

        assert result["permissions"] == {"allow": ["Read", "Edit"]}
        assert result["model"] == "claude-sonnet"

    def test_merge_nested_dicts(self):
        """Test that nested dicts are recursively merged."""
        base = {"nested": {"a": 1, "b": 2}}
        overlay = {"nested": {"c": 3}}

        result = deep_merge_hooks(base, overlay)

        assert result["nested"] == {"a": 1, "b": 2, "c": 3}


class TestEnsureHooksConfigWithGlobalConfig:
    """Tests for ensure_hooks_config with global config merging."""

    def test_copies_global_config_files(self, tmp_path, monkeypatch):
        """Test that all files from global config are copied."""
        global_dir = tmp_path / "global_claude"
        global_dir.mkdir()
        (global_dir / "settings.json").write_text('{"model": "opus"}')
        (global_dir / "credentials.json").write_text('{"token": "secret"}')
        (global_dir / "projects.json").write_text('{}')

        test_dir = tmp_path / "chorus" / "hooks" / ".claude"

        monkeypatch.setattr("services.hooks.get_hooks_config_dir", lambda: test_dir)
        monkeypatch.setattr("services.hooks.get_global_config_dir", lambda: global_dir)

        ensure_hooks_config(chorus_url="http://localhost:8000")

        # All files should be copied
        assert (test_dir / "credentials.json").exists()
        assert (test_dir / "projects.json").exists()
        assert json.loads((test_dir / "credentials.json").read_text()) == {"token": "secret"}

    def test_merges_hooks_into_global_settings(self, tmp_path, monkeypatch):
        """Test that Chorus hooks are merged into global settings."""
        global_dir = tmp_path / "global_claude"
        global_dir.mkdir()
        (global_dir / "settings.json").write_text(json.dumps({
            "model": "opus",
            "permissions": {"allow": ["Read"]},
            "hooks": {
                "UserHook": [{"type": "command", "command": "user_cmd"}]
            }
        }))

        test_dir = tmp_path / "chorus" / "hooks" / ".claude"

        monkeypatch.setattr("services.hooks.get_hooks_config_dir", lambda: test_dir)
        monkeypatch.setattr("services.hooks.get_global_config_dir", lambda: global_dir)

        ensure_hooks_config(chorus_url="http://localhost:8000")

        settings = json.loads((test_dir / "settings.json").read_text())

        # Global settings preserved
        assert settings["model"] == "opus"
        assert settings["permissions"] == {"allow": ["Read"]}

        # User hook preserved
        assert "UserHook" in settings["hooks"]

        # Chorus hooks added
        assert "SessionStart" in settings["hooks"]
        assert "Stop" in settings["hooks"]

    def test_force_regeneration(self, tmp_path, monkeypatch):
        """Test that force=True regenerates the config."""
        global_dir = tmp_path / "global_claude"
        global_dir.mkdir()
        (global_dir / "settings.json").write_text('{"model": "opus"}')

        test_dir = tmp_path / "chorus" / "hooks" / ".claude"

        monkeypatch.setattr("services.hooks.get_hooks_config_dir", lambda: test_dir)
        monkeypatch.setattr("services.hooks.get_global_config_dir", lambda: global_dir)

        # First call
        ensure_hooks_config(chorus_url="http://first:8000")
        first_content = (test_dir / "settings.json").read_text()
        assert "http://first:8000" in first_content

        # Update global config
        (global_dir / "settings.json").write_text('{"model": "sonnet"}')

        # Second call without force - should not change
        ensure_hooks_config(chorus_url="http://second:9000")
        assert (test_dir / "settings.json").read_text() == first_content

        # Third call with force - should regenerate
        ensure_hooks_config(chorus_url="http://third:7000", force=True)
        new_content = (test_dir / "settings.json").read_text()
        assert "http://third:7000" in new_content
        assert "sonnet" in new_content

    def test_works_without_global_config(self, tmp_path, monkeypatch):
        """Test that config is created even without global config."""
        global_dir = tmp_path / "nonexistent_claude"  # Doesn't exist
        test_dir = tmp_path / "chorus" / "hooks" / ".claude"

        monkeypatch.setattr("services.hooks.get_hooks_config_dir", lambda: test_dir)
        monkeypatch.setattr("services.hooks.get_global_config_dir", lambda: global_dir)

        ensure_hooks_config(chorus_url="http://localhost:8000")

        # Should still create valid config
        assert test_dir.exists()
        settings = json.loads((test_dir / "settings.json").read_text())
        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]

    def test_copies_credentials_file(self, tmp_path, monkeypatch):
        """Test that ~/.claude.json credentials file is copied to config dir."""
        global_dir = tmp_path / "global_claude"
        global_dir.mkdir()
        (global_dir / "settings.json").write_text('{}')

        # Create credentials file at home root level (like ~/.claude.json)
        global_creds = tmp_path / ".claude.json"
        global_creds.write_text(json.dumps({
            "oauthAccount": {"accessToken": "secret123"},
            "userID": "user-abc",
            "theme": "dark"
        }))

        test_dir = tmp_path / "chorus" / "hooks" / ".claude"

        monkeypatch.setattr("services.hooks.get_hooks_config_dir", lambda: test_dir)
        monkeypatch.setattr("services.hooks.get_global_config_dir", lambda: global_dir)
        monkeypatch.setattr("services.hooks.get_global_credentials_path", lambda: global_creds)

        ensure_hooks_config(chorus_url="http://localhost:8000")

        # Credentials should be copied into config dir
        copied_creds = test_dir / ".claude.json"
        assert copied_creds.exists()
        creds_data = json.loads(copied_creds.read_text())
        assert "oauthAccount" in creds_data
        assert creds_data["userID"] == "user-abc"

    def test_works_without_credentials_file(self, tmp_path, monkeypatch):
        """Test that config works even if ~/.claude.json doesn't exist."""
        global_dir = tmp_path / "global_claude"
        global_dir.mkdir()
        (global_dir / "settings.json").write_text('{"model": "opus"}')

        # No credentials file
        global_creds = tmp_path / "nonexistent.json"

        test_dir = tmp_path / "chorus" / "hooks" / ".claude"

        monkeypatch.setattr("services.hooks.get_hooks_config_dir", lambda: test_dir)
        monkeypatch.setattr("services.hooks.get_global_config_dir", lambda: global_dir)
        monkeypatch.setattr("services.hooks.get_global_credentials_path", lambda: global_creds)

        ensure_hooks_config(chorus_url="http://localhost:8000")

        # Should still create config, just without credentials
        assert test_dir.exists()
        settings = json.loads((test_dir / "settings.json").read_text())
        assert "hooks" in settings


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

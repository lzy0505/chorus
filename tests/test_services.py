"""Tests for service modules."""

import re

import pytest

from config import default_config, set_config


@pytest.fixture(autouse=True)
def setup_config():
    """Set up default config for all tests in this module."""
    set_config(default_config())


class TestStatusDetection:
    """Tests for status detection patterns."""

    def test_idle_pattern_detection(self):
        """Test detecting idle status from output."""
        from config import get_config
        config = get_config()
        status_patterns = {
            "idle": config.status_patterns.idle,
            "waiting": config.status_patterns.waiting,
        }

        idle_outputs = [
            "some output\n>",
            "done processing\n> ",
            "finished\nclaude> ",
        ]

        for output in idle_outputs:
            last_lines = output.split("\n")[-5:]
            is_idle = any(
                re.search(pattern, "\n".join(last_lines))
                for pattern in status_patterns["idle"]
            )
            assert is_idle, f"Should detect idle in: {output!r}"

    def test_waiting_pattern_detection(self):
        """Test detecting waiting status from output."""
        from config import get_config
        config = get_config()
        status_patterns = {
            "idle": config.status_patterns.idle,
            "waiting": config.status_patterns.waiting,
        }

        waiting_outputs = [
            "Allow write to file? (y/n)",
            "Do you want to proceed?",
            "Allow?",
            "Continue?",
        ]

        for output in waiting_outputs:
            is_waiting = any(
                re.search(pattern, output)
                for pattern in status_patterns["waiting"]
            )
            assert is_waiting, f"Should detect waiting in: {output!r}"

    def test_busy_is_default(self):
        """Test that busy is the default status."""
        from config import get_config
        config = get_config()
        status_patterns = {
            "idle": config.status_patterns.idle,
            "waiting": config.status_patterns.waiting,
        }

        busy_output = "Processing request...\nWorking on task..."

        is_idle = any(
            re.search(pattern, busy_output)
            for pattern in status_patterns["idle"]
        )
        is_waiting = any(
            re.search(pattern, busy_output)
            for pattern in status_patterns["waiting"]
        )

        assert not is_idle
        assert not is_waiting

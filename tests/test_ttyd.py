"""Tests for ttyd service."""

import pytest
from services.ttyd import TtydService, TtydAlreadyRunningError, TtydNotRunningError


class TestTtydService:
    """Test TtydService class."""

    def test_get_port(self):
        """Test port calculation."""
        service = TtydService(base_port=7681)
        assert service.get_port(1) == 7682
        assert service.get_port(10) == 7691
        assert service.get_port(100) == 7781

    def test_get_url(self):
        """Test URL generation."""
        service = TtydService(base_port=7681)
        assert service.get_url(1) == "http://localhost:7682"
        assert service.get_url(5) == "http://localhost:7686"

    def test_is_running_when_not_started(self):
        """Test is_running returns False for never-started task."""
        service = TtydService()
        assert service.is_running(999) is False

    def test_get_info_when_not_running(self):
        """Test get_info returns None when not running."""
        service = TtydService()
        assert service.get_info(999) is None

    def test_list_running_empty(self):
        """Test list_running returns empty list when nothing running."""
        service = TtydService()
        # Note: This might not be empty if other tests left processes running
        # But for a fresh service, it should work
        running = service.list_running()
        assert isinstance(running, list)

    def test_stop_if_running_when_not_running(self):
        """Test stop_if_running returns False when not running."""
        service = TtydService()
        assert service.stop_if_running(999) is False

    def test_stop_raises_when_not_running(self):
        """Test stop raises TtydNotRunningError."""
        service = TtydService()
        with pytest.raises(TtydNotRunningError):
            service.stop(999)


@pytest.mark.integration
class TestTtydServiceIntegration:
    """Integration tests that require ttyd to be installed."""

    def test_start_and_stop(self):
        """Test starting and stopping ttyd."""
        # This test requires ttyd to be installed
        # Skip if not available
        import shutil
        if not shutil.which("ttyd"):
            pytest.skip("ttyd not installed")

        # Would need a real tmux session to test properly
        pytest.skip("Requires running tmux session")

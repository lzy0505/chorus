"""Desktop notification service for Chorus.

Sends desktop notifications for important task events like:
- Task started
- Task completed
- Task failed
- Claude is idle (waiting for input)
- Permission requests
"""

import logging
import subprocess
import platform
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class NotificationLevel(str, Enum):
    """Notification urgency levels."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class NotifierService:
    """Cross-platform desktop notification service."""

    def __init__(self, enabled: bool = True):
        """Initialize the notifier.

        Args:
            enabled: Whether notifications are enabled
        """
        self.enabled = enabled
        self.platform = platform.system()

    def send(
        self,
        title: str,
        message: str,
        level: NotificationLevel = NotificationLevel.INFO,
        sound: bool = False,
    ) -> bool:
        """Send a desktop notification.

        Args:
            title: Notification title
            message: Notification body
            level: Urgency level (info, success, warning, error)
            sound: Whether to play a sound

        Returns:
            True if notification was sent successfully, False otherwise
        """
        if not self.enabled:
            logger.debug(f"Notifications disabled, skipping: {title}")
            return False

        try:
            if self.platform == "Darwin":  # macOS
                return self._send_macos(title, message, sound)
            elif self.platform == "Linux":
                return self._send_linux(title, message, level)
            elif self.platform == "Windows":
                return self._send_windows(title, message)
            else:
                logger.warning(f"Unsupported platform for notifications: {self.platform}")
                return False
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    def _send_macos(self, title: str, message: str, sound: bool) -> bool:
        """Send notification on macOS using osascript."""
        # Use AppleScript to show notification
        script = f'display notification "{message}" with title "{title}"'
        if sound:
            script += ' sound name "default"'

        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            logger.debug(f"Sent macOS notification: {title}")
            return True
        else:
            logger.error(f"Failed to send macOS notification: {result.stderr}")
            return False

    def _send_linux(self, title: str, message: str, level: NotificationLevel) -> bool:
        """Send notification on Linux using notify-send."""
        # Map level to urgency
        urgency_map = {
            NotificationLevel.INFO: "normal",
            NotificationLevel.SUCCESS: "normal",
            NotificationLevel.WARNING: "normal",
            NotificationLevel.ERROR: "critical",
        }
        urgency = urgency_map.get(level, "normal")

        result = subprocess.run(
            ["notify-send", "-u", urgency, title, message],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            logger.debug(f"Sent Linux notification: {title}")
            return True
        else:
            logger.error(f"Failed to send Linux notification: {result.stderr}")
            return False

    def _send_windows(self, title: str, message: str) -> bool:
        """Send notification on Windows using PowerShell."""
        # Use PowerShell to show toast notification
        script = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
        [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null

        $template = @"
        <toast>
            <visual>
                <binding template="ToastText02">
                    <text id="1">{title}</text>
                    <text id="2">{message}</text>
                </binding>
            </visual>
        </toast>
        "@

        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($template)
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Chorus").Show($toast)
        """

        result = subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            logger.debug(f"Sent Windows notification: {title}")
            return True
        else:
            logger.error(f"Failed to send Windows notification: {result.stderr}")
            return False

    # Convenience methods for common notifications

    def task_started(self, task_id: int, title: str) -> bool:
        """Notify that a task has started."""
        return self.send(
            title="Task Started",
            message=f"Task #{task_id}: {title}",
            level=NotificationLevel.INFO,
        )

    def task_completed(self, task_id: int, title: str) -> bool:
        """Notify that a task has completed."""
        return self.send(
            title="Task Completed",
            message=f"Task #{task_id}: {title}",
            level=NotificationLevel.SUCCESS,
            sound=True,
        )

    def task_failed(self, task_id: int, title: str, reason: Optional[str] = None) -> bool:
        """Notify that a task has failed."""
        message = f"Task #{task_id}: {title}"
        if reason:
            message += f"\nReason: {reason}"

        return self.send(
            title="Task Failed",
            message=message,
            level=NotificationLevel.ERROR,
            sound=True,
        )

    def claude_idle(self, task_id: int, title: str) -> bool:
        """Notify that Claude is idle and waiting for input."""
        return self.send(
            title="Claude is Idle",
            message=f"Task #{task_id}: {title} is ready for input",
            level=NotificationLevel.INFO,
        )

    def permission_requested(self, task_id: int, title: str) -> bool:
        """Notify that Claude is requesting permission."""
        return self.send(
            title="Permission Required",
            message=f"Task #{task_id}: {title} needs approval",
            level=NotificationLevel.WARNING,
            sound=True,
        )

    def claude_crashed(self, task_id: int, title: str) -> bool:
        """Notify that Claude has crashed or stopped unexpectedly."""
        return self.send(
            title="Claude Stopped",
            message=f"Task #{task_id}: {title} - Claude has stopped",
            level=NotificationLevel.ERROR,
            sound=True,
        )

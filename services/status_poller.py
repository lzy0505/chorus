"""Background status polling service.

Periodically checks Claude's actual status by analyzing terminal output,
updating the database when status changes are detected.

This service works in hybrid mode with hooks:
- Hooks provide fast, event-driven updates (SessionStart, Stop, PermissionRequest)
- Polling provides a safety net, catching missed hooks or drift (every 5-10s)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from database import get_engine
from models import Task, TaskStatus, ClaudeStatus
from services.status_detector import StatusDetector

logger = logging.getLogger(__name__)


class StatusPoller:
    """Background service that polls Claude status for running tasks.

    This service runs in the background and periodically checks the actual
    status of Claude by analyzing terminal output. It updates the database
    when status changes are detected.

    This provides a safety net for hook-based status updates, catching cases
    where hooks might be missed or delayed.
    """

    def __init__(self, interval: float = 5.0, engine=None):
        """Initialize the status poller.

        Args:
            interval: Polling interval in seconds (default: 5.0)
                     Longer intervals are appropriate for hybrid mode where
                     hooks provide fast updates and polling is a safety net.
            engine: Optional database engine (for testing)
        """
        self.interval = interval
        self.detector = StatusDetector()
        self.engine = engine  # If None, will use get_engine()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._correction_count = 0  # Track how often poller corrects hook status

    async def _poll_once(self) -> None:
        """Poll status for all running tasks once."""
        try:
            engine = self.engine if self.engine is not None else get_engine()
            with Session(engine) as db:
                # Get all tasks that might need status updates
                statement = select(Task).where(
                    Task.status.in_([TaskStatus.running, TaskStatus.waiting])
                )
                tasks = db.exec(statement).all()

                for task in tasks:
                    # Skip if no tmux session
                    if not task.tmux_session:
                        continue

                    # Detect actual status from terminal
                    detected_status = self.detector.detect_status(task.id)

                    # Skip if couldn't detect (session might be gone)
                    if detected_status is None:
                        continue

                    # Update if status changed (poller correcting hook-based status)
                    if detected_status != task.claude_status:
                        self._correction_count += 1
                        logger.warning(
                            f"Task {task.id}: Status correction by poller - "
                            f"{task.claude_status} → {detected_status} "
                            f"(correction #{self._correction_count})"
                        )
                        task.claude_status = detected_status

                        # Also update task status if needed
                        if detected_status == ClaudeStatus.waiting:
                            task.status = TaskStatus.waiting
                        elif task.status == TaskStatus.waiting and detected_status == ClaudeStatus.idle:
                            # Claude finished responding to permission
                            task.status = TaskStatus.running
                        elif detected_status == ClaudeStatus.busy and task.status == TaskStatus.running:
                            # Ensure task status matches busy state
                            pass  # Already running, no change needed

                        db.add(task)

                db.commit()

        except Exception as e:
            logger.error(f"Error during status polling: {e}", exc_info=True)

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        logger.info(f"Status poller started (interval: {self.interval}s)")

        while self._running:
            await self._poll_once()
            await asyncio.sleep(self.interval)

        logger.info("Status poller stopped")

    def start(self) -> None:
        """Start the polling loop.

        This should be called when the server starts.
        """
        if self._running:
            logger.warning("Status poller already running")
            return

        self._running = True
        # Create the background task (non-blocking)
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Status poller starting...")

    async def stop(self) -> None:
        """Stop the polling loop.

        This should be called when the server shuts down.
        """
        if not self._running:
            return

        self._running = False

        # Wait for the task to finish
        if self._task:
            await self._task

    async def poll_now(self) -> None:
        """Immediately poll all tasks once.

        Useful for testing or forcing an immediate update.
        """
        await self._poll_once()

    def get_stats(self) -> dict:
        """Get polling statistics.

        Returns:
            Dict with polling stats (corrections, running state, etc.)
        """
        return {
            "running": self._running,
            "interval": self.interval,
            "correction_count": self._correction_count,
        }


# Global poller instance
_poller: Optional[StatusPoller] = None


def get_status_poller(interval: float = 2.0) -> StatusPoller:
    """Get or create the global status poller instance.

    Args:
        interval: Polling interval in seconds

    Returns:
        StatusPoller instance
    """
    global _poller
    if _poller is None:
        _poller = StatusPoller(interval=interval)
    return _poller

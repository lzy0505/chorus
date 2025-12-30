"""Background status polling service.

Periodically checks Claude's actual status by analyzing terminal output,
updating the database when status changes are detected.
"""

import asyncio
import logging
from typing import Optional

from sqlmodel import Session, select

from database import engine
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

    def __init__(self, interval: float = 2.0):
        """Initialize the status poller.

        Args:
            interval: Polling interval in seconds (default: 2.0)
        """
        self.interval = interval
        self.detector = StatusDetector()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def _poll_once(self) -> None:
        """Poll status for all running tasks once."""
        try:
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

                    # Update if status changed
                    if detected_status != task.claude_status:
                        logger.info(
                            f"Task {task.id}: Status changed from "
                            f"{task.claude_status} to {detected_status} (detected)"
                        )
                        task.claude_status = detected_status

                        # Also update task status if needed
                        if detected_status == ClaudeStatus.waiting:
                            task.status = TaskStatus.waiting
                        elif task.status == TaskStatus.waiting and detected_status == ClaudeStatus.idle:
                            # Claude finished responding to permission
                            task.status = TaskStatus.running

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

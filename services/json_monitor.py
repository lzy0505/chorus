"""JSON-based monitoring service for Claude Code sessions.

This service monitors Claude sessions running in --output-format stream-json mode
by polling tmux output and parsing JSON events.
"""

import asyncio
import logging
from typing import Optional

from sqlmodel import Session, select

from models import Task, ClaudeStatus
from services.gitbutler import GitButlerService
from services.json_parser import JsonEventParser, ClaudeJsonEvent
from services.tmux import TmuxService

logger = logging.getLogger(__name__)


class JsonMonitor:
    """Monitor Claude sessions via JSON event parsing.

    This monitor:
    1. Polls tmux output for JSON events
    2. Parses structured events (session_start, tool_use, tool_result, etc.)
    3. Updates task status in database
    4. Triggers GitButler commits on file edits
    5. Stores session_id for --resume support
    """

    def __init__(
        self,
        db: Session,
        tmux: TmuxService,
        gitbutler: GitButlerService,
        json_parser: JsonEventParser,
        poll_interval: float = 1.0,
    ):
        """Initialize the JSON monitor.

        Args:
            db: Database session for task updates
            tmux: TmuxService for capturing output
            gitbutler: GitButlerService for auto-commits
            json_parser: JsonEventParser for parsing events
            poll_interval: Seconds between polling cycles
        """
        self.db = db
        self.tmux = tmux
        self.gitbutler = gitbutler
        self.json_parser = json_parser
        self.poll_interval = poll_interval
        self._tasks: dict[int, asyncio.Task] = {}
        self._running = False
        self._last_event_count: dict[int, int] = {}

    async def start(self):
        """Start the monitoring loop."""
        self._running = True
        logger.info("JSON monitor started")

        while self._running:
            try:
                # Get all running tasks from database
                statement = select(Task).where(Task.status == "running")
                tasks = self.db.exec(statement).all()

                for task in tasks:
                    # Start monitoring task if not already monitored
                    if task.id not in self._tasks or self._tasks[task.id].done():
                        self._tasks[task.id] = asyncio.create_task(
                            self._monitor_task(task.id)
                        )

                await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

    def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        logger.info("JSON monitor stopped")

    async def _monitor_task(self, task_id: int):
        """Monitor a specific task for JSON events.

        Args:
            task_id: The task ID to monitor
        """
        logger.debug(f"Starting JSON monitoring for task {task_id}")

        while self._running:
            try:
                # Capture JSON events from tmux
                output = self.tmux.capture_json_events(task_id)

                if output:
                    # Parse events
                    events = self.json_parser.parse_output(output)

                    # Only process new events (simple deduplication)
                    previous_count = self._last_event_count.get(task_id, 0)
                    new_events = events[previous_count:]

                    if new_events:
                        logger.debug(f"Task {task_id}: Found {len(new_events)} new events")

                        # Process each new event
                        for event in new_events:
                            await self._handle_event(task_id, event)

                        # Update event count
                        self._last_event_count[task_id] = len(events)

                await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Error monitoring task {task_id}: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

    async def _handle_event(self, task_id: int, event: ClaudeJsonEvent):
        """Handle a single JSON event.

        Args:
            task_id: The task ID
            event: The parsed JSON event
        """
        try:
            # Get task from database
            statement = select(Task).where(Task.id == task_id)
            task = self.db.exec(statement).first()
            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return

            event_type = event.event_type
            logger.debug(f"Task {task_id}: Handling event type '{event_type}'")

            match event_type:
                case "session_start":
                    # Extract session ID for --resume support
                    session_id = event.data.get("session_id")
                    if session_id:
                        task.json_session_id = session_id
                        task.claude_status = ClaudeStatus.idle
                        logger.info(f"Task {task_id}: Session started, ID={session_id}")
                        self.db.commit()

                case "tool_use":
                    # Claude is using a tool, mark as busy
                    task.claude_status = ClaudeStatus.busy
                    tool_name = event.data.get("tool", "unknown")
                    logger.debug(f"Task {task_id}: Tool use - {tool_name}")
                    self.db.commit()

                case "tool_result":
                    # Tool execution completed
                    tool_name = event.data.get("tool")
                    status = event.data.get("status")

                    # If file was edited, commit to GitButler
                    if tool_name in ["Edit", "Write", "MultiEdit"] and status == "success":
                        if task.stack_name:
                            logger.info(f"Task {task_id}: File edited, committing to stack {task.stack_name}")
                            try:
                                self.gitbutler.commit_to_stack(task.stack_name)
                            except Exception as e:
                                logger.error(f"Failed to commit to stack: {e}", exc_info=True)

                    # Mark Claude as idle after tool completion
                    task.claude_status = ClaudeStatus.idle
                    self.db.commit()

                case "result":
                    # Final result event - extract session_id for future resumption
                    session_id = event.data.get("session_id")
                    if session_id:
                        task.json_session_id = session_id
                        logger.debug(f"Task {task_id}: Result event, session_id={session_id}")
                        self.db.commit()

                    # Mark as idle
                    task.claude_status = ClaudeStatus.idle
                    self.db.commit()

                case "text" | "assistant":
                    # Claude is responding, mark as busy
                    if task.claude_status != ClaudeStatus.busy:
                        task.claude_status = ClaudeStatus.busy
                        self.db.commit()

                case "permission_request":
                    # Claude is asking for permission
                    task.claude_status = ClaudeStatus.waiting
                    logger.info(f"Task {task_id}: Permission request")
                    self.db.commit()

                case _:
                    # Unknown event type, log for debugging
                    logger.debug(f"Task {task_id}: Unknown event type '{event_type}'")

        except Exception as e:
            logger.error(f"Error handling event for task {task_id}: {e}", exc_info=True)

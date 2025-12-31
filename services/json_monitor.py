"""JSON-based monitoring service for Claude Code sessions.

This service monitors Claude sessions running in --output-format stream-json mode
by polling tmux output and parsing JSON events.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlmodel import Session, select

from models import Task, ClaudeStatus
from services.gitbutler import GitButlerService
from services.json_parser import JsonEventParser, ClaudeJsonEvent
from services.tmux import TmuxService, get_transcript_dir

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
        self._tasks: dict[UUID, asyncio.Task] = {}
        self._running = False
        self._last_event_count: dict[UUID, int] = {}
        self._recent_tool_uses: dict[UUID, list[dict]] = {}  # Track tool_use events for pairing
        self._stack_discovered: dict[UUID, bool] = {}  # Track if stack was discovered per task

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

    async def _monitor_task(self, task_id: UUID):
        """Monitor a specific task for JSON events.

        Args:
            task_id: The task UUID to monitor
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

    async def _handle_event(self, task_id: UUID, event: ClaudeJsonEvent):
        """Handle a single JSON event with GitButler hook integration.

        Args:
            task_id: The task UUID
            event: The parsed JSON event
        """
        try:
            # Get task from database
            statement = select(Task).where(Task.id == task_id)
            task = self.db.exec(statement).first()
            if not task:
                logger.warning(f"Task {task_id} not found in database")
                return

            # Get transcript path for GitButler hooks
            transcript_dir = get_transcript_dir(task_id)
            transcript_path = str(transcript_dir / "transcript.json")

            event_type = event.event_type
            logger.debug(f"Task {task_id}: Handling event type '{event_type}'")

            match event_type:
                case "session_start":
                    # Extract Claude session ID for --resume support (not for hooks!)
                    session_id = event.data.get("session_id")
                    if session_id:
                        task.claude_session_id = session_id
                        task.claude_status = ClaudeStatus.idle
                        logger.info(f"Task {task_id}: Claude session started, ID={session_id}")
                        self.db.commit()

                case "tool_use":
                    # Claude is using a tool
                    task.claude_status = ClaudeStatus.busy
                    tool_name = event.data.get("toolName", "unknown")
                    tool_input = event.data.get("toolInput", {})
                    file_path = tool_input.get("file_path")

                    logger.debug(f"Task {task_id}: Tool use - {tool_name}")

                    # Store tool_use event for pairing with tool_result
                    if task_id not in self._recent_tool_uses:
                        self._recent_tool_uses[task_id] = []
                    self._recent_tool_uses[task_id].append(event.data)
                    # Keep only last 10 tool uses to prevent memory growth
                    self._recent_tool_uses[task_id] = self._recent_tool_uses[task_id][-10:]

                    # Call pre-tool hook for file edits
                    if tool_name in ["Edit", "Write", "MultiEdit"] and file_path:
                        logger.debug(f"Task {task_id}: Calling pre-tool hook for {file_path}")
                        try:
                            self.gitbutler.call_pre_tool_hook(
                                session_id=str(task_id),  # Use task UUID for GitButler
                                file_path=file_path,
                                transcript_path=transcript_path,
                                tool_name=tool_name
                            )
                        except Exception as e:
                            logger.error(f"Pre-tool hook failed: {e}", exc_info=True)

                    self.db.commit()

                case "tool_result":
                    # Tool execution completed
                    tool_use_id = event.data.get("toolUseId")

                    # Find corresponding tool_use event
                    tool_use_event = None
                    if task_id in self._recent_tool_uses:
                        for tu in reversed(self._recent_tool_uses[task_id]):
                            if tu.get("id") == tool_use_id:
                                tool_use_event = tu
                                break

                    if tool_use_event:
                        tool_name = tool_use_event.get("toolName")
                        tool_input = tool_use_event.get("toolInput", {})
                        file_path = tool_input.get("file_path")
                        is_error = event.data.get("isError", False)

                        # Call post-tool hook for successful file edits
                        if tool_name in ["Edit", "Write", "MultiEdit"] and file_path and not is_error:
                            logger.debug(f"Task {task_id}: Calling post-tool hook for {file_path}")
                            try:
                                self.gitbutler.call_post_tool_hook(
                                    session_id=str(task_id),  # Use task UUID for GitButler
                                    file_path=file_path,
                                    transcript_path=transcript_path,
                                    tool_name=tool_name
                                )

                                # Discover stack after first successful edit
                                if not self._stack_discovered.get(task_id, False):
                                    logger.info(f"Task {task_id}: Discovering GitButler stack")
                                    stack_info = self.gitbutler.discover_stack_for_session(
                                        session_id=str(task_id),
                                        edited_file=file_path
                                    )
                                    if stack_info:
                                        stack_name, stack_cli_id = stack_info
                                        task.stack_name = stack_name
                                        task.stack_cli_id = stack_cli_id
                                        self._stack_discovered[task_id] = True
                                        logger.info(f"Task {task_id}: Discovered stack {stack_name}")

                                # Commit to stack if discovered
                                if task.stack_name:
                                    logger.info(f"Task {task_id}: Committing to stack {task.stack_name}")
                                    self.gitbutler.commit_to_stack(task.stack_name)

                            except Exception as e:
                                logger.error(f"Post-tool hook or commit failed: {e}", exc_info=True)

                    # Mark Claude as idle after tool completion
                    task.claude_status = ClaudeStatus.idle
                    self.db.commit()

                case "result":
                    # Final result event - extract Claude session_id for future --resume
                    session_id = event.data.get("sessionId")
                    if session_id and not task.claude_session_id:
                        task.claude_session_id = session_id
                        logger.debug(f"Task {task_id}: Extracted Claude session_id={session_id}")
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

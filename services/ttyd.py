"""ttyd service for web terminal access.

Manages ttyd processes that provide web-based terminal access to task tmux sessions.
Each task gets its own ttyd instance on a unique port.
"""

import subprocess
import signal
import os
from dataclasses import dataclass
from typing import Optional

from config import get_config


class TtydError(Exception):
    """Base exception for ttyd operations."""
    pass


class TtydNotRunningError(TtydError):
    """Raised when ttyd is not running for a task."""
    pass


class TtydAlreadyRunningError(TtydError):
    """Raised when ttyd is already running for a task."""
    pass


@dataclass
class TtydConfig:
    """ttyd configuration."""
    base_port: int = 7681
    enabled: bool = True


@dataclass
class TtydInfo:
    """Information about a running ttyd instance."""
    task_id: int
    port: int
    pid: int
    url: str


# Track running ttyd processes: task_id -> (pid, port)
_running_processes: dict[int, tuple[int, int]] = {}


def _get_port_for_task(task_id: int, base_port: int = 7681) -> int:
    """Calculate port for a task. Uses task_id + base_port."""
    return base_port + task_id


def _is_process_running(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class TtydService:
    """Manage ttyd processes for web terminal access.

    Each task can have a ttyd instance that provides browser-based
    terminal access to its tmux session.
    """

    def __init__(self, base_port: int = 7681):
        """Initialize the ttyd service.

        Args:
            base_port: Base port for ttyd instances. Task ports are base_port + task_id.
        """
        self.base_port = base_port

    def get_port(self, task_id: int) -> int:
        """Get the port for a task's ttyd instance."""
        return _get_port_for_task(task_id, self.base_port)

    def get_url(self, task_id: int) -> str:
        """Get the URL for a task's ttyd instance."""
        port = self.get_port(task_id)
        return f"http://localhost:{port}"

    def is_running(self, task_id: int) -> bool:
        """Check if ttyd is running for a task."""
        if task_id not in _running_processes:
            return False
        pid, _ = _running_processes[task_id]
        if not _is_process_running(pid):
            # Clean up stale entry
            del _running_processes[task_id]
            return False
        return True

    def start(self, task_id: int, session_id: str) -> TtydInfo:
        """Start ttyd for a task's tmux session.

        Args:
            task_id: The task ID.
            session_id: The tmux session ID to attach to.

        Returns:
            TtydInfo with connection details.

        Raises:
            TtydAlreadyRunningError: If ttyd is already running for this task.
            TtydError: If ttyd fails to start.
        """
        if self.is_running(task_id):
            raise TtydAlreadyRunningError(f"ttyd already running for task {task_id}")

        port = self.get_port(task_id)

        # Build ttyd command
        # -W: writable (allow input)
        # -p: port
        # Use 'setsid' to run tmux attach in its own session, preventing SIGHUP
        # propagation when WebSocket clients disconnect
        # This prevents page refreshes from killing processes in the tmux session
        cmd = [
            "ttyd",
            "-W",  # Writable
            "-p", str(port),
            "sh", "-c", f"setsid tmux attach -t {session_id}"
        ]

        try:
            # Start ttyd in background
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # Detach from parent
            )

            # Store process info
            _running_processes[task_id] = (process.pid, port)

            return TtydInfo(
                task_id=task_id,
                port=port,
                pid=process.pid,
                url=self.get_url(task_id),
            )

        except FileNotFoundError:
            raise TtydError("ttyd not found. Install with: brew install ttyd")
        except Exception as e:
            raise TtydError(f"Failed to start ttyd: {e}")

    def stop(self, task_id: int) -> None:
        """Stop ttyd for a task.

        Args:
            task_id: The task ID.

        Raises:
            TtydNotRunningError: If ttyd is not running for this task.
        """
        if task_id not in _running_processes:
            raise TtydNotRunningError(f"ttyd not running for task {task_id}")

        pid, port = _running_processes[task_id]

        try:
            # Send SIGTERM to gracefully stop
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass  # Process already gone

        # Remove from tracking
        del _running_processes[task_id]

    def stop_if_running(self, task_id: int) -> bool:
        """Stop ttyd if it's running for a task.

        Args:
            task_id: The task ID.

        Returns:
            True if ttyd was stopped, False if it wasn't running.
        """
        if not self.is_running(task_id):
            return False

        try:
            self.stop(task_id)
            return True
        except TtydNotRunningError:
            return False

    def get_info(self, task_id: int) -> Optional[TtydInfo]:
        """Get info about a running ttyd instance.

        Args:
            task_id: The task ID.

        Returns:
            TtydInfo if running, None otherwise.
        """
        if not self.is_running(task_id):
            return None

        pid, port = _running_processes[task_id]
        return TtydInfo(
            task_id=task_id,
            port=port,
            pid=pid,
            url=self.get_url(task_id),
        )

    def list_running(self) -> list[TtydInfo]:
        """List all running ttyd instances.

        Returns:
            List of TtydInfo for all running instances.
        """
        result = []
        # Iterate over copy to allow modification during iteration
        for task_id in list(_running_processes.keys()):
            info = self.get_info(task_id)
            if info:
                result.append(info)
        return result

    def cleanup_all(self) -> int:
        """Stop all running ttyd instances.

        Returns:
            Number of instances stopped.
        """
        count = 0
        for task_id in list(_running_processes.keys()):
            if self.stop_if_running(task_id):
                count += 1
        return count

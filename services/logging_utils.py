"""Logging utilities for Chorus.

Provides helper functions for logging subprocess commands and external tool interactions.
"""

import logging
import subprocess
from typing import Optional

from config import get_config


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Configured logger instance.
    """
    return logging.getLogger(name)


def log_subprocess_call(
    logger: logging.Logger,
    cmd: list[str],
    result: Optional[subprocess.CompletedProcess] = None,
    error: Optional[Exception] = None,
) -> None:
    """Log a subprocess command execution.

    Args:
        logger: Logger instance to use.
        cmd: Command and arguments that were executed.
        result: CompletedProcess result (if command completed).
        error: Exception that was raised (if command failed).
    """
    try:
        config = get_config()
        if not config.logging.log_subprocess:
            return
    except RuntimeError:
        # Config not initialized yet, skip logging
        return

    # Format command for logging (truncate long arguments)
    cmd_str = " ".join(_truncate_arg(arg) for arg in cmd)

    if error:
        logger.error(f"Command failed: {cmd_str}", exc_info=error)
    elif result:
        if result.returncode == 0:
            logger.debug(f"Command succeeded: {cmd_str}")
            if result.stdout:
                logger.debug(f"  stdout: {_truncate(result.stdout)}")
        else:
            logger.warning(
                f"Command failed (exit {result.returncode}): {cmd_str}"
            )
            if result.stderr:
                logger.warning(f"  stderr: {_truncate(result.stderr)}")
            if result.stdout:
                logger.debug(f"  stdout: {_truncate(result.stdout)}")
    else:
        # Just log the command being executed
        logger.debug(f"Executing: {cmd_str}")


def log_api_request(
    logger: logging.Logger,
    method: str,
    path: str,
    status_code: Optional[int] = None,
    error: Optional[Exception] = None,
) -> None:
    """Log an API request.

    Args:
        logger: Logger instance to use.
        method: HTTP method (GET, POST, etc.).
        path: Request path.
        status_code: HTTP status code (if request completed).
        error: Exception that was raised (if request failed).
    """
    try:
        config = get_config()
        if not config.logging.log_api_requests:
            return
    except RuntimeError:
        # Config not initialized yet, skip logging
        return

    if error:
        logger.error(f"{method} {path} - Error: {error}", exc_info=error)
    elif status_code:
        if 200 <= status_code < 300:
            logger.info(f"{method} {path} - {status_code}")
        elif 400 <= status_code < 500:
            logger.warning(f"{method} {path} - {status_code}")
        else:
            logger.error(f"{method} {path} - {status_code}")
    else:
        logger.debug(f"{method} {path}")


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text for logging.

    Args:
        text: Text to truncate.
        max_len: Maximum length.

    Returns:
        Truncated text with ellipsis if needed.
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _truncate_arg(arg: str, max_len: int = 100) -> str:
    """Truncate a command argument for logging.

    Args:
        arg: Argument to truncate.
        max_len: Maximum length.

    Returns:
        Truncated argument with ellipsis if needed.
    """
    if len(arg) <= max_len:
        return arg
    return arg[:max_len] + "..."


def configure_logging(level: str = "INFO", format_str: Optional[str] = None) -> None:
    """Configure logging for the entire application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        format_str: Log format string. If None, uses default format.
    """
    if format_str is None:
        format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Convert string level to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format=format_str,
        force=True,  # Reconfigure even if already configured
    )

    # Log the configuration
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured: level={level}, subprocess={_is_subprocess_logging_enabled()}, api={_is_api_logging_enabled()}")


def _is_subprocess_logging_enabled() -> bool:
    """Check if subprocess logging is enabled."""
    try:
        config = get_config()
        return config.logging.log_subprocess
    except RuntimeError:
        return True


def _is_api_logging_enabled() -> bool:
    """Check if API logging is enabled."""
    try:
        config = get_config()
        return config.logging.log_api_requests
    except RuntimeError:
        return True

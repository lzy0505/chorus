"""GitButler service for stack-based version control.

Each task gets its own GitButler stack (virtual branch).
Chorus commits file changes to the appropriate stack via hooks.
"""

import json
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from config import get_config
from services.logging_utils import get_logger, log_subprocess_call

logger = get_logger(__name__)


class GitButlerError(Exception):
    """Base exception for GitButler operations."""

    pass


class StackNotFoundError(GitButlerError):
    """Raised when a stack doesn't exist."""

    pass


class StackExistsError(GitButlerError):
    """Raised when trying to create a stack that already exists."""

    pass


class CommitError(GitButlerError):
    """Raised when a commit operation fails."""

    pass


@dataclass
class Change:
    """A file change in the workspace."""

    cli_id: str
    file_path: str
    change_type: str  # "added", "modified", "deleted"


@dataclass
class Commit:
    """A commit in a stack."""

    cli_id: str
    commit_id: str
    message: str
    author_name: str
    author_email: str
    created_at: str
    conflicted: Optional[bool] = None
    changes: list[Change] = field(default_factory=list)


@dataclass
class Stack:
    """A GitButler stack (virtual branch)."""

    name: str
    cli_id: str
    commits: list[Commit] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)


@dataclass
class WorkspaceStatus:
    """GitButler workspace status."""

    stacks: list[Stack]
    unassigned_changes: list[Change]
    merge_base: Optional[Commit] = None


def _run_but(
    args: list[str], check: bool = True, cwd: Optional[str] = None
) -> subprocess.CompletedProcess:
    """Run a GitButler CLI command.

    Args:
        args: Command arguments (without 'but').
        check: Whether to raise on non-zero exit.
        cwd: Working directory (defaults to config project_root).

    Returns:
        CompletedProcess with stdout/stderr.
    """
    cmd = ["but"] + args
    if cwd is None:
        config = get_config()
        cwd = str(config.project_root)

    log_subprocess_call(logger, cmd)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            cwd=cwd,
        )
        log_subprocess_call(logger, cmd, result=result)
        return result
    except Exception as e:
        log_subprocess_call(logger, cmd, error=e)
        raise


def _parse_change(data: dict) -> Change:
    """Parse a change from JSON."""
    return Change(
        cli_id=data.get("cliId", ""),
        file_path=data.get("filePath", ""),
        change_type=data.get("changeType", ""),
    )


def _parse_commit(data: dict) -> Commit:
    """Parse a commit from JSON."""
    changes = []
    if data.get("changes"):
        changes = [_parse_change(c) for c in data["changes"]]

    return Commit(
        cli_id=data.get("cliId", ""),
        commit_id=data.get("commitId", ""),
        message=data.get("message", ""),
        author_name=data.get("authorName", ""),
        author_email=data.get("authorEmail", ""),
        created_at=data.get("createdAt", ""),
        conflicted=data.get("conflicted"),
        changes=changes,
    )


def _parse_stack(data: dict) -> Stack:
    """Parse a stack from GitButler CLI JSON output.

    GitButler CLI returns a wrapper structure with 'branches' array containing the actual branch data.
    """
    # Extract the first branch from the wrapper
    if not data.get("branches"):
        return Stack(name="", cli_id=data.get("cliId", ""), commits=[], changes=[])

    branch_data = data["branches"][0]

    commits = []
    if branch_data.get("commits"):
        commits = [_parse_commit(c) for c in branch_data["commits"]]

    # Changes are in assignedChanges at wrapper level
    changes = []
    if data.get("assignedChanges"):
        changes = [_parse_change(c) for c in data["assignedChanges"]]

    return Stack(
        name=branch_data.get("name", ""),
        cli_id=branch_data.get("cliId", ""),
        commits=commits,
        changes=changes,
    )


class GitButlerService:
    """Stack-based version control for tasks.

    Each task gets its own stack (virtual branch) where its changes are committed.
    Stacks run in parallel and can be merged/pushed independently.

    Lifecycle:
    1. create_stack() - Create stack when task starts
    2. commit_to_stack() - Commit changes (triggered by hooks)
    3. get_stack_commits() - View task's commit history
    4. delete_stack() - Cleanup when task fails (optional)
    """

    def __init__(self, project_root: Optional[str] = None):
        """Initialize the GitButler service.

        Args:
            project_root: Working directory. Defaults to config project_root.
        """
        if project_root is None:
            config = get_config()
            project_root = str(config.project_root)
        self.project_root = project_root

    def get_status(self) -> WorkspaceStatus:
        """Get the current workspace status.

        Returns:
            WorkspaceStatus with stacks and unassigned changes.

        Raises:
            GitButlerError: If the command fails.
        """
        logger.debug("Getting GitButler workspace status")
        result = _run_but(["status", "-j"], check=False, cwd=self.project_root)

        if result.returncode != 0:
            raise GitButlerError(f"Failed to get status: {result.stderr}")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise GitButlerError(f"Failed to parse status JSON: {e}")

        stacks = []
        if data.get("stacks"):
            stacks = [_parse_stack(s) for s in data["stacks"]]

        unassigned = []
        if data.get("unassignedChanges"):
            unassigned = [_parse_change(c) for c in data["unassignedChanges"]]

        merge_base = None
        if data.get("mergeBase"):
            merge_base = _parse_commit(data["mergeBase"])

        return WorkspaceStatus(
            stacks=stacks,
            unassigned_changes=unassigned,
            merge_base=merge_base,
        )

    def stack_exists(self, name: str) -> bool:
        """Check if a stack exists.

        Args:
            name: Stack name.

        Returns:
            True if the stack exists.
        """
        try:
            status = self.get_status()
            return any(s.name == name for s in status.stacks)
        except GitButlerError:
            return False

    def create_stack(self, name: str) -> Stack:
        """Create a new stack (virtual branch).

        Args:
            name: Name for the new stack.

        Returns:
            The created Stack.

        Raises:
            StackExistsError: If a stack with this name already exists.
            GitButlerError: If the command fails.
        """
        if self.stack_exists(name):
            raise StackExistsError(f"Stack '{name}' already exists")

        logger.info(f"Creating GitButler stack: {name}")
        result = _run_but(
            ["branch", "new", name, "-j"], check=False, cwd=self.project_root
        )

        if result.returncode != 0:
            raise GitButlerError(f"Failed to create stack: {result.stderr}")

        # GitButler CLI returns {"branch": "name"} format, not a full stack object
        # Fetch the full stack info from status
        status = self.get_status()
        for stack in status.stacks:
            if stack.name == name:
                logger.info(f"Created GitButler stack: {name}")
                return stack
        raise GitButlerError(f"Stack '{name}' created but not found in status")

    def delete_stack(self, name: str, force: bool = True) -> None:
        """Delete a stack.

        Args:
            name: Stack name to delete.
            force: Force deletion even if stack has uncommitted changes.

        Raises:
            StackNotFoundError: If the stack doesn't exist.
            GitButlerError: If the command fails.
        """
        if not self.stack_exists(name):
            raise StackNotFoundError(f"Stack '{name}' not found")

        logger.info(f"Deleting GitButler stack: {name} (force={force})")
        args = ["branch", "delete", name]
        if force:
            args.append("--force")

        result = _run_but(args, check=False, cwd=self.project_root)

        if result.returncode != 0:
            raise GitButlerError(f"Failed to delete stack: {result.stderr}")

        logger.info(f"Deleted GitButler stack: {name}")

    def commit_to_stack(
        self,
        stack_name: str,
        message: Optional[str] = None,
        create_if_missing: bool = False,
    ) -> Optional[Commit]:
        """Commit current changes to a stack.

        Args:
            stack_name: Stack to commit to.
            message: Commit message. If None, GitButler generates one.
            create_if_missing: If True, create the stack if it doesn't exist.

        Returns:
            The created Commit, or None if there were no changes.

        Raises:
            StackNotFoundError: If the stack doesn't exist and create_if_missing is False.
            CommitError: If the commit fails.
        """
        # Check if stack exists
        if not self.stack_exists(stack_name):
            if create_if_missing:
                logger.info(f"Stack '{stack_name}' doesn't exist, creating it")
                self.create_stack(stack_name)
            else:
                raise StackNotFoundError(f"Stack '{stack_name}' not found")

        # Build commit command
        logger.info(f"Committing to GitButler stack: {stack_name}" + (f" with message: {message}" if message else ""))
        args = ["commit", stack_name, "-j"]
        if message:
            args.extend(["-m", message])

        result = _run_but(args, check=False, cwd=self.project_root)

        # Check for "nothing to commit" case
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if "nothing to commit" in stderr or "no changes" in stderr:
                logger.debug(f"No changes to commit to stack: {stack_name}")
                return None
            raise CommitError(f"Failed to commit: {result.stderr}")

        # Parse the commit response
        try:
            data = json.loads(result.stdout)
            if isinstance(data, dict) and "commitId" in data:
                return _parse_commit(data)
            # Some responses wrap the commit
            if isinstance(data, dict) and "commit" in data:
                return _parse_commit(data["commit"])
        except json.JSONDecodeError:
            pass

        # Command succeeded - fetch latest commit from stack
        commits = self.get_stack_commits(stack_name)
        commit = commits[0] if commits else None
        if commit:
            logger.info(f"Created commit in stack '{stack_name}': {commit.commit_id[:8]}")
        return commit

    def get_stack_commits(self, stack_name: str) -> list[Commit]:
        """Get commits in a stack.

        Args:
            stack_name: Stack name.

        Returns:
            List of commits (newest first).

        Raises:
            StackNotFoundError: If the stack doesn't exist.
            GitButlerError: If the command fails.
        """
        if not self.stack_exists(stack_name):
            raise StackNotFoundError(f"Stack '{stack_name}' not found")

        result = _run_but(
            ["branch", "show", stack_name, "-j"], check=False, cwd=self.project_root
        )

        if result.returncode != 0:
            raise GitButlerError(f"Failed to get stack commits: {result.stderr}")

        try:
            data = json.loads(result.stdout)
            commits = []
            if isinstance(data, list):
                commits = [_parse_commit(c) for c in data]
            elif isinstance(data, dict) and "commits" in data:
                commits = [_parse_commit(c) for c in data["commits"]]
            return commits
        except json.JSONDecodeError as e:
            raise GitButlerError(f"Failed to parse commits JSON: {e}")

    def get_stack_by_name(self, name: str) -> Optional[Stack]:
        """Get a stack by name.

        Args:
            name: Stack name.

        Returns:
            The Stack if found, None otherwise.
        """
        try:
            status = self.get_status()
            for stack in status.stacks:
                if stack.name == name:
                    return stack
        except GitButlerError:
            pass
        return None

    def list_stacks(self) -> list[Stack]:
        """List all stacks in the workspace.

        Returns:
            List of all stacks.
        """
        try:
            status = self.get_status()
            return status.stacks
        except GitButlerError:
            return []

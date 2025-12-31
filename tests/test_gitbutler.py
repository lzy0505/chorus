"""Tests for GitButler service."""

import json
import pytest
from subprocess import CompletedProcess
from unittest.mock import patch, MagicMock

from services.gitbutler import (
    GitButlerService,
    GitButlerError,
    StackNotFoundError,
    StackExistsError,
    CommitError,
    Change,
    Commit,
    Stack,
    WorkspaceStatus,
    _run_but,
    _parse_change,
    _parse_commit,
    _parse_stack,
)


class TestParsingFunctions:
    """Tests for JSON parsing helper functions."""

    def test_parse_change(self):
        """Test parsing a change from JSON."""
        data = {
            "cliId": "g0",
            "filePath": "src/main.py",
            "changeType": "modified",
        }

        change = _parse_change(data)

        assert change.cli_id == "g0"
        assert change.file_path == "src/main.py"
        assert change.change_type == "modified"

    def test_parse_change_minimal(self):
        """Test parsing change with missing fields."""
        change = _parse_change({})

        assert change.cli_id == ""
        assert change.file_path == ""
        assert change.change_type == ""

    def test_parse_commit(self):
        """Test parsing a commit from JSON."""
        data = {
            "cliId": "abc123",
            "commitId": "deadbeef",
            "message": "Fix bug",
            "authorName": "Test User",
            "authorEmail": "test@example.com",
            "createdAt": "2025-01-01T00:00:00Z",
            "conflicted": False,
            "changes": [
                {"cliId": "c1", "filePath": "file.py", "changeType": "modified"}
            ],
        }

        commit = _parse_commit(data)

        assert commit.cli_id == "abc123"
        assert commit.commit_id == "deadbeef"
        assert commit.message == "Fix bug"
        assert commit.author_name == "Test User"
        assert commit.author_email == "test@example.com"
        assert commit.conflicted is False
        assert len(commit.changes) == 1
        assert commit.changes[0].file_path == "file.py"

    def test_parse_commit_minimal(self):
        """Test parsing commit with missing fields."""
        commit = _parse_commit({})

        assert commit.cli_id == ""
        assert commit.commit_id == ""
        assert commit.message == ""
        assert commit.changes == []

    def test_parse_stack(self):
        """Test parsing a stack from JSON (new GitButler format)."""
        data = {
            "cliId": "s1",
            "assignedChanges": [
                {"cliId": "g0", "filePath": "auth.py", "changeType": "added"}
            ],
            "branches": [
                {
                    "name": "feature-auth",
                    "cliId": "s1",
                    "commits": [
                        {
                            "cliId": "c1",
                            "commitId": "abc",
                            "message": "Add auth",
                            "authorName": "User",
                            "authorEmail": "user@test.com",
                            "createdAt": "2025-01-01T00:00:00Z",
                        }
                    ],
                }
            ],
        }

        stack = _parse_stack(data)

        assert stack.name == "feature-auth"
        assert stack.cli_id == "s1"
        assert len(stack.commits) == 1
        assert stack.commits[0].message == "Add auth"
        assert len(stack.changes) == 1
        assert stack.changes[0].file_path == "auth.py"

    def test_parse_stack_minimal(self):
        """Test parsing stack with missing fields."""
        data = {"cliId": "s1", "assignedChanges": [], "branches": []}
        stack = _parse_stack(data)

        assert stack.name == ""
        assert stack.cli_id == "s1"
        assert stack.commits == []
        assert stack.changes == []


class TestRunBut:
    """Tests for _run_but helper function."""

    @patch("services.gitbutler.subprocess.run")
    def test_run_but_success(self, mock_run):
        """Test running a successful but command."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status"], returncode=0, stdout="success", stderr=""
        )

        result = _run_but(["status"])

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["but", "status"]
        assert result.returncode == 0

    @patch("services.gitbutler.subprocess.run")
    def test_run_but_with_cwd(self, mock_run):
        """Test running but command with custom working directory."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status"], returncode=0, stdout="", stderr=""
        )

        _run_but(["status"], cwd="/custom/path")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == "/custom/path"


class TestGitButlerServiceGetStatus:
    """Tests for GitButlerService.get_status."""

    @patch("services.gitbutler._run_but")
    def test_get_status_success(self, mock_run):
        """Test getting workspace status."""
        status_json = {
            "stacks": [
                {
                    "cliId": "s1",
                    "assignedChanges": [],
                    "branches": [
                        {"name": "feature-1", "cliId": "s1", "commits": []}
                    ],
                }
            ],
            "unassignedChanges": [
                {"cliId": "g0", "filePath": "README.md", "changeType": "modified"}
            ],
            "mergeBase": {
                "cliId": "mb",
                "commitId": "base123",
                "message": "Base commit",
                "authorName": "User",
                "authorEmail": "user@test.com",
                "createdAt": "2025-01-01T00:00:00Z",
            },
        }
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps(status_json),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        status = service.get_status()

        assert len(status.stacks) == 1
        assert status.stacks[0].name == "feature-1"
        assert len(status.unassigned_changes) == 1
        assert status.unassigned_changes[0].file_path == "README.md"
        assert status.merge_base is not None
        assert status.merge_base.commit_id == "base123"

    @patch("services.gitbutler._run_but")
    def test_get_status_empty(self, mock_run):
        """Test getting status with no stacks."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        status = service.get_status()

        assert status.stacks == []
        assert status.unassigned_changes == []

    @patch("services.gitbutler._run_but")
    def test_get_status_command_fails(self, mock_run):
        """Test handling command failure."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=1,
            stdout="",
            stderr="GitButler not initialized",
        )

        service = GitButlerService(project_root="/test")

        with pytest.raises(GitButlerError) as exc_info:
            service.get_status()

        assert "Failed to get status" in str(exc_info.value)

    @patch("services.gitbutler._run_but")
    def test_get_status_invalid_json(self, mock_run):
        """Test handling invalid JSON response."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout="not valid json",
            stderr="",
        )

        service = GitButlerService(project_root="/test")

        with pytest.raises(GitButlerError) as exc_info:
            service.get_status()

        assert "Failed to parse" in str(exc_info.value)


class TestGitButlerServiceStackExists:
    """Tests for GitButlerService.stack_exists."""

    @patch("services.gitbutler._run_but")
    def test_stack_exists_true(self, mock_run):
        """Test when stack exists."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({
                "stacks": [{"cliId": "s1", "assignedChanges": [], "branches": [{"name": "my-stack", "cliId": "s1", "commits": []}]}],
                "unassignedChanges": [],
            }),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        assert service.stack_exists("my-stack") is True

    @patch("services.gitbutler._run_but")
    def test_stack_exists_false(self, mock_run):
        """Test when stack doesn't exist."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        assert service.stack_exists("nonexistent") is False

    @patch("services.gitbutler._run_but")
    def test_stack_exists_on_error(self, mock_run):
        """Test stack_exists returns False on error."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=1,
            stdout="",
            stderr="error",
        )

        service = GitButlerService(project_root="/test")
        assert service.stack_exists("any") is False


class TestGitButlerServiceCreateStack:
    """Tests for GitButlerService.create_stack."""

    @patch("services.gitbutler._run_but")
    def test_create_stack_success(self, mock_run):
        """Test creating a new stack."""
        # First call: status check (stack doesn't exist)
        # Second call: create stack
        # Third call: status check (to return the created stack)
        mock_run.side_effect = [
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
                stderr="",
            ),
            CompletedProcess(
                args=["but", "branch", "new", "task-1", "-j"],
                returncode=0,
                stdout=json.dumps({"branch": "task-1"}),
                stderr="",
            ),
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "stacks": [{
                        "cliId": "s1",
                        "assignedChanges": [],
                        "branches": [{"name": "task-1", "cliId": "s1", "commits": []}]
                    }],
                    "unassignedChanges": []
                }),
                stderr="",
            ),
        ]

        service = GitButlerService(project_root="/test")
        stack = service.create_stack("task-1")

        assert stack.name == "task-1"
        assert stack.cli_id == "s1"

    @patch("services.gitbutler._run_but")
    def test_create_stack_already_exists(self, mock_run):
        """Test creating stack that already exists."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({
                "stacks": [{"cliId": "s1", "assignedChanges": [], "branches": [{"name": "existing", "cliId": "s1", "commits": []}]}],
                "unassignedChanges": [],
            }),
            stderr="",
        )

        service = GitButlerService(project_root="/test")

        with pytest.raises(StackExistsError) as exc_info:
            service.create_stack("existing")

        assert "already exists" in str(exc_info.value)

    @patch("services.gitbutler._run_but")
    def test_create_stack_command_fails(self, mock_run):
        """Test handling create stack failure."""
        mock_run.side_effect = [
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
                stderr="",
            ),
            CompletedProcess(
                args=["but", "branch", "new", "task-1", "-j"],
                returncode=1,
                stdout="",
                stderr="Failed to create branch",
            ),
        ]

        service = GitButlerService(project_root="/test")

        with pytest.raises(GitButlerError) as exc_info:
            service.create_stack("task-1")

        assert "Failed to create stack" in str(exc_info.value)


class TestGitButlerServiceDeleteStack:
    """Tests for GitButlerService.delete_stack."""

    @patch("services.gitbutler._run_but")
    def test_delete_stack_success(self, mock_run):
        """Test deleting a stack."""
        mock_run.side_effect = [
            # Status check - stack exists
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "stacks": [{"cliId": "s1", "assignedChanges": [], "branches": [{"name": "to-delete", "cliId": "s1", "commits": []}]}],
                    "unassignedChanges": [],
                }),
                stderr="",
            ),
            # Delete command
            CompletedProcess(
                args=["but", "branch", "delete", "to-delete", "--force"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]

        service = GitButlerService(project_root="/test")
        service.delete_stack("to-delete")

        # Verify delete was called with --force
        delete_call = mock_run.call_args_list[1]
        assert "--force" in delete_call[0][0]

    @patch("services.gitbutler._run_but")
    def test_delete_stack_not_found(self, mock_run):
        """Test deleting non-existent stack."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
            stderr="",
        )

        service = GitButlerService(project_root="/test")

        with pytest.raises(StackNotFoundError) as exc_info:
            service.delete_stack("nonexistent")

        assert "not found" in str(exc_info.value)

    @patch("services.gitbutler._run_but")
    def test_delete_stack_without_force(self, mock_run):
        """Test deleting stack without force flag."""
        mock_run.side_effect = [
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "stacks": [{"cliId": "s1", "assignedChanges": [], "branches": [{"name": "stack", "cliId": "s1", "commits": []}]}],
                    "unassignedChanges": [],
                }),
                stderr="",
            ),
            CompletedProcess(
                args=["but", "branch", "delete", "stack"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]

        service = GitButlerService(project_root="/test")
        service.delete_stack("stack", force=False)

        delete_call = mock_run.call_args_list[1]
        assert "--force" not in delete_call[0][0]


class TestGitButlerServiceCommitToStack:
    """Tests for GitButlerService.commit_to_stack."""

    @patch("services.gitbutler._run_but")
    def test_commit_to_stack_success(self, mock_run):
        """Test committing to a stack."""
        mock_run.side_effect = [
            # Status check - stack exists
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "stacks": [{"cliId": "s1", "assignedChanges": [], "branches": [{"name": "my-stack", "cliId": "s1", "commits": []}]}],
                    "unassignedChanges": [],
                }),
                stderr="",
            ),
            # Commit command
            CompletedProcess(
                args=["but", "commit", "my-stack", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "commitId": "abc123",
                    "cliId": "c1",
                    "message": "Auto commit",
                    "authorName": "User",
                    "authorEmail": "user@test.com",
                    "createdAt": "2025-01-01T00:00:00Z",
                }),
                stderr="",
            ),
        ]

        service = GitButlerService(project_root="/test")
        commit = service.commit_to_stack("my-stack")

        assert commit is not None
        assert commit.commit_id == "abc123"

    @patch("services.gitbutler._run_but")
    def test_commit_to_stack_with_message(self, mock_run):
        """Test committing with a custom message."""
        mock_run.side_effect = [
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "stacks": [{"cliId": "s1", "assignedChanges": [], "branches": [{"name": "stack", "cliId": "s1", "commits": []}]}],
                    "unassignedChanges": [],
                }),
                stderr="",
            ),
            CompletedProcess(
                args=["but", "commit", "stack", "-j", "-m", "My message"],
                returncode=0,
                stdout=json.dumps({"commitId": "xyz", "cliId": "c1", "message": "My message", "authorName": "", "authorEmail": "", "createdAt": ""}),
                stderr="",
            ),
        ]

        service = GitButlerService(project_root="/test")
        service.commit_to_stack("stack", message="My message")

        commit_call = mock_run.call_args_list[1]
        args = commit_call[0][0]
        assert "-m" in args
        assert "My message" in args

    @patch("services.gitbutler._run_but")
    def test_commit_to_stack_nothing_to_commit(self, mock_run):
        """Test committing when there are no changes."""
        mock_run.side_effect = [
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "stacks": [{"cliId": "s1", "assignedChanges": [], "branches": [{"name": "stack", "cliId": "s1", "commits": []}]}],
                    "unassignedChanges": [],
                }),
                stderr="",
            ),
            CompletedProcess(
                args=["but", "commit", "stack", "-j"],
                returncode=1,
                stdout="",
                stderr="nothing to commit",
            ),
        ]

        service = GitButlerService(project_root="/test")
        result = service.commit_to_stack("stack")

        assert result is None

    @patch("services.gitbutler._run_but")
    def test_commit_to_stack_not_found(self, mock_run):
        """Test committing to non-existent stack."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
            stderr="",
        )

        service = GitButlerService(project_root="/test")

        with pytest.raises(StackNotFoundError):
            service.commit_to_stack("nonexistent")

    @patch("services.gitbutler._run_but")
    def test_commit_to_stack_create_if_missing(self, mock_run):
        """Test auto-creating stack when missing."""
        mock_run.side_effect = [
            # First status check - commit_to_stack's stack_exists call
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
                stderr="",
            ),
            # Second status check - create_stack's stack_exists call
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
                stderr="",
            ),
            # Create stack
            CompletedProcess(
                args=["but", "branch", "new", "new-stack", "-j"],
                returncode=0,
                stdout=json.dumps({"branch": "new-stack"}),
                stderr="",
            ),
            # Get status after create to fetch the created stack
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "stacks": [{
                        "cliId": "s1",
                        "assignedChanges": [],
                        "branches": [{"name": "new-stack", "cliId": "s1", "commits": []}]
                    }],
                    "unassignedChanges": []
                }),
                stderr="",
            ),
            # Commit
            CompletedProcess(
                args=["but", "commit", "new-stack", "-j"],
                returncode=0,
                stdout=json.dumps({"commitId": "abc", "cliId": "c1", "message": "", "authorName": "", "authorEmail": "", "createdAt": ""}),
                stderr="",
            ),
        ]

        service = GitButlerService(project_root="/test")
        commit = service.commit_to_stack("new-stack", create_if_missing=True)

        assert commit is not None

    @patch("services.gitbutler._run_but")
    def test_commit_to_stack_error(self, mock_run):
        """Test handling commit error."""
        mock_run.side_effect = [
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "stacks": [{"cliId": "s1", "assignedChanges": [], "branches": [{"name": "stack", "cliId": "s1", "commits": []}]}],
                    "unassignedChanges": [],
                }),
                stderr="",
            ),
            CompletedProcess(
                args=["but", "commit", "stack", "-j"],
                returncode=1,
                stdout="",
                stderr="Some other error",
            ),
        ]

        service = GitButlerService(project_root="/test")

        with pytest.raises(CommitError) as exc_info:
            service.commit_to_stack("stack")

        assert "Failed to commit" in str(exc_info.value)


class TestGitButlerServiceGetStackCommits:
    """Tests for GitButlerService.get_stack_commits."""

    @patch("services.gitbutler._run_but")
    def test_get_stack_commits_success(self, mock_run):
        """Test getting commits from a stack."""
        mock_run.side_effect = [
            # Status check
            CompletedProcess(
                args=["but", "status", "-j"],
                returncode=0,
                stdout=json.dumps({
                    "stacks": [{"cliId": "s1", "assignedChanges": [], "branches": [{"name": "stack", "cliId": "s1", "commits": []}]}],
                    "unassignedChanges": [],
                }),
                stderr="",
            ),
            # Show commits
            CompletedProcess(
                args=["but", "branch", "show", "stack", "-j"],
                returncode=0,
                stdout=json.dumps([
                    {
                        "cliId": "c1",
                        "commitId": "abc",
                        "message": "First commit",
                        "authorName": "User",
                        "authorEmail": "user@test.com",
                        "createdAt": "2025-01-01T00:00:00Z",
                    },
                    {
                        "cliId": "c2",
                        "commitId": "def",
                        "message": "Second commit",
                        "authorName": "User",
                        "authorEmail": "user@test.com",
                        "createdAt": "2025-01-02T00:00:00Z",
                    },
                ]),
                stderr="",
            ),
        ]

        service = GitButlerService(project_root="/test")
        commits = service.get_stack_commits("stack")

        assert len(commits) == 2
        assert commits[0].message == "First commit"
        assert commits[1].message == "Second commit"

    @patch("services.gitbutler._run_but")
    def test_get_stack_commits_not_found(self, mock_run):
        """Test getting commits from non-existent stack."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
            stderr="",
        )

        service = GitButlerService(project_root="/test")

        with pytest.raises(StackNotFoundError):
            service.get_stack_commits("nonexistent")


class TestGitButlerServiceListStacks:
    """Tests for GitButlerService.list_stacks."""

    @patch("services.gitbutler._run_but")
    def test_list_stacks(self, mock_run):
        """Test listing all stacks."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({
                "stacks": [
                    {
                        "cliId": "s1",
                        "assignedChanges": [],
                        "branches": [{"name": "stack-1", "cliId": "s1", "commits": []}],
                    },
                    {
                        "cliId": "s2",
                        "assignedChanges": [],
                        "branches": [{"name": "stack-2", "cliId": "s2", "commits": []}],
                    },
                ],
                "unassignedChanges": [],
            }),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        stacks = service.list_stacks()

        assert len(stacks) == 2
        assert stacks[0].name == "stack-1"
        assert stacks[1].name == "stack-2"

    @patch("services.gitbutler._run_but")
    def test_list_stacks_empty(self, mock_run):
        """Test listing when no stacks exist."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        stacks = service.list_stacks()

        assert stacks == []

    @patch("services.gitbutler._run_but")
    def test_list_stacks_on_error(self, mock_run):
        """Test listing stacks returns empty on error."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=1,
            stdout="",
            stderr="error",
        )

        service = GitButlerService(project_root="/test")
        stacks = service.list_stacks()

        assert stacks == []


class TestGitButlerServiceGetStackByName:
    """Tests for GitButlerService.get_stack_by_name."""

    @patch("services.gitbutler._run_but")
    def test_get_stack_by_name_found(self, mock_run):
        """Test getting stack by name when it exists."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({
                "stacks": [
                    {"cliId": "s1", "assignedChanges": [], "branches": [{"name": "target", "cliId": "s1", "commits": []}]},
                    {"cliId": "s2", "assignedChanges": [], "branches": [{"name": "other", "cliId": "s2", "commits": []}]},
                ],
                "unassignedChanges": [],
            }),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        stack = service.get_stack_by_name("target")

        assert stack is not None
        assert stack.name == "target"
        assert stack.cli_id == "s1"

    @patch("services.gitbutler._run_but")
    def test_get_stack_by_name_not_found(self, mock_run):
        """Test getting stack by name when it doesn't exist."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        stack = service.get_stack_by_name("nonexistent")

        assert stack is None


class TestGitButlerHooks:
    """Tests for GitButler Claude Code hooks integration."""

    @patch("services.gitbutler.subprocess.run")
    def test_call_pre_tool_hook_success(self, mock_run):
        """Test calling pre-tool hook successfully."""
        mock_run.return_value = CompletedProcess(
            args=["but", "claude", "pre-tool", "-j"],
            returncode=0,
            stdout='{"continue":true,"stopReason":"","suppressOutput":true}',
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        result = service.call_pre_tool_hook(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            file_path="/test/file.py",
            transcript_path="/tmp/transcript.json",
            tool_name="Edit",
        )

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args.kwargs["input"] is not None

        # Verify hook input JSON structure
        hook_input = json.loads(call_args.kwargs["input"])
        assert hook_input["session_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert hook_input["hook_event_name"] == "PreToolUse"
        assert hook_input["tool_name"] == "Edit"
        assert hook_input["tool_input"]["file_path"] == "/test/file.py"

    @patch("services.gitbutler.subprocess.run")
    def test_call_pre_tool_hook_failure(self, mock_run):
        """Test pre-tool hook failure handling."""
        mock_run.return_value = CompletedProcess(
            args=["but", "claude", "pre-tool", "-j"],
            returncode=1,
            stdout="",
            stderr="Hook failed",
        )

        service = GitButlerService(project_root="/test")
        result = service.call_pre_tool_hook(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            file_path="/test/file.py",
            transcript_path="/tmp/transcript.json",
        )

        assert result is False

    @patch("services.gitbutler.subprocess.run")
    def test_call_post_tool_hook_success(self, mock_run):
        """Test calling post-tool hook successfully."""
        mock_run.return_value = CompletedProcess(
            args=["but", "claude", "post-tool", "-j"],
            returncode=0,
            stdout='{"continue":true,"stopReason":"","suppressOutput":true}',
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        result = service.call_post_tool_hook(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            file_path="/test/file.py",
            transcript_path="/tmp/transcript.json",
            tool_name="Write",
        )

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args

        # Verify hook input JSON structure
        hook_input = json.loads(call_args.kwargs["input"])
        assert hook_input["session_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert hook_input["hook_event_name"] == "PostToolUse"
        assert hook_input["tool_name"] == "Write"
        assert hook_input["tool_response"]["filePath"] == "/test/file.py"
        assert hook_input["tool_response"]["structuredPatch"] == []

    @patch("services.gitbutler.subprocess.run")
    def test_call_post_tool_hook_failure(self, mock_run):
        """Test post-tool hook failure handling."""
        mock_run.return_value = CompletedProcess(
            args=["but", "claude", "post-tool", "-j"],
            returncode=1,
            stdout="",
            stderr="Invalid JSON",
        )

        service = GitButlerService(project_root="/test")
        result = service.call_post_tool_hook(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            file_path="/test/file.py",
            transcript_path="/tmp/transcript.json",
        )

        assert result is False

    @patch("services.gitbutler.subprocess.run")
    def test_call_stop_hook_success(self, mock_run):
        """Test calling stop hook successfully."""
        mock_run.return_value = CompletedProcess(
            args=["but", "claude", "stop", "-j"],
            returncode=0,
            stdout='{"continue":true,"stopReason":"","suppressOutput":true}',
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        result = service.call_stop_hook(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            transcript_path="/tmp/transcript.json",
        )

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args

        # Verify hook input JSON structure
        hook_input = json.loads(call_args.kwargs["input"])
        assert hook_input["session_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert hook_input["hook_event_name"] == "SessionEnd"
        assert hook_input["transcript_path"] == "/tmp/transcript.json"

    @patch("services.gitbutler.subprocess.run")
    def test_call_stop_hook_failure(self, mock_run):
        """Test stop hook failure handling."""
        mock_run.return_value = CompletedProcess(
            args=["but", "claude", "stop", "-j"],
            returncode=1,
            stdout="",
            stderr="Transcript not found",
        )

        service = GitButlerService(project_root="/test")
        result = service.call_stop_hook(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            transcript_path="/tmp/transcript.json",
        )

        assert result is False

    @patch("services.gitbutler.subprocess.run")
    def test_discover_stack_for_session_success(self, mock_run):
        """Test discovering auto-created stack after first edit."""
        status_json = {
            "stacks": [
                {
                    "cliId": "u0",
                    "assignedChanges": [
                        {"cliId": "c1", "filePath": "/test/file.py", "changeType": "modified"}
                    ],
                    "branches": [
                        {
                            "cliId": "u0",
                            "name": "zl-branch-15",
                            "commits": [],
                        }
                    ],
                }
            ],
            "unassignedChanges": [],
        }

        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps(status_json),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        result = service.discover_stack_for_session(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            edited_file="/test/file.py",
        )

        assert result is not None
        stack_name, stack_cli_id = result
        assert stack_name == "zl-branch-15"
        assert stack_cli_id == "u0"

    @patch("services.gitbutler.subprocess.run")
    def test_discover_stack_for_session_not_found(self, mock_run):
        """Test when stack discovery fails."""
        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps({"stacks": [], "unassignedChanges": []}),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        result = service.discover_stack_for_session(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            edited_file="/test/file.py",
        )

        assert result is None

    @patch("services.gitbutler.subprocess.run")
    def test_discover_stack_ignores_non_auto_stacks(self, mock_run):
        """Test that discovery only looks at auto-created zl-branch-* stacks."""
        status_json = {
            "stacks": [
                {
                    "cliId": "tm",
                    "assignedChanges": [
                        {"cliId": "c1", "filePath": "/test/file.py", "changeType": "modified"}
                    ],
                    "branches": [
                        {
                            "cliId": "tm",
                            "name": "task-1-feature",  # Not a zl-branch-*
                            "commits": [],
                        }
                    ],
                }
            ],
            "unassignedChanges": [],
        }

        mock_run.return_value = CompletedProcess(
            args=["but", "status", "-j"],
            returncode=0,
            stdout=json.dumps(status_json),
            stderr="",
        )

        service = GitButlerService(project_root="/test")
        result = service.discover_stack_for_session(
            session_id="550e8400-e29b-41d4-a716-446655440000",
            edited_file="/test/file.py",
        )

        # Should not find task-1-feature, only zl-branch-* stacks
        assert result is None

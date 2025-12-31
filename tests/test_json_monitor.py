"""Tests for JSON monitor service with GitButler hooks integration."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from uuid import UUID
from sqlmodel import Session, create_engine, SQLModel

from models import Task, TaskStatus, ClaudeStatus
from services.json_monitor import JsonMonitor
from services.json_parser import JsonEventParser, ClaudeJsonEvent
from services.tmux import TmuxService
from services.gitbutler import GitButlerService


# Test UUID constant
TEST_TASK_ID = UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def db():
    """Create an in-memory database for testing."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def mock_tmux():
    """Create a mock TmuxService."""
    return Mock(spec=TmuxService)


@pytest.fixture
def mock_gitbutler():
    """Create a mock GitButlerService."""
    mock = Mock(spec=GitButlerService)
    # Setup discover_stack_for_session to return stack info
    mock.discover_stack_for_session.return_value = ("test-stack", "s0")
    return mock


@pytest.fixture
def json_parser():
    """Create a real JsonEventParser."""
    return JsonEventParser()


@pytest.fixture
def monitor(db, mock_tmux, mock_gitbutler, json_parser):
    """Create a JsonMonitor instance."""
    return JsonMonitor(
        db=db,
        tmux=mock_tmux,
        gitbutler=mock_gitbutler,
        json_parser=json_parser,
        poll_interval=0.1,
    )


@pytest.mark.asyncio
async def test_handle_session_start_event(db, monitor):
    """Test handling session_start event."""
    # Create a task
    task = Task(
        id=TEST_TASK_ID,
        title="Test Task",
        status=TaskStatus.running,
        stack_name="test-stack",
    )
    db.add(task)
    db.commit()

    # Create session_start event
    event = ClaudeJsonEvent(
        event_type="session_start",
        data={"type": "session_start", "session_id": "abc123"},
        session_id="abc123",
    )

    # Handle event
    await monitor._handle_event(TEST_TASK_ID, event)

    # Check task was updated
    db.refresh(task)
    assert task.claude_session_id == "abc123"
    assert task.claude_status == ClaudeStatus.idle


@pytest.mark.asyncio
async def test_handle_tool_use_event(db, monitor):
    """Test handling tool_use event."""
    # Create a task
    task = Task(
        id=1,
        title="Test Task",
        status=TaskStatus.running,
        claude_status=ClaudeStatus.idle,
    )
    db.add(task)
    db.commit()

    # Create tool_use event
    event = ClaudeJsonEvent(
        event_type="tool_use",
        data={"type": "tool_use", "tool": "Read"},
    )

    # Handle event
    await monitor._handle_event(1, event)

    # Check task status updated to busy
    db.refresh(task)
    assert task.claude_status == ClaudeStatus.busy


@pytest.mark.asyncio
async def test_handle_tool_result_file_edit(db, monitor, mock_gitbutler):
    """Test handling tool_result for file edit triggers GitButler commit."""
    # Create a task
    task = Task(
        id=1,
        title="Test Task",
        status=TaskStatus.running,
        stack_name="test-stack",
        claude_status=ClaudeStatus.busy,
    )
    db.add(task)
    db.commit()

    # Create tool_result event for file edit
    event = ClaudeJsonEvent(
        event_type="tool_result",
        data={"type": "tool_result", "tool": "Edit", "status": "success"},
    )

    # Handle event
    await monitor._handle_event(1, event)

    # Check GitButler commit was called
    mock_gitbutler.commit_to_stack.assert_called_once_with("test-stack")

    # Check task status updated to idle
    db.refresh(task)
    assert task.claude_status == ClaudeStatus.idle


@pytest.mark.asyncio
async def test_handle_tool_result_no_commit_for_non_edit(db, monitor, mock_gitbutler):
    """Test tool_result for non-edit tools doesn't trigger commit."""
    # Create a task
    task = Task(
        id=1,
        title="Test Task",
        status=TaskStatus.running,
        stack_name="test-stack",
    )
    db.add(task)
    db.commit()

    # Create tool_result event for non-edit tool
    event = ClaudeJsonEvent(
        event_type="tool_result",
        data={"type": "tool_result", "tool": "Read", "status": "success"},
    )

    # Handle event
    await monitor._handle_event(1, event)

    # Check GitButler commit was NOT called
    mock_gitbutler.commit_to_stack.assert_not_called()


@pytest.mark.asyncio
async def test_handle_result_event(db, monitor):
    """Test handling result event."""
    # Create a task
    task = Task(
        id=1,
        title="Test Task",
        status=TaskStatus.running,
    )
    db.add(task)
    db.commit()

    # Create result event
    event = ClaudeJsonEvent(
        event_type="result",
        data={"type": "result", "session_id": "xyz789"},
        session_id="xyz789",
    )

    # Handle event
    await monitor._handle_event(1, event)

    # Check session_id was stored
    db.refresh(task)
    assert task.json_session_id == "xyz789"
    assert task.claude_status == ClaudeStatus.idle


@pytest.mark.asyncio
async def test_handle_permission_request_event(db, monitor):
    """Test handling permission_request event."""
    # Create a task
    task = Task(
        id=1,
        title="Test Task",
        status=TaskStatus.running,
        claude_status=ClaudeStatus.busy,
    )
    db.add(task)
    db.commit()

    # Create permission_request event
    event = ClaudeJsonEvent(
        event_type="permission_request",
        data={"type": "permission_request"},
    )

    # Handle event
    await monitor._handle_event(1, event)

    # Check status updated to waiting
    db.refresh(task)
    assert task.claude_status == ClaudeStatus.waiting


@pytest.mark.asyncio
async def test_handle_unknown_event(db, monitor):
    """Test handling unknown event type doesn't crash."""
    # Create a task
    task = Task(
        id=1,
        title="Test Task",
        status=TaskStatus.running,
    )
    db.add(task)
    db.commit()

    # Create unknown event
    event = ClaudeJsonEvent(
        event_type="unknown_type",
        data={"type": "unknown_type"},
    )

    # Handle event - should not crash
    await monitor._handle_event(1, event)

    # Task should be unchanged
    db.refresh(task)
    assert task.claude_status == ClaudeStatus.stopped


@pytest.mark.asyncio
async def test_monitor_parses_json_output(db, monitor, mock_tmux):
    """Test that monitor correctly parses JSON from tmux output."""
    # Create a task
    task = Task(
        id=1,
        title="Test Task",
        status=TaskStatus.running,
    )
    db.add(task)
    db.commit()

    # Mock tmux output with JSON events
    json_output = '''
{"type": "session_start", "session_id": "test123"}
{"type": "tool_use", "tool": "Bash"}
{"type": "tool_result", "tool": "Bash", "status": "success"}
'''
    mock_tmux.capture_json_events.return_value = json_output

    # Manually process the output (simulates one monitor cycle)
    output = mock_tmux.capture_json_events(1)
    events = monitor.json_parser.parse_output(output)

    # Process each event
    for event in events:
        await monitor._handle_event(1, event)

    # Check that events were processed
    db.refresh(task)
    assert task.json_session_id == "test123"
    assert task.claude_status == ClaudeStatus.idle


@pytest.mark.asyncio
async def test_monitor_handles_empty_output(db, monitor, mock_tmux):
    """Test that monitor handles empty tmux output gracefully."""
    # Create a task
    task = Task(
        id=TEST_TASK_ID,
        title="Test Task",
        status=TaskStatus.running,
    )
    db.add(task)
    db.commit()

    # Mock empty tmux output
    mock_tmux.capture_json_events.return_value = ""

    # Create monitor task
    monitor_task = monitor._monitor_task(TEST_TASK_ID)

    # Run one iteration
    import asyncio
    try:
        await asyncio.wait_for(asyncio.shield(monitor_task), timeout=0.2)
    except asyncio.TimeoutError:
        monitor_task.cancel()

    # Task should be unchanged
    db.refresh(task)
    assert task.claude_session_id is None


# Hook Integration Tests


@pytest.mark.asyncio
async def test_hook_integration_pre_tool_on_edit(db, monitor, mock_gitbutler, monkeypatch):
    """Test that pre_tool_hook is called on Edit tool_use."""
    from pathlib import Path

    # Setup - mock get_transcript_dir
    monkeypatch.setattr("services.json_monitor.get_transcript_dir", lambda x: Path("/tmp/test-transcript"))

    task = Task(
        id=TEST_TASK_ID,
        title="Test Task",
        status=TaskStatus.running,
    )
    db.add(task)
    db.commit()

    # Create tool_use event for Edit
    event = ClaudeJsonEvent(
        event_type="tool_use",
        data={
            "type": "tool_use",
            "id": "tool_123",
            "toolName": "Edit",
            "toolInput": {"file_path": "/test/file.py"}
        },
    )

    # Handle event
    await monitor._handle_event(TEST_TASK_ID, event)

    # Verify pre_tool_hook was called
    mock_gitbutler.call_pre_tool_hook.assert_called_once()
    call_args = mock_gitbutler.call_pre_tool_hook.call_args
    assert call_args[1]["session_id"] == str(TEST_TASK_ID)
    assert call_args[1]["file_path"] == "/test/file.py"
    assert call_args[1]["tool_name"] == "Edit"


@pytest.mark.asyncio
async def test_hook_integration_post_tool_and_commit(db, monitor, mock_gitbutler, monkeypatch):
    """Test that post_tool_hook is called and stack is committed on successful edit."""
    from pathlib import Path

    # Setup - mock get_transcript_dir
    monkeypatch.setattr("services.json_monitor.get_transcript_dir", lambda x: Path("/tmp/test-transcript"))

    task = Task(
        id=TEST_TASK_ID,
        title="Test Task",
        status=TaskStatus.running,
        stack_name="test-stack",
    )
    db.add(task)
    db.commit()

    # First, handle tool_use to store it
    tool_use_event = ClaudeJsonEvent(
        event_type="tool_use",
        data={
            "type": "tool_use",
            "id": "tool_123",
            "toolName": "Write",
            "toolInput": {"file_path": "/test/new_file.py"}
        },
    )
    await monitor._handle_event(TEST_TASK_ID, tool_use_event)

    # Then handle tool_result
    tool_result_event = ClaudeJsonEvent(
        event_type="tool_result",
        data={
            "type": "tool_result",
            "toolUseId": "tool_123",
            "isError": False
        },
    )
    await monitor._handle_event(TEST_TASK_ID, tool_result_event)

    # Verify post_tool_hook was called
    mock_gitbutler.call_post_tool_hook.assert_called_once()

    # Verify commit_to_stack was called
    mock_gitbutler.commit_to_stack.assert_called_once_with("test-stack")


@pytest.mark.asyncio
async def test_hook_integration_stack_discovery_on_first_edit(db, monitor, mock_gitbutler, monkeypatch):
    """Test that stack is discovered and saved on first successful edit."""
    from pathlib import Path

    # Setup - mock get_transcript_dir
    monkeypatch.setattr("services.json_monitor.get_transcript_dir", lambda x: Path("/tmp/test-transcript"))
    mock_gitbutler.discover_stack_for_session.return_value = ("discovered-stack", "s5")

    task = Task(
        id=TEST_TASK_ID,
        title="Test Task",
        status=TaskStatus.running,
        stack_name=None,  # No stack yet
    )
    db.add(task)
    db.commit()

    # Handle tool_use
    tool_use_event = ClaudeJsonEvent(
        event_type="tool_use",
        data={
            "type": "tool_use",
            "id": "tool_456",
            "toolName": "Edit",
            "toolInput": {"file_path": "/test/file.py"}
        },
    )
    await monitor._handle_event(TEST_TASK_ID, tool_use_event)

    # Handle successful tool_result
    tool_result_event = ClaudeJsonEvent(
        event_type="tool_result",
        data={
            "type": "tool_result",
            "toolUseId": "tool_456",
            "isError": False
        },
    )
    await monitor._handle_event(TEST_TASK_ID, tool_result_event)

    # Verify discover_stack_for_session was called
    mock_gitbutler.discover_stack_for_session.assert_called_once()

    # Verify stack was saved to task
    db.refresh(task)
    assert task.stack_name == "discovered-stack"
    assert task.stack_cli_id == "s5"

    # Verify commit was made to discovered stack
    mock_gitbutler.commit_to_stack.assert_called_once_with("discovered-stack")


@pytest.mark.asyncio
async def test_hook_integration_no_hooks_for_read_tools(db, monitor, mock_gitbutler):
    """Test that hooks are NOT called for Read/Grep/Glob tools."""
    task = Task(
        id=TEST_TASK_ID,
        title="Test Task",
        status=TaskStatus.running,
    )
    db.add(task)
    db.commit()

    # Handle Read tool_use
    event = ClaudeJsonEvent(
        event_type="tool_use",
        data={
            "type": "tool_use",
            "id": "tool_789",
            "toolName": "Read",
            "toolInput": {"file_path": "/test/file.py"}
        },
    )
    await monitor._handle_event(TEST_TASK_ID, event)

    # Verify pre_tool_hook was NOT called
    mock_gitbutler.call_pre_tool_hook.assert_not_called()


@pytest.mark.asyncio
async def test_extract_claude_session_id_from_result_event(db, monitor):
    """Test that Claude session_id is extracted from result event for --resume."""
    task = Task(
        id=TEST_TASK_ID,
        title="Test Task",
        status=TaskStatus.running,
        claude_session_id=None,
    )
    db.add(task)
    db.commit()

    # Create result event with sessionId
    event = ClaudeJsonEvent(
        event_type="result",
        data={
            "type": "result",
            "sessionId": "claude-session-xyz"
        },
    )

    await monitor._handle_event(TEST_TASK_ID, event)

    # Verify claude_session_id was stored
    db.refresh(task)
    assert task.claude_session_id == "claude-session-xyz"

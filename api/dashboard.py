"""Dashboard routes for htmx partials.

These endpoints return HTML fragments for htmx to swap into the page.
"""

from typing import Optional
from uuid import UUID

import markdown
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from database import get_db
from models import Task, TaskStatus
from services.tmux import TmuxService, SessionNotFoundError

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="templates")

# Add custom Jinja filters
import json
templates.env.filters["from_json"] = lambda s: json.loads(s) if s else []


def _render_task_with_oob(request: Request, task: Task) -> HTMLResponse:
    """Render task detail with out-of-band task list item update."""
    # Check if tmux session exists for running/waiting tasks
    tmux_session_exists = False
    if task.status in (TaskStatus.running, TaskStatus.waiting):
        tmux = TmuxService()
        tmux_session_exists = tmux.session_exists(task.id)

    detail_html = templates.get_template("partials/task_detail.html").render(
        request=request, task=task, tmux_session_exists=tmux_session_exists
    )
    item_html = templates.get_template("partials/task_item.html").render(
        request=request, task=task
    )
    # Add hx-swap-oob to the task item for out-of-band swap
    oob_item = item_html.replace(
        f'id="task-{task.id}"',
        f'id="task-{task.id}" hx-swap-oob="true"'
    )
    return HTMLResponse(detail_html + oob_item)


@router.get("/tasks", response_class=HTMLResponse)
async def get_task_list(
    request: Request,
    status: Optional[TaskStatus] = None,
    db: Session = Depends(get_db),
):
    """Get task list as HTML partial."""
    statement = select(Task)
    if status:
        statement = statement.where(Task.status == status)
    statement = statement.order_by(Task.priority.desc(), Task.created_at.desc())
    tasks = list(db.exec(statement).all())

    return templates.TemplateResponse(
        request, "partials/task_list.html", {"tasks": tasks}
    )


@router.post("/tasks", response_class=HTMLResponse)
async def create_task(
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a task from form data and return task item HTML."""
    form = await request.form()
    title = form.get("title", "").strip()

    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    task = Task(title=title)
    db.add(task)
    db.commit()
    db.refresh(task)

    return templates.TemplateResponse(
        request, "partials/task_item.html", {"task": task}
    )


@router.delete("/tasks/{task_id}", response_class=HTMLResponse)
async def delete_task(
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Delete a task and return HTML to clear task item and detail panel."""
    from api.tasks import delete_task as api_delete_task

    try:
        await api_delete_task(task_id, db)
    except HTTPException:
        raise

    # Return empty content for the task item (removes it) plus OOB to clear detail
    empty_detail = '''<div class="panel-header" hx-swap-oob="innerHTML:#task-detail">Task Detail</div>
<p class="muted" hx-swap-oob="true" id="task-detail-placeholder">Select a task to view details</p>'''
    return HTMLResponse(empty_detail)


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def get_task_detail(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Get task detail as HTML partial with OOB task list update."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Return detail with OOB swap for task list item
    return _render_task_with_oob(request, task)


@router.get("/tasks/{task_id}/output", response_class=HTMLResponse)
async def get_task_output(
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Get formatted JSON output."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in (TaskStatus.running, TaskStatus.waiting):
        return HTMLResponse("<pre class='muted'>No active session</pre>")

    # Get raw output from tmux and format as JSON
    from services.tmux import TmuxService
    from services.json_parser import JsonEventParser
    import json
    import html

    tmux = TmuxService()
    try:
        raw_output = tmux.capture_json_events(task_id)
        if not raw_output:
            return HTMLResponse("<pre>Waiting for output...</pre>")

        # Use the JSON parser to handle line-wrapped events
        parser = JsonEventParser()
        events = parser.parse_output(raw_output)

        if not events:
            return HTMLResponse('<div class="no-events">Waiting for output...</div>')

        # Extract tool_use blocks from assistant messages and tool_result blocks from user messages
        tool_use_blocks = {}  # tool_id -> (assistant_event, tool_use_block)
        tool_result_blocks = {}  # tool_use_id -> (user_event, tool_result_block)

        for event in events:
            event_type = event.data.get('type')

            # Extract tool_use blocks from assistant messages
            if event_type == 'assistant':
                msg = event.data.get('message', {})
                content = msg.get('content', [])
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        tool_id = block.get('id')
                        if tool_id:
                            tool_use_blocks[tool_id] = (event, block)

            # Extract tool_result blocks from user messages
            elif event_type == 'user':
                msg = event.data.get('message', {})
                content = msg.get('content', [])
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        tool_use_id = block.get('tool_use_id')
                        if tool_use_id:
                            tool_result_blocks[tool_use_id] = (event, block)

        # Create paired events
        paired_events = []
        processed_user_events = set()  # Track which user events we've processed as tool results

        for i, event in enumerate(events):
            event_type = event.data.get('type')

            # For assistant events, check if any tool_use blocks have matching results
            if event_type == 'assistant':
                msg = event.data.get('message', {})
                content = msg.get('content', [])

                # Separate tool_use blocks from other content
                tool_uses_in_msg = []
                has_other_content = False

                for block in content:
                    if isinstance(block, dict):
                        if block.get('type') == 'tool_use':
                            tool_uses_in_msg.append(block)
                        else:
                            has_other_content = True

                # If this assistant message has tool_use blocks, create combined entries
                for tool_use_block in tool_uses_in_msg:
                    tool_id = tool_use_block.get('id')
                    if tool_id and tool_id in tool_result_blocks:
                        result_event, result_block = tool_result_blocks[tool_id]
                        # Create a combined tool execution entry
                        paired_events.append(('tool_pair', event, result_event, tool_use_block, result_block))
                        processed_user_events.add(id(result_event))

                # If assistant has other content besides tool_use, add it as regular event
                if has_other_content or not tool_uses_in_msg:
                    paired_events.append((event_type, event, None, None, None))

            # For user events, only add if not already processed as a tool_result
            elif event_type == 'user':
                if id(event) not in processed_user_events:
                    paired_events.append((event_type, event, None, None, None))

            # All other events
            else:
                paired_events.append((event_type, event, None, None, None))

        # Render events using template
        html_output = ""
        for event_tuple in paired_events:
            event_type_tuple, event, result_event, tool_use_block, tool_result_block = event_tuple
            event_data = event.data

            # Handle tool_pair specially
            if event_type_tuple == 'tool_pair':
                # Combined tool_use + tool_result from message blocks
                tool_name = tool_use_block.get('name', 'Unknown')
                tool_input = tool_use_block.get('input', {})
                is_error = tool_result_block.get('is_error', False)
                result_content = tool_result_block.get('content', '')

                # Build summary
                summary_html = f'<span class="event-type">tool_execution</span>'
                summary_html += '<span class="event-details">'
                summary_html += f'<strong>{html.escape(tool_name)}</strong> '

                # Show key input details
                if 'file_path' in tool_input:
                    summary_html += f'→ {html.escape(tool_input["file_path"])} '
                elif 'command' in tool_input:
                    cmd = tool_input['command'][:40]
                    summary_html += f'→ <code>{html.escape(cmd)}...</code> '

                # Show result status
                if is_error:
                    summary_html += '<span class="error-badge">ERROR</span>'
                else:
                    summary_html += '<span class="success-badge">SUCCESS</span>'

                # Show brief result preview
                if result_content:
                    if isinstance(result_content, str):
                        preview = result_content[:80]
                        summary_html += f' <span style="color: var(--text-secondary); font-size: 0.8rem;">{html.escape(preview)}{"..." if len(result_content) > 80 else ""}</span>'

                summary_html += '</span><span class="expand-icon">▶</span>'

                # Full JSON data - combine both blocks
                combined_json = {
                    "tool_use": tool_use_block,
                    "tool_result": tool_result_block
                }
                full_json = json.dumps(combined_json, indent=2)

                html_output += f'''
                <div class="json-event event-tool_execution" onclick="this.classList.toggle('expanded')">
                    <div class="event-summary">
                        {summary_html}
                    </div>
                    <div class="event-full-data">
                        <pre>{html.escape(full_json)}</pre>
                    </div>
                </div>
                '''
                continue

            # Regular event rendering
            # For paired events, use tuple type; otherwise use data type
            event_type = event_type_tuple if event_type_tuple in ['tool_use', 'tool_result'] else event_data.get('type', event_type_tuple)

            # Build summary based on event type
            summary_html = f'<span class="event-type">{event_type}</span>'
            summary_html += '<span class="event-details">'

            if event_type == 'session_start':
                session_id = event_data.get('session_id', 'N/A')
                summary_html += f'Session: {session_id[:16] if session_id else "N/A"}...'
            elif event_type == 'user':
                msg = event_data.get('message', {})
                content = msg.get('content', [])

                # Check for text, tool_use, and tool_result blocks
                text_parts = []
                tool_uses = []
                tool_results = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get('type') == 'text':
                            text_parts.append(block.get('text', ''))
                        elif block.get('type') == 'tool_use':
                            tool_uses.append(block.get('name', 'tool'))
                        elif block.get('type') == 'tool_result':
                            tool_use_id = block.get('tool_use_id', 'unknown')
                            is_error = block.get('is_error', False)
                            tool_results.append((tool_use_id, is_error, block.get('content', '')))

                # If this is a tool_result message, render it specially
                if tool_results and not text_parts:
                    for tool_use_id, is_error, result_content in tool_results:
                        if is_error:
                            summary_html += '<span class="error-badge">TOOL ERROR</span> '
                        else:
                            summary_html += '<span class="success-badge">TOOL SUCCESS</span> '

                        # Show brief preview
                        if isinstance(result_content, str):
                            preview = result_content[:80]
                            summary_html += f'{html.escape(preview)}{"..." if len(result_content) > 80 else ""}'
                else:
                    # Show text preview
                    if text_parts:
                        combined = ' '.join(text_parts)
                        preview = combined[:100]
                        summary_html += f'{html.escape(preview)}{"..." if len(combined) > 100 else ""}'
                    else:
                        summary_html += 'User input'

                    # Indicate tool uses if present
                    if tool_uses:
                        summary_html += f' <em style="color: var(--accent-yellow);">[Uses: {", ".join(tool_uses)}]</em>'
            elif event_type == 'tool_use':
                tool_name = event_data.get('toolName', 'Unknown')
                tool_input = event_data.get('toolInput', {})
                summary_html += f'<strong>{html.escape(tool_name)}</strong> '
                if 'file_path' in tool_input:
                    summary_html += f'→ {html.escape(tool_input["file_path"])}'
                elif 'command' in tool_input:
                    cmd = tool_input['command'][:40]
                    summary_html += f'→ <code>{html.escape(cmd)}...</code>'
            elif event_type == 'tool_result':
                is_error = event_data.get('isError', False)
                if is_error:
                    summary_html += '<span class="error-badge">ERROR</span>'
                else:
                    summary_html += '<span class="success-badge">SUCCESS</span>'
            elif event_type == 'text':
                text = event_data.get('text', '')
                # Show all text for streaming assistant messages
                summary_html += f'<div style="white-space: pre-wrap; max-width: 800px;">{html.escape(text)}</div>'
            elif event_type == 'assistant':
                msg = event_data.get('message', {})
                content = msg.get('content', [])

                # Extract text from content blocks
                text_parts = []
                tool_uses = []
                for block in content:
                    if block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                    elif block.get('type') == 'tool_use':
                        tool_uses.append(block.get('name', 'tool'))

                # Combine text and show first ~200 chars (roughly 3 lines)
                combined_text = ' '.join(text_parts)
                if combined_text:
                    preview = combined_text[:200]
                    # Add line breaks for readability
                    summary_html += f'<div style="white-space: pre-wrap; max-width: 600px;">{html.escape(preview)}{"..." if len(combined_text) > 200 else ""}</div>'

                # Show tool uses if any
                if tool_uses:
                    summary_html += f'<div style="margin-top: 0.25rem;"><em>Uses: {", ".join(tool_uses)}</em></div>'

                if not combined_text and not tool_uses:
                    summary_html += f'Assistant response ({len(content)} blocks)'
            elif event_type == 'result':
                usage = event_data.get('usage', {})
                if usage:
                    inp = usage.get('input_tokens', 0)
                    out = usage.get('output_tokens', 0)
                    summary_html += f'Tokens: {inp}in / {out}out'
                else:
                    summary_html += 'Completed'
            elif event_type == 'permission_request':
                prompt = event_data.get('prompt', '')[:50]
                summary_html += f'⚠️ {html.escape(prompt)}...'
            elif event_type == 'error':
                err = event_data.get('error', {})
                err_type = err.get('type', 'unknown')
                err_msg = err.get('message', '')[:40]
                summary_html += f'<span class="error-badge">{html.escape(err_type)}</span> {html.escape(err_msg)}...'

            summary_html += '</span>'
            summary_html += '<span class="expand-icon">▶</span>'

            # Full data - special handling for text events
            if event_type == 'text':
                # For text events, render the text as markdown instead of JSON
                text = event_data.get('text', '')
                rendered_html = markdown.markdown(text, extensions=['fenced_code', 'tables'])
                full_data_html = f'<div class="markdown-content">{rendered_html}</div>'
            else:
                # For other events, show full JSON
                full_json = json.dumps(event_data, indent=2)
                full_data_html = f'<pre>{html.escape(full_json)}</pre>'

            html_output += f'''
            <div class="json-event event-{event_type}" onclick="this.classList.toggle('expanded')">
                <div class="event-summary">
                    {summary_html}
                </div>
                <div class="event-full-data">
                    {full_data_html}
                </div>
            </div>
            '''

    except Exception as e:
        return HTMLResponse(f'<div class="no-events">Error: {html.escape(str(e))}</div>')

    return HTMLResponse(html_output)


@router.post("/tasks/{task_id}/send", response_class=HTMLResponse)
async def send_message(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Send a message to Claude and return updated output."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    form = await request.form()
    message = form.get("message", "")

    if not message:
        return await get_task_output(task_id, db)

    tmux = TmuxService()
    try:
        tmux.send_keys(task_id, message)
    except SessionNotFoundError:
        return HTMLResponse("<span class='error'>Session not found</span>")

    # Return current output (will update via polling)
    return await get_task_output(task_id, db)


@router.post("/tasks/{task_id}/start", response_class=HTMLResponse)
async def start_task(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Start a task and return updated task detail HTML + OOB task item."""
    from api.tasks import start_task as api_start_task, TaskStartRequest

    # Parse form data to get initial_prompt if provided
    form_data = await request.form()
    initial_prompt = form_data.get("initial_prompt", "").strip() or None

    # Call the API function to do the actual work
    try:
        await api_start_task(task_id, TaskStartRequest(initial_prompt=initial_prompt), db)
    except HTTPException:
        raise

    # Refresh task and return HTML with OOB swap for task list item
    task = db.get(Task, task_id)
    return _render_task_with_oob(request, task)


@router.post("/tasks/{task_id}/restart-claude", response_class=HTMLResponse)
async def restart_claude(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Restart Claude and return updated task detail HTML + OOB task item."""
    from api.tasks import restart_claude as api_restart_claude

    try:
        await api_restart_claude(task_id, db)
    except HTTPException:
        raise

    task = db.get(Task, task_id)
    return _render_task_with_oob(request, task)


@router.post("/tasks/{task_id}/complete", response_class=HTMLResponse)
async def complete_task(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Complete a task and return updated task detail HTML + OOB task item."""
    from api.tasks import complete_task as api_complete_task, TaskCompleteRequest

    try:
        await api_complete_task(task_id, TaskCompleteRequest(), db)
    except HTTPException:
        raise

    task = db.get(Task, task_id)
    return _render_task_with_oob(request, task)


@router.post("/tasks/{task_id}/fail", response_class=HTMLResponse)
async def fail_task(
    request: Request,
    task_id: UUID,
    db: Session = Depends(get_db),
):
    """Fail a task and return updated task detail HTML + OOB task item."""
    from api.tasks import fail_task as api_fail_task, TaskFailRequest

    try:
        await api_fail_task(task_id, TaskFailRequest(), db)
    except HTTPException:
        raise

    task = db.get(Task, task_id)
    return _render_task_with_oob(request, task)


@router.post("/tasks/{task_id}/respond", response_class=HTMLResponse)
async def respond_to_permission(
    request: Request,
    task_id: UUID,
    confirm: bool = True,
    db: Session = Depends(get_db),
):
    """Respond to permission prompt and return updated detail."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    tmux = TmuxService()
    try:
        tmux.send_confirmation(task_id, confirm)
    except SessionNotFoundError:
        pass

    task.permission_prompt = None
    db.add(task)
    db.commit()
    db.refresh(task)

    return _render_task_with_oob(request, task)

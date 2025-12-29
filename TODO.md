# TODO

> Auto-updated by Claude Code. Last update: 2025-12-29 01:32

## In Progress

<!-- Tasks currently being worked on -->

## Up Next

<!-- Priority tasks - Phase 2: Task API + Monitor (tmux focus) -->

### tmux Service (task-centric)
- [ ] Update `services/tmux.py` with task-centric operations
  - [ ] `create_task_session(task_id)` - Create tmux for a task
  - [ ] `start_claude(task_id)` - Launch Claude in task's tmux
  - [ ] `restart_claude(task_id)` - Kill and relaunch Claude
  - [ ] `kill_task_session(task_id)` - Kill task's tmux

### Claude Status Detection
- [ ] Implement `services/detector.py`
  - [ ] `detect_claude_status(output)` → (ClaudeStatus, permission_prompt)
  - [ ] Idle/busy/waiting pattern matching

### GitButler Integration
- [ ] Implement `services/gitbutler.py`
  - [ ] `create_branch(name)` - Create feature branch
  - [ ] `commit_changes(message)` - Commit via update_branches

### Task API
- [ ] Implement `api/tasks.py` - Full task lifecycle
  - [ ] CRUD endpoints (create, list, get, update, delete)
  - [ ] `POST /api/tasks/{id}/start` - Start task
  - [ ] `POST /api/tasks/{id}/restart-claude` - Restart Claude
  - [ ] `POST /api/tasks/{id}/complete` - Complete task
  - [ ] `POST /api/tasks/{id}/fail` - Fail task

### Task Monitor
- [ ] Implement `services/monitor.py` - Async polling loop
- [ ] Implement `api/events.py` - SSE endpoint

## Backlog

<!-- Future tasks -->

### Phase 3: Document API
- [ ] Implement `services/documents.py`
- [ ] Implement `api/documents.py`
- [ ] Document reference endpoints

### Phase 4: Dashboard
- [ ] Task-centric dashboard layout
- [ ] htmx interactions
- [ ] SSE integration

### Phase 5: Polish
- [ ] Error handling
- [ ] Desktop notifications
- [ ] Edge cases
- [ ] Integration tests with tmux

## Completed

<!-- Done tasks, most recent first -->
- [x] Migrate to task-centric architecture (2025-12-29)
- [x] Update all documentation (design.md, CLAUDE.md, PLAN.md)
- [x] Update models.py (remove Session, enhance Task)
- [x] Initial project setup
- [x] Create SQLModel data models
- [x] Implement tmux service wrapper (basic)
- [x] Set up pytest infrastructure
- [x] Create base templates and styling

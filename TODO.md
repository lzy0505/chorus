# TODO

> Auto-updated by Claude Code. Last update: 2025-12-29 16:06

## In Progress

<!-- Tasks currently being worked on -->

## Up Next

<!-- Priority tasks - Phase 2: Task API + Hooks -->

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

### SSE Events
- [ ] Implement `api/events.py` - SSE endpoint for real-time updates

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
- [x] Implement `api/hooks.py` with full test coverage (2025-12-29)
- [x] Implement `services/hooks.py` with full test coverage (2025-12-29)
- [x] Add `claude_session_id` field to Task model (2025-12-29)
- [x] Switch to Claude Code hooks for status detection (2025-12-29)
- [x] Implement task-centric TmuxService with tests (2025-12-29)
- [x] Migrate to task-centric architecture (2025-12-29)
- [x] Update all documentation (design.md, CLAUDE.md, PLAN.md)
- [x] Update models.py (remove Session, enhance Task)
- [x] Initial project setup
- [x] Create SQLModel data models
- [x] Implement tmux service wrapper (basic)
- [x] Set up pytest infrastructure
- [x] Create base templates and styling

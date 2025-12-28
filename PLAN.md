# Implementation Plan

> Reference: See `design.md` for full specification

## Current Phase: Phase 2 - Session API + Monitor

### Phase 1: Core Foundation ✅
- [x] Project structure
- [x] config.py with settings
- [x] SQLModel definitions
- [x] Database setup
- [x] tmux service wrapper

### Phase 2: Session API + Monitor 🔄
- [ ] `services/detector.py` - Status detection patterns
- [ ] `services/notifier.py` - Desktop notifications
- [ ] `api/sessions.py` - Session CRUD endpoints
- [ ] `services/monitor.py` - Async polling loop
- [ ] `api/events.py` - SSE endpoint

### Phase 3: Task API
- [ ] `api/tasks.py` - Task CRUD endpoints
- [ ] Task assignment logic
- [ ] Prompt building with context
- [ ] Sync task status with session status

### Phase 4: Document API
- [ ] `services/documents.py` - Document manager
- [ ] `api/documents.py` - Document endpoints
- [ ] Document reference endpoints
- [ ] Include references in task prompts

### Phase 5: Dashboard
- [ ] `templates/partials/sessions.html`
- [ ] `templates/partials/tasks.html`
- [ ] `templates/partials/documents.html`
- [ ] `templates/partials/viewer.html`
- [ ] htmx interactions
- [ ] SSE integration

### Phase 6: Polish
- [ ] Error handling
- [ ] Edge cases
- [ ] Manual testing checklist
- [ ] Documentation updates

## Notes

<!-- Add implementation notes, decisions, blockers here -->

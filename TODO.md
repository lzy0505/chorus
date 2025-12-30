# TODO

> Auto-updated by Claude Code. Last update: 2025-12-30 20:36

## In Progress

<!-- Tasks currently being worked on -->

## Up Next

<!-- Future enhancements -->

### Phase 5: Polish
- [x] Error handling (2025-12-30)
- [x] Edge cases (2025-12-30)
- [x] Move polling configuration to TOML (2025-12-30)
- [x] Comprehensive logging for debugging external tools (2025-12-30)
- [ ] Desktop notifications
- [ ] Integration tests with tmux

## Completed

<!-- Done tasks, most recent first -->
- [x] Implement robust corner case handling for status detection (2025-12-30)
- [x] Implement hybrid status detection (hooks + polling) (2025-12-30)
- [x] Use Claude CLI native prompt argument for reliable prompt delivery (2025-12-30)
- [x] Auto-send initial prompt to spawned Claude sessions (2025-12-30)
- [x] Inherit global Claude config (~/.claude/) for spawned sessions (2025-12-30)
- [x] Optimize Claude hooks to use shared project-level config (2025-12-30)
- [x] Implement minimal web dashboard with htmx + SSE (2025-12-29)
- [x] Implement `api/tasks.py` with full CRUD and lifecycle endpoints (2025-12-29)
- [x] Implement `POST /api/hooks/posttooluse` for auto-commits (2025-12-29)
- [x] Implement `services/gitbutler.py` with full test coverage (2025-12-29)
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

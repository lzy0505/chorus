# TODO

> Auto-updated by Claude Code. Last update: 2025-12-30 20:37

## In Progress

<!-- Tasks currently being worked on -->

## Up Next

<!-- Future enhancements -->

### Migration to Hybrid Architecture (JSON Monitoring)

**Goal:** Replace hook-based status detection with JSON event parsing while keeping tmux for process isolation.
**Estimated Time:** 8-12 hours over 2-3 days
**Net Code Reduction:** -515 lines (36% smaller codebase)

#### Phase 0: Preparation & Backup (30 min)
1. [ ] Create git branch: `feature/hybrid-json-monitoring`
2. [ ] Document current hook behavior by starting server and capturing logs
3. [ ] Create checkpoint commit before migration

#### Phase 1: Add JSON Parsing Infrastructure (2 hours)
4. [ ] Create `services/json_parser.py` with `ClaudeJsonEvent` and `JsonEventParser`
5. [ ] Create `tests/test_json_parser.py` with unit tests
6. [ ] Add `json_session_id: Optional[str]` field to Task model in `models.py`
7. [ ] Create and apply database migration for `json_session_id` field
8. [ ] Add experimental `start_claude_json_mode()` method to `services/tmux.py`
9. [ ] Add experimental `capture_json_events()` method to `services/tmux.py`
10. [ ] Test JSON mode manually with tmux session

#### Phase 2: Create JSON Monitor Service (2 hours)
11. [ ] Create `services/json_monitor.py` with `JsonMonitor` class
12. [ ] Implement `_monitor_task()` method
13. [ ] Implement event handlers: `session_start`, `tool_use`, `tool_result`, `text`, `result`, `error`
14. [ ] Implement GitButler commit trigger in `tool_result` handler
15. [ ] Create `tests/test_json_monitor.py` with unit tests
16. [ ] Add `MonitoringConfig` class to `config.py` with `use_json_mode` field
17. [ ] Add `[monitoring]` section to `chorus.toml` with `use_json_mode = false`

#### Phase 3: Parallel Testing (2 hours)
18. [ ] Update `main.py` to conditionally start `JsonMonitor` or `StatusPoller` based on feature flag
19. [ ] Test server starts with `use_json_mode = false`
20. [ ] Test server starts with `use_json_mode = true`
21. [ ] Create test task via API with JSON mode enabled
22. [ ] Verify JSON events are parsed from logs
23. [ ] Verify GitButler auto-commit happens after file edits
24. [ ] Verify `json_session_id` is populated in task
25. [ ] Test session resumption with `--resume`
26. [ ] Create `MIGRATION_NOTES.md` documenting differences and test results

#### Phase 4: Cutover (1.5 hours)
27. [ ] Update `api/tasks.py` to use `start_claude_json_mode()` instead of `start_claude()`
28. [ ] Update `send_message()` to build `--resume` command with `json_session_id`
29. [ ] Delete `services/hooks.py` (385 lines)
30. [ ] Delete `api/hooks.py` (342 lines)
31. [ ] Delete `services/status_detector.py` (88 lines)
32. [ ] Remove all `HooksService` and `StatusDetector` imports
33. [ ] Rename `services/json_monitor.py` → `services/monitor.py`
34. [ ] Update all imports from `json_monitor` to `monitor`
35. [ ] Remove feature flag logic from `main.py` (always use Monitor)
36. [ ] Run full test suite and fix any failures

#### Phase 5: Cleanup & Documentation (1 hour)
37. [ ] Update `design.md` - remove hook architecture, add JSON monitoring section
38. [ ] Update `CLAUDE.md` - remove hook setup, update task workflow
39. [ ] Update `PLAN.md` - mark hook phases as removed, add JSON monitoring notes
40. [ ] Update `README.md` - simplify setup (no hooks needed)
41. [ ] Update integration tests for JSON mode
42. [ ] Run full test suite with coverage
43. [ ] Create final commit with detailed migration message
44. [ ] Push branch and create PR

#### Testing Checklist (Before Merge)
- [ ] Basic task creation works
- [ ] Task start launches Claude in JSON mode
- [ ] JSON events parsed correctly from tmux output
- [ ] Tool use detected (Read, Edit, Write, Bash, Grep, Glob)
- [ ] GitButler auto-commit triggers on file edits
- [ ] Session resumption works (`--resume`)
- [ ] Multiple concurrent tasks work
- [ ] Each task commits to its own GitButler stack
- [ ] Task completion cleans up properly
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] MCP servers (lean-lsp, rocq-lsp) still work

### Future Polish (Post-Migration)
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

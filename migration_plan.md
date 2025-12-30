# 📋 Detailed Migration Plan: Hybrid Architecture (tmux + `claude -p` + stream-json)

## Executive Summary

**Goal:** Replace hook-based status detection with JSON event parsing while keeping tmux for process isolation and GitButler for multi-stack support.

**Estimated Total Time:** 8-12 hours (can be done incrementally over 2-3 days)

**Risk Level:** Medium (breaking changes, but with rollback points)

---

## Current vs. Target State

### Current Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ services/tmux.py (386 lines)                                 │
│ └─ start_claude() → Interactive `claude`                    │
│ └─ capture_output() → Get terminal text                     │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ services/hooks.py (385 lines)                                │
│ └─ generate_hooks_config() → .claude/settings.json          │
│ └─ ensure_hooks_config() → /tmp/chorus/hooks/.claude/       │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ api/hooks.py (342 lines)                                     │
│ └─ POST /api/hooks/sessionstart → map session_id to task    │
│ └─ POST /api/hooks/stop → update status to idle             │
│ └─ POST /api/hooks/permissionrequest → status waiting       │
│ └─ POST /api/hooks/posttooluse → commit to GitButler        │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ services/status_poller.py + status_detector.py              │
│ └─ Poll tmux output every 5s                                │
│ └─ Regex pattern matching for status detection              │
│ └─ Safety net for missed hooks                              │
└─────────────────────────────────────────────────────────────┘
```

### Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ services/tmux.py (UPDATED ~300 lines)                        │
│ └─ start_claude() → `claude -p --output-format stream-json` │
│ └─ capture_json_events() → Parse JSON from tmux             │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ services/json_monitor.py (NEW ~200 lines)                    │
│ └─ poll_json_events() → Parse stream-json from tmux         │
│ └─ handle_tool_use() → Detect file edits                    │
│ └─ handle_tool_result() → Trigger GitButler commit          │
│ └─ handle_result() → Extract session_id for resumption      │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ services/gitbutler.py (UNCHANGED)                            │
│ └─ commit_to_stack(stack_name)                              │
└─────────────────────────────────────────────────────────────┘
```

**Files to DELETE:**
- ❌ `services/hooks.py` (385 lines)
- ❌ `api/hooks.py` (342 lines)
- ❌ `services/status_detector.py` (88 lines)

**Files to UPDATE:**
- 🔄 `services/tmux.py` (~100 lines modified)
- 🔄 `services/status_poller.py` (~150 lines modified, renamed to `json_monitor.py`)
- 🔄 `api/tasks.py` (~50 lines modified)
- 🔄 `models.py` (add 1 field)

**Files to ADD:**
- ✅ `services/json_parser.py` (NEW ~100 lines - helper for parsing stream-json)

**Total Code Change:** -815 lines deleted, +300 lines added = **-515 net lines** (36% code reduction)

---

## Phase-by-Phase Migration Plan

### 🔵 Phase 0: Preparation & Backup (30 minutes)

**Goal:** Create safety nets and understand current behavior

#### Step 0.1: Create Git Branch
- [ ] Create new branch: `git checkout -b feature/hybrid-json-monitoring`
- [ ] Stage all current changes: `git add .`
- [ ] Create checkpoint commit: `git commit -m "Checkpoint before hybrid architecture migration"`

#### Step 0.2: Document Current Behavior
- [ ] Start the Chorus server: `uv run python main.py`
- [ ] Create a test task via API
- [ ] Start the test task
- [ ] Capture and document hook events from logs: `tail -f chorus.log | grep "hook"`
- [ ] Document what events fire and when in a notes file
- [ ] Stop the server

**Deliverables:**
- [ ] Git branch created
- [ ] Baseline behavior documented
- [ ] Rollback point established

**Rollback:** `git checkout main`

---

### 🟢 Phase 1: Add JSON Parsing Infrastructure (2 hours)

**Goal:** Add new JSON parsing utilities WITHOUT breaking existing code

#### Step 1.1: Create JSON Parser Helper (30 min)

- [ ] Create new file: `services/json_parser.py`
- [ ] Implement `ClaudeJsonEvent` dataclass
- [ ] Implement `JsonEventParser` class with:
  - [ ] `parse_line(line: str)` method
  - [ ] `parse_output(output: str)` method
- [ ] Create test file: `tests/test_json_parser.py`
- [ ] Write unit tests for JSON parsing
- [ ] Run tests: `uv run pytest tests/test_json_parser.py -v`
- [ ] Fix any failing tests

#### Step 1.2: Update Task Model (15 min)

- [ ] Open `models.py`
- [ ] Add `json_session_id: Optional[str] = Field(default=None)` to `Task` model
- [ ] Create database migration: `alembic revision --autogenerate -m "Add json_session_id to Task"`
- [ ] Review the generated migration file
- [ ] Apply migration: `alembic upgrade head`
- [ ] Verify migration succeeded: `alembic current`

#### Step 1.3: Add Experimental JSON Mode to tmux.py (1 hour)

- [ ] Open `services/tmux.py`
- [ ] Add new method `start_claude_json_mode()` (don't modify existing methods)
- [ ] Add new method `capture_json_events()` (don't modify existing methods)
- [ ] Test JSON mode manually in tmux:
  - [ ] Create test session: `tmux new-session -d -s test-json`
  - [ ] Send JSON command: `tmux send-keys -t test-json 'claude -p "Read README.md" --output-format stream-json' Enter`
  - [ ] Wait 2 seconds: `sleep 2`
  - [ ] Capture output: `tmux capture-pane -t test-json -p`
  - [ ] Verify JSON events appear in output
  - [ ] Cleanup: `tmux kill-session -t test-json`

**Deliverables:**
- [ ] `services/json_parser.py` created and tested
- [ ] `json_session_id` field added to Task model
- [ ] Experimental JSON methods added to tmux.py
- [ ] Existing code still works (no breaking changes)

**Rollback:** Delete new files, run `alembic downgrade -1`

---

### 🟡 Phase 2: Create JSON Monitor Service (2 hours)

**Goal:** Build new monitoring service alongside existing poller

#### Step 2.1: Create json_monitor.py (1.5 hours)

- [ ] Create new file: `services/json_monitor.py`
- [ ] Implement `JsonMonitor` class with:
  - [ ] `__init__()` method
  - [ ] `_monitor_task()` method
  - [ ] `_handle_event()` method with event handlers:
    - [ ] `session_start` handler
    - [ ] `tool_use` handler
    - [ ] `tool_result` handler (with GitButler commit)
    - [ ] `text` handler
    - [ ] `result` handler
    - [ ] `error` handler
  - [ ] `_monitor_loop()` async method
  - [ ] `start()` method
  - [ ] `stop()` method
- [ ] Create test file: `tests/test_json_monitor.py`
- [ ] Write unit tests for JsonMonitor
- [ ] Run tests: `uv run pytest tests/test_json_monitor.py -v`
- [ ] Fix any failing tests

#### Step 2.2: Add Feature Flag to Config (15 min)

- [ ] Open `config.py`
- [ ] Add `MonitoringConfig` class with `use_json_mode` field
- [ ] Update main config class to include `monitoring: MonitoringConfig`
- [ ] Open `chorus.toml`
- [ ] Add `[monitoring]` section
- [ ] Add `use_json_mode = false` setting
- [ ] Add `poll_interval = 1.0` setting
- [ ] Test config loads: `uv run python -c "from config import get_config; print(get_config().monitoring)"`

**Deliverables:**
- [ ] `services/json_monitor.py` created
- [ ] Feature flag added to config
- [ ] Both old (hooks) and new (JSON) systems can coexist

**Rollback:** Delete `json_monitor.py`, remove feature flag from config

---

### 🟠 Phase 3: Parallel Testing (2 hours)

**Goal:** Run both systems side-by-side to verify JSON mode works

#### Step 3.1: Update main.py to Run Both Monitors (30 min)

- [ ] Open `main.py`
- [ ] Import `JsonMonitor` from `services.json_monitor`
- [ ] Update `startup()` event handler to check feature flag
- [ ] Add logic to start `JsonMonitor` if `use_json_mode = true`
- [ ] Add logic to start `StatusPoller` if `use_json_mode = false`
- [ ] Test server starts with `use_json_mode = false`: `uv run python main.py`
- [ ] Stop server (Ctrl+C)
- [ ] Test server starts with `use_json_mode = true` in config
- [ ] Stop server (Ctrl+C)

#### Step 3.2: Test JSON Mode with Feature Flag (1 hour)

- [ ] Set feature flag in `chorus.toml`: `use_json_mode = true`
- [ ] Start server: `uv run python main.py`
- [ ] In another terminal, create test task:
  ```bash
  curl -X POST http://localhost:8000/api/tasks \
    -H "Content-Type: application/json" \
    -d '{"title":"JSON test","description":"Test JSON monitoring"}'
  ```
- [ ] Start the task with initial prompt:
  ```bash
  curl -X POST http://localhost:8000/api/tasks/1/start \
    -H "Content-Type: application/json" \
    -d '{"initial_prompt":"Read the README.md file"}'
  ```
- [ ] Watch logs for JSON events: `tail -f chorus.log | grep "JSON"`
- [ ] Verify JSON events are being parsed
- [ ] Send a message to Claude:
  ```bash
  curl -X POST http://localhost:8000/api/tasks/1/send \
    -H "Content-Type: application/json" \
    -d '{"message":"Add a comment to main.py"}'
  ```
- [ ] Check GitButler status: `but status`
- [ ] Verify GitButler auto-commit happened
- [ ] Check task status via API: `curl http://localhost:8000/api/tasks/1`
- [ ] Verify `json_session_id` is populated
- [ ] Complete the task:
  ```bash
  curl -X POST http://localhost:8000/api/tasks/1/complete
  ```
- [ ] Stop server

#### Step 3.3: Document Differences (30 min)

- [ ] Create `MIGRATION_NOTES.md` file
- [ ] Document feature comparison table (Hook Mode vs JSON Mode)
- [ ] List any issues found during testing
- [ ] Document performance metrics (CPU, memory, latency)
- [ ] Note any behavioral differences
- [ ] Document session resumption test results
- [ ] Commit notes: `git add MIGRATION_NOTES.md && git commit -m "Add migration test notes"`

**Deliverables:**
- [ ] Both systems tested in parallel
- [ ] Feature flag works correctly
- [ ] Migration notes document behavior differences
- [ ] JSON mode validated as working

**Rollback:** Set `use_json_mode = false` in config

---

### 🔴 Phase 4: Cutover (1.5 hours)

**Goal:** Make JSON mode the default and remove hook infrastructure

#### Step 4.1: Update Task API to Use JSON Mode (45 min)

- [ ] Open `api/tasks.py`
- [ ] Remove `from services.hooks import HooksService` import
- [ ] Update `start_task()` function:
  - [ ] Remove `hooks = HooksService()` line
  - [ ] Remove `hooks.ensure_hooks()` line
  - [ ] Change `tmux.start_claude()` to `tmux.start_claude_json_mode()`
- [ ] Update `restart_claude()` function:
  - [ ] Change to use `start_claude_json_mode()`
- [ ] Update `send_message()` function:
  - [ ] Build `--resume` command with `task.json_session_id`
  - [ ] Use JSON mode command format
- [ ] Run tests: `uv run pytest tests/test_tasks.py -v`
- [ ] Fix any failing tests

#### Step 4.2: Remove Hook Code (30 min)

- [ ] Delete file: `rm services/hooks.py`
- [ ] Delete file: `rm api/hooks.py`
- [ ] Delete file: `rm services/status_detector.py`
- [ ] Delete tests: `rm tests/test_hooks.py` (if exists)
- [ ] Delete tests: `rm tests/test_status_detector.py` (if exists)
- [ ] Find all files with `HooksService` import: `grep -r "HooksService" .`
- [ ] Remove `HooksService` imports from all files
- [ ] Find all files with `StatusDetector` import: `grep -r "StatusDetector" .`
- [ ] Remove `StatusDetector` imports from all files
- [ ] Run full test suite: `uv run pytest`
- [ ] Fix any import errors

#### Step 4.3: Rename json_monitor.py → monitor.py (15 min)

- [ ] Rename file: `mv services/json_monitor.py services/monitor.py`
- [ ] Update class name from `JsonMonitor` to `Monitor` in the file
- [ ] Find all imports: `grep -r "json_monitor" .`
- [ ] Update all imports from `services.json_monitor` to `services.monitor`
- [ ] Update all `JsonMonitor` references to `Monitor`
- [ ] Run tests: `uv run pytest`

#### Step 4.4: Update main.py (15 min)

- [ ] Open `main.py`
- [ ] Remove feature flag logic
- [ ] Always use Monitor (formerly JsonMonitor)
- [ ] Remove StatusPoller import and usage
- [ ] Simplify startup code to always start Monitor
- [ ] Test server starts: `uv run python main.py`
- [ ] Verify no errors on startup
- [ ] Stop server

**Deliverables:**
- [ ] Hook code deleted
- [ ] JSON mode is the only mode
- [ ] All tests pass
- [ ] Server starts without errors

**Rollback:** `git checkout main` (full rollback to start)

---

### 🟣 Phase 5: Cleanup & Documentation (1 hour)

#### Step 5.1: Update Documentation (30 min)

- [ ] Update `design.md`:
  - [ ] Remove hook architecture section
  - [ ] Add JSON monitoring section
  - [ ] Update architecture diagrams
  - [ ] Update component responsibilities table
- [ ] Update `CLAUDE.md`:
  - [ ] Remove hook setup instructions
  - [ ] Update task workflow description
  - [ ] Update GitButler workflow section
- [ ] Update `PLAN.md`:
  - [ ] Mark hook phases as completed/removed
  - [ ] Add JSON monitoring phase notes
  - [ ] Update architecture decision notes
- [ ] Update `README.md`:
  - [ ] Update quick start instructions
  - [ ] Simplify setup (no hooks needed)
  - [ ] Update architecture overview
- [ ] Review all documentation changes
- [ ] Commit docs: `git add . && git commit -m "Update documentation for JSON monitoring"`

#### Step 5.2: Update Tests (30 min)

- [ ] Review all test files in `tests/`
- [ ] Remove hook-related assertions from tests
- [ ] Add JSON event assertions to tests
- [ ] Update integration tests for JSON mode
- [ ] Run full test suite: `uv run pytest`
- [ ] Run with coverage: `uv run pytest --cov`
- [ ] Review coverage report
- [ ] Ensure coverage is acceptable (>80%)
- [ ] Fix any failing tests
- [ ] Commit test updates: `git add tests/ && git commit -m "Update tests for JSON monitoring"`

#### Step 5.3: Final Commit (5 min)

- [ ] Review all changes: `git status`
- [ ] Review diff: `git diff main`
- [ ] Add all files: `git add .`
- [ ] Create final commit with detailed message:
  ```bash
  git commit -m "Migrate to hybrid architecture (tmux + claude -p + stream-json)

  - Replace hook-based status detection with JSON event parsing
  - Remove 815 lines of hook infrastructure code
  - Add JSON monitor service (200 lines)
  - Simplify task lifecycle management
  - Enable session resumption via --resume
  - Net reduction: -515 lines (36% smaller codebase)

  Breaking changes:
  - Removed /api/hooks/* endpoints
  - Removed services/hooks.py and api/hooks.py
  - Updated Task model (added json_session_id field)

  Migration: Automatic (feature flag tested in parallel)"
  ```
- [ ] Push to remote: `git push origin feature/hybrid-json-monitoring`

**Deliverables:**
- [ ] All documentation updated
- [ ] Tests updated and passing
- [ ] Migration complete
- [ ] Ready for PR/merge to main

---

## Testing Checklist

Before merging to main, verify all of the following:

- [ ] Basic task creation works
- [ ] Task start launches Claude in JSON mode
- [ ] JSON events are parsed correctly from tmux output
- [ ] Tool use detected (Read, Edit, Write, Bash, Grep, Glob)
- [ ] GitButler auto-commit triggers on file edits
- [ ] Session resumption works (send_message uses --resume)
- [ ] Multiple concurrent tasks work (separate tmux sessions)
- [ ] Each task commits to its own GitButler stack
- [ ] Task completion cleans up properly
- [ ] Task failure cleans up properly
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] No regression in GitButler multi-stack support
- [ ] MCP servers (lean-lsp, rocq-lsp) still work
- [ ] Skills still work
- [ ] Server starts without errors
- [ ] Server shuts down cleanly
- [ ] Logs are clear and informative
- [ ] No memory leaks observed
- [ ] Performance is acceptable (no slower than hook mode)

---

## Rollback Plan

| Phase | Rollback Command | Impact | Data Loss |
|-------|------------------|--------|-----------|
| Phase 0 | `git checkout main` | None | None |
| Phase 1 | `git checkout main` | None | None |
| Phase 2 | `git checkout main` | None | None |
| Phase 3 | Set `use_json_mode = false` in config | None | None |
| Phase 4+ | `git checkout main` + `alembic downgrade -1` | Breaking | Tasks lose `json_session_id` |

**Emergency Rollback (from any phase):**
```bash
git checkout main
alembic downgrade -1  # Remove json_session_id field
uv run python main.py  # Should work with hooks again
```

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| JSON parsing fails | Medium | High | Feature flag allows A/B testing in Phase 3 |
| GitButler commits missed | Low | High | Monitor logs during Phase 3 testing |
| Session resumption broken | Medium | Medium | Test extensively in Phase 3 |
| MCP/Skills stop working | Low | High | Test early in Phase 3 |
| Concurrent tasks conflict | Low | Medium | Test multi-task scenario in Phase 3 |
| Database migration fails | Low | Low | Simple field addition, easily reversible |
| Performance degradation | Medium | Medium | Monitor CPU/memory in Phase 3 |
| Terminal parsing breaks | Medium | High | Use feature flag, extensive testing |

---

## Success Criteria

Migration is successful when all of the following are true:

- [ ] All hook-related code deleted (-815 lines)
- [ ] JSON monitor working (+200 lines)
- [ ] All tests passing (100%)
- [ ] GitButler auto-commit working
- [ ] Multiple concurrent tasks working
- [ ] Session resumption working
- [ ] MCP servers and Skills working
- [ ] Documentation updated
- [ ] Net code reduction: -515 lines (36% smaller)
- [ ] No regressions in functionality
- [ ] Performance equal or better than before

---

## Timeline Estimate

| Phase | Duration | Can Start | Blocking Dependencies |
|-------|----------|-----------|----------------------|
| Phase 0 | 30 min | Immediately | - |
| Phase 1 | 2 hours | After Phase 0 | - |
| Phase 2 | 2 hours | After Phase 1 | - |
| Phase 3 | 2 hours | After Phase 2 | Phase 1, 2 must be complete |
| Phase 4 | 1.5 hours | After Phase 3 | Phase 3 must be validated |
| Phase 5 | 1 hour | After Phase 4 | - |

**Total: 9 hours** (can be spread over 2-3 days)

**Suggested Schedule:**
- **Day 1:** Phases 0-2 (4.5 hours) - Preparation + Infrastructure
- **Day 2:** Phase 3 (2 hours) - Parallel Testing + Validation
- **Day 3:** Phases 4-5 (2.5 hours) - Cutover + Cleanup

---

## Progress Tracking

Update this section as you complete phases:

### Completed Phases
- [ ] Phase 0: Preparation & Backup
- [ ] Phase 1: Add JSON Parsing Infrastructure
- [ ] Phase 2: Create JSON Monitor Service
- [ ] Phase 3: Parallel Testing
- [ ] Phase 4: Cutover
- [ ] Phase 5: Cleanup & Documentation

### Current Status
- **Current Phase:** Not started
- **Blockers:** None
- **Notes:** Ready to begin

---

## Notes & Observations

Use this section to track issues, decisions, and observations during migration:

### Issues Encountered
<!-- Add issues as you find them -->

### Decisions Made
<!-- Document any architectural decisions or deviations from the plan -->

### Performance Observations
<!-- Track performance metrics, CPU usage, memory, etc. -->

### Test Results
<!-- Document test results, edge cases found, etc. -->

---

**Migration prepared by:** Claude (Sonnet 4.5)
**Date:** 2025-12-30
**Repository:** /Users/zongyuan/code/chorus

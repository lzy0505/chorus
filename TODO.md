# TODO

> Auto-updated by Claude Code. Last update: 2025-12-31 00:02

## In Progress

<!-- Tasks currently being worked on -->

## Up Next

<!-- Future enhancements -->

### Migration to JSON Monitoring Architecture

**Goal:** Implement JSON event parsing for Claude session monitoring
**Estimated Time:** 8-12 hours over 2-3 days

#### Phase 0: Preparation & Backup (30 min)
1. [ ] Run `but branch new feature/hybrid-json-monitoring`
2. [ ] Start server, create test task, check logs for current behavior baseline
3. [ ] Run `but commit -c feature/hybrid-json-monitoring -m "Checkpoint before JSON migration"`

#### Phase 1: Add JSON Parsing Infrastructure (2 hours)
4. [ ] Create `services/json_parser.py`: define `@dataclass ClaudeJsonEvent(event_type: str, data: dict, session_id: Optional[str])`
5. [ ] In `json_parser.py`: implement `JsonEventParser.parse_line(line: str)` using `json.loads()` with try/except
6. [ ] In `json_parser.py`: implement `JsonEventParser.parse_output(output: str)` to split by `\n` and parse each line
7. [ ] Create `tests/test_json_parser.py`: test cases for valid JSON, invalid JSON, empty input, multiple events
8. [ ] Run `uv run pytest tests/test_json_parser.py -v` to verify
9. [ ] In `models.py`: add `json_session_id: Optional[str] = Field(default=None)` to `Task` class after `claude_session_id`
10. [ ] Run `alembic revision --autogenerate -m "Add json_session_id to Task"`
11. [ ] Run `alembic upgrade head && alembic current` to apply and verify migration
12. [ ] In `services/tmux.py`: copy `start_claude()` method to new `start_claude_json_mode()`, append `--output-format stream-json` to command
13. [ ] In `services/tmux.py`: add `capture_json_events(task_id: int) -> str` that runs `tmux capture-pane -t task-{id} -p`
14. [ ] Test manually: `tmux new -s test && tmux send-keys -t test 'claude -p "hi" --output-format stream-json' Enter && sleep 2 && tmux capture-pane -t test -p`

#### Phase 2: Create JSON Monitor Service (2 hours)
15. [ ] Create `services/json_monitor.py`: define `class JsonMonitor` with `__init__(self, db: Session, tmux: TmuxService, gitbutler: GitButlerService, json_parser: JsonEventParser)`
16. [ ] In `json_monitor.py`: implement `async _monitor_task(self, task_id: int)` to call `tmux.capture_json_events()` then `json_parser.parse_output()`
17. [ ] In `json_monitor.py`: implement `async _handle_event(self, task_id: int, event: ClaudeJsonEvent)` with `match event.event_type:`
18. [ ] In `_handle_event()`: case `"session_start"` → set `task.json_session_id = event.session_id` and `task.claude_status = "idle"`
19. [ ] In `_handle_event()`: case `"tool_result"` → if `event.data["tool_name"]` in `["Edit", "Write"]`, call `gitbutler.commit_to_stack(task.stack_name)`
20. [ ] In `_handle_event()`: case `"result"` → store `task.json_session_id = event.session_id` for resumption
21. [ ] In `json_monitor.py`: implement `start(self)` to create `asyncio.create_task()` for monitoring loop
22. [ ] Create `tests/test_json_monitor.py`: mock `tmux.capture_json_events()` return value, verify status updates
23. [ ] Run `uv run pytest tests/test_json_monitor.py -v`
24. [ ] In `config.py`: add `class MonitoringConfig(BaseModel): use_json_mode: bool = False; poll_interval: float = 1.0`
25. [ ] In `config.py`: add `monitoring: MonitoringConfig = MonitoringConfig()` to `Settings` class
26. [ ] In `chorus.toml`: add `[monitoring]\nuse_json_mode = false\npoll_interval = 1.0`

#### Phase 3: Parallel Testing (2 hours)
27. [ ] In `main.py`: import `JsonMonitor`, in `startup()` add: `if config.monitoring.use_json_mode: monitor = JsonMonitor(...) else: monitor = StatusPoller(...)`
28. [ ] With `use_json_mode = false`, run `uv run python main.py`, verify no errors
29. [ ] Set `use_json_mode = true` in `chorus.toml`, run `uv run python main.py`, verify startup
30. [ ] Run `curl -X POST localhost:8000/api/tasks -H 'Content-Type: application/json' -d '{"title":"test","description":"test"}'`
31. [ ] Run `curl -X POST localhost:8000/api/tasks/1/start -H 'Content-Type: application/json' -d '{"initial_prompt":"Read README.md"}'`
32. [ ] Run `tail -f chorus.log | grep -E "JSON|session_id"` to verify JSON event parsing
33. [ ] Run `curl -X POST localhost:8000/api/tasks/1/send -H 'Content-Type: application/json' -d '{"message":"Add a comment to main.py"}'`
34. [ ] Run `but status` to confirm auto-commit occurred on task's stack
35. [ ] Run `curl localhost:8000/api/tasks/1 | jq '.json_session_id'` to verify field is populated
36. [ ] Send another message, check logs to verify `--resume` flag is used with `json_session_id`
37. [ ] Create `MIGRATION_NOTES.md` documenting: CPU usage, memory, response latency, issues found, resumption test results

#### Phase 4: Cutover (1.5 hours)
38. [ ] In `api/tasks.py` function `start_task()`: replace `tmux.start_claude(task.id)` with `tmux.start_claude_json_mode(task.id)`
39. [ ] In `api/tasks.py` function `send_message()`: add logic: `if task.json_session_id: prompt += f" --resume {task.json_session_id}"`
40. [ ] In `api/tasks.py` function `restart_claude()`: replace with `tmux.start_claude_json_mode(task.id)`
41. [ ] Run `rm services/hooks.py`
42. [ ] Run `rm api/hooks.py`
43. [ ] Run `rm services/status_detector.py`
44. [ ] Run `rg "from services.hooks import" -l` and delete those import lines
45. [ ] Run `rg "from services.status_detector import" -l` and delete those import lines
46. [ ] Run `mv services/json_monitor.py services/monitor.py`
47. [ ] In `services/monitor.py`: replace `class JsonMonitor:` with `class Monitor:`
48. [ ] Run `rg "json_monitor" -l` and replace all occurrences with `monitor`
49. [ ] Run `rg "JsonMonitor" -l` and replace all occurrences with `Monitor`
50. [ ] In `main.py`: remove `if config.monitoring.use_json_mode` check, always use `Monitor`
51. [ ] Run `uv run pytest`
52. [ ] Fix failing tests: remove hook assertions, update to check JSON event handling

#### Phase 5: Cleanup & Documentation (1 hour)
53. [ ] In `design.md`: verify "JSON Monitor Service" section exists, remove "Hook Handler Service" if present
54. [ ] In `design.md`: verify "JSON Event Parsing" section exists, remove "Claude Code Hooks Integration" if present
55. [ ] In `CLAUDE.md`: verify Architecture section describes JSON monitoring correctly
56. [ ] In `PLAN.md`: update Phase 2 section, add note about JSON monitoring replacing hooks
57. [ ] In `README.md`: verify "How It Works" describes JSON parsing
58. [ ] In `tests/`: update integration tests to mock JSON events instead of hook endpoints
59. [ ] Run `uv run pytest --cov`
60. [ ] If coverage < 80%, add tests for uncovered Monitor/JsonParser code paths
61. [ ] Run `but commit -c feature/hybrid-json-monitoring -m "Migrate to JSON monitoring\n\n- Add json_parser and monitor services\n- Remove hooks/status_detector (815 lines)\n- Add json_session_id for --resume support\n- Update all docs"`
62. [ ] Run `git push origin feature/hybrid-json-monitoring`

#### Testing Checklist (Before Merge)
- [ ] Run: Create task, start task, verify Claude launches with `--output-format stream-json`
- [ ] Run: Check logs for parsed JSON events (session_start, tool_use, tool_result)
- [ ] Run: Edit a file via Claude, verify `but status` shows auto-commit
- [ ] Run: Send second message, verify `--resume` flag used in logs
- [ ] Run: Create two tasks concurrently, verify each commits to own stack
- [ ] Run: Complete task, verify cleanup happens
- [ ] Run: `uv run pytest` all unit tests pass
- [ ] Run: Integration test with real Claude session
- [ ] Check: MCP servers still work (if configured)

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

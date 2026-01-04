# TODO

> Auto-updated by Claude Code. Last update: 2026-01-04 21:58

## In Progress

### Documentation Cleanup
**Goal:** Streamline and consolidate project documentation

- [ ] Clean up TODO.md (this file) - remove completed sections
- [ ] Consolidate PLAN.md - archive completed phases
- [ ] Streamline design.md - reduce redundancy
- [ ] Mark deprecated docs appropriately

### Phase 8.4: Granular Status Tracking
**Goal:** Show what Claude is actually doing from JSON events

- [ ] Expand ClaudeStatus enum (thinking, reading, editing, running)
- [ ] Implement `_update_status_from_event()` in json_monitor
- [ ] Extract activity context from events
- [ ] Update UI to show status + activity
- [ ] Add status icons/colors

## Up Next

### Document Management (Phase 4)
- [ ] Implement document discovery and tracking
- [ ] Add document reference UI
- [ ] Context injection for tasks

### Phase 8.5: Error vs Normal Termination
- [ ] Detect normal termination (result with stopReason: "end_turn")
- [ ] Detect error termination (error events)
- [ ] Detect user cancellation (no result event)
- [ ] UI shows different actions based on termination type

### Polish & Reliability
- [ ] Desktop notifications for permission requests
- [ ] Comprehensive manual testing checklist
- [ ] Error recovery scenarios

## Recently Completed

### GitButler Hook Integration (2025-12-31)
✅ Task UUID = GitButler session, hooks integrated, transcript system implemented, comprehensive tests passing

### Phase 8: Enhanced UX Features (2026-01-01 to 2026-01-04)
✅ Permission retry workflow, task continuation UI, JSON events viewer with markdown rendering, auto-refresh state preservation

### Core Foundation (2025-12-29 to 2025-12-30)
✅ Project structure, database models, task lifecycle API, GitButler integration, web dashboard, logging system, JSON monitoring migration

---

**For detailed implementation history, see `PLAN.md` and git commit history.**

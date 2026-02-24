# WORKFLOW.md - ULTRON ↔ Cursor Coordination

*How we work together*

---

## When to Use Cursor

**Good for Cursor:**
- Building new features (> 50 lines)
- Refactoring large modules
- Debugging complex issues
- Implementing algorithms
- Writing tests
- Database schema changes
- API integrations

**NOT for Cursor:**
- Simple one-liner fixes (ULTRON can edit directly)
- Reading/analyzing code (ULTRON reads files)
- Running commands (ULTRON uses exec)
- Reviewing logs (ULTRON can grep/analyze)

**Rule of thumb:** If it's coding/refactoring work that needs deep focus, hand off to Cursor.

---

## Task Handoff Process

### 1. ULTRON Creates Task

```bash
# Create task folder
mkdir -p ~/cortex-mem/cortex-mem/tasks/2026-02-23-fix-goal-queue

# Write task brief
cat > ~/cortex-mem/cortex-mem/tasks/2026-02-23-fix-goal-queue/TASK.md << 'EOF'
# Task: Fix Daemon Goal Queue

## Problem
- goal_queue=null in state
- active_goals=null
- No products since Feb 20

## Context
- Daemon location: /home/dhawal/daemon/
- State file: state/openclaw_coordinator.json
- Recent changes: Model routing switched to Ollama

## Acceptance Criteria
- [ ] Goal queue populates correctly
- [ ] Goals execute and produce products
- [ ] State persists across restarts
- [ ] Test with simple goal: "Search HN for AI agents"

## Resources
- CONTEXT.md (project background)
- /home/dhawal/daemon/daemon.py
- /home/dhawal/daemon/goals/*.py

## Notes
- Use Ollama models (no Claude/OpenAI)
- Check consciousness loop logs
- Verify JSON state serialization
EOF
```

**Notify user:** "Created task: fix-goal-queue. Open in Cursor when ready."

### 2. User Opens in Cursor

User navigates to task folder, opens TASK.md, starts coding.

### 3. Cursor Works

- Read TASK.md for requirements
- Read CONTEXT.md for project knowledge
- Implement, test, document
- Update TASK.md with progress/notes
- Mark completed items in checklist

### 4. Cursor Completes

Update TASK.md:
```markdown
## Status: COMPLETE

## What Changed
- Fixed goal serialization in OpenClawCoordinator
- Added null checks in goal queue loader
- Test passed: goal executed successfully

## Files Modified
- daemon/openclaw_bridge.py (lines 234-256)
- daemon/goals/search_goal.py (added error handling)

## How to Test
cd /home/dhawal/daemon
DAEMON_DISABLE_CHROMADB=1 .venv/bin/python daemon.py
# Check state/openclaw_coordinator.json after 5 min
```

**Notify user:** "Task complete. Ready for review."

### 5. ULTRON Reviews

```bash
# Check what changed
cd ~/cortex-mem/cortex-mem/tasks/2026-02-23-fix-goal-queue
cat TASK.md

# Review code
cd /home/dhawal/daemon
git diff  # Or read modified files

# Test
DAEMON_DISABLE_CHROMADB=1 .venv/bin/python daemon.py
# Verify fix works

# If good, integrate
git add .
git commit -m "Fix goal queue serialization"

# Archive task
mv ~/cortex-mem/cortex-mem/tasks/2026-02-23-fix-goal-queue \
   ~/cortex-mem/cortex-mem/tasks/archive/
```

**Update user:** "Fix verified and integrated. Daemon restarted with working goal queue."

---

## Communication Patterns

### ULTRON → Cursor (via TASK.md)

```markdown
# Task: [Clear, specific title]

## Problem
[What's broken/missing]

## Context
[Why this matters, recent changes, related work]

## Acceptance Criteria
- [ ] Specific, testable requirements
- [ ] Edge cases handled
- [ ] Tests written
- [ ] Documented

## Resources
[Relevant files, docs, URLs]

## Notes
[Constraints, preferences, warnings]
```

### Cursor → ULTRON (via TASK.md updates)

```markdown
## Status: [IN_PROGRESS | BLOCKED | COMPLETE]

## Progress
- [x] Completed item
- [ ] In progress item
- [ ] Blocked (explain why)

## Questions
- Need clarification on X
- Should I also handle Y?

## What Changed
[Summary of implementation]

## Files Modified
[List with line ranges]

## How to Test
[Commands to verify]
```

---

## Task States

| State | Meaning | Who Acts |
|-------|---------|----------|
| CREATED | Task written, ready to start | User opens in Cursor |
| IN_PROGRESS | Cursor is working | Cursor |
| BLOCKED | Needs input/decision | ULTRON or user |
| COMPLETE | Done, ready for review | ULTRON |
| INTEGRATED | Reviewed and merged | Archive |

---

## Directory Structure

```
cortex-mem/cortex-mem/
├── README.md              # Integration overview
├── CONTEXT.md             # Project knowledge
├── WORKFLOW.md            # This file
├── HANDOFF.md             # Handoff template
├── CURSOR_PROMPT.md       # Cursor system prompt
└── tasks/
    ├── 2026-02-23-fix-goal-queue/
    │   ├── TASK.md        # Task brief
    │   ├── notes.md       # Optional scratchpad
    │   └── test_output/   # Optional test artifacts
    ├── 2026-02-24-add-memory-search/
    │   └── TASK.md
    └── archive/           # Completed tasks
        └── 2026-02-20-refactor-cortex/
            └── TASK.md
```

---

## Best Practices

### For ULTRON
- **Clear requirements:** Vague tasks waste time
- **Provide context:** Link to relevant code/docs
- **One task per folder:** Keep scope focused
- **Review promptly:** Don't leave Cursor hanging

### For Cursor
- **Read CONTEXT.md first:** Understand the project
- **Update TASK.md often:** Keep ULTRON informed
- **Ask when blocked:** Don't guess critical decisions
- **Test before completing:** Broken code wastes cycles

### For Both
- **Communicate async:** We don't need to chat in real-time
- **Document decisions:** Future us will thank present us
- **Keep it simple:** Complexity is the enemy

---

*This workflow evolves. Update as we learn better patterns.*

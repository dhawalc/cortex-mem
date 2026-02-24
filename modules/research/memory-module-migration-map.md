# OpenClaw → openclaw-memory Migration Map

## Goal
Map current OpenClaw workspace files into the standalone memory module tree, with minimal disruption.

---

## Current Workspace Files → New Modules

### Core / Onboarding
- `/home/dhawal/.openclaw/workspace/AGENTS.md` → `openclaw-memory/AGENTS.md`
- `/home/dhawal/.openclaw/workspace/IDENTITY.md` → `modules/identity/IDENTITY.md`
- `/home/dhawal/.openclaw/workspace/SOUL.md` → `modules/identity/voice.md`
- `/home/dhawal/.openclaw/workspace/USER.md` → `modules/identity/values.yaml` (or `IDENTITY.md` addendum)

### Memory
- `/home/dhawal/.openclaw/workspace/MEMORY.md` → `modules/memory/MEMORY.md`
- `/home/dhawal/.openclaw/workspace/memory/*.md` → `modules/memory/episodic/experiences.jsonl` (long-term) + `projects/status.jsonl` (daily)

### Operations / System
- `/home/dhawal/.openclaw/workspace/TOOLS.md` → `modules/operations/OPERATIONS.md`
- `/home/dhawal/.openclaw/workspace/HEARTBEAT.md` → `modules/operations/checklists.yaml`

### Projects / Research
- `/home/dhawal/.openclaw/workspace/docs/*` → `modules/research/` (notes + references)
- `/home/dhawal/.openclaw/workspace/PENDING.md` → `modules/projects/status.jsonl` or `projects.yaml`

### Content
- `/home/dhawal/.openclaw/workspace/twitter_engagement_strategy_2026.md` → `modules/content/CONTENT.md`
- `/home/dhawal/.openclaw/workspace/engagement-targets-2026-02-20.md` → `modules/content/ideas.jsonl` (or archive)

---

## Proposed New Tree (Minimal)
```
openclaw-memory/
  AGENTS.md
  AGENT.md
  router.yaml
  modules/
    identity/
      IDENTITY.md
      voice.md
      values.yaml
    memory/
      MEMORY.md
      episodic/
        experiences.jsonl
        decisions.jsonl
        failures.jsonl
    operations/
      OPERATIONS.md
      priorities.yaml
      checklists.yaml
    projects/
      projects.yaml
      status.jsonl
    content/
      CONTENT.md
      ideas.jsonl
      posts.jsonl
    research/
      RESEARCH.md
      notes.md
  schemas/
    jsonl_schemas.yaml
```

---

## Migration Steps (No Breakage)
1. **Copy** (not move) current files into the new repo structure.
2. Add `router.yaml` to map tasks → modules.
3. Add `AGENT.md` with decision table and global rules.
4. Keep OpenClaw workspace as is; only dual-read for now.
5. Gradually switch OpenClaw boot to read from the new memory repo.

---

## Open Questions
- Should the memory repo live inside `/home/dhawal/.openclaw/` or as its own Git repo?
- How much of daily logs should remain as Markdown vs JSONL?
- Should we move personal info (family, etc.) into identity module or keep in MEMORY.md?

---

## Next Action
If you approve, I can scaffold the repo structure and copy files into it without breaking current OpenClaw behavior.

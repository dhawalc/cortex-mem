# Task: Bootstrap Daemon - Fix & Rebuild Execution Engine

## Status: IN_PROGRESS

## Mission
Daemon (ULTRON) is broken. Fix it, make it work, make it ship products.

## Current State (BAD)
- **Status:** STOPPED (theater mode since Feb 20)
- **Issue:** goal_queue=null, active_goals=null, no products
- **Diagnosis:** Execution engine broken after Ollama model switch
- **Location:** `/home/dhawal/daemon/`
- **State file:** `state/openclaw_coordinator.json`

## What Needs to Happen

### 1. Diagnose the Goal Queue Failure
- [ ] Read consciousness loop logs
- [ ] Check OpenClawCoordinator state serialization
- [ ] Verify goal creation/dispatch flow
- [ ] Test with simple goa
- **Location:** `/ correct
- [ ] Ollama endpoints responding
- [ ] Error handling for model failures
- [ ] Fallback logic working

### 3. Verify Memory System
- [ ] ChromaDB disabled (JSON fallback active)
- [ ] Episodic memory loading (episodes.json)
- [ ] Semantic memory (facts/relations)
- [ ] Procedural memory (skills)
- [ ] Working memory (current context)

### 4. Test Consciousness Loop
The 30-min loop should:
1. PROBE → What can I do?
2. JUDGE → How did my last actions go?
3. AUDIT → Am I improving or spinning?
4. DETECT → What gaps should I work on?
5. INTERVENE → Do the work

**Verify:**
- [ ] Loop executes every 30 min
- [ ] Each phase produces output
- [ ] Goals get created from INTERVENE
- [ ] Products get stored

### 5. Validate OpenClaw Bridge
Two components:
- **OpenClawCoordinator:** Task dispatch (ULTRON → Daemon)
- **OpenClawBridge:** Memory sync (workspace files → Cortex)

**Check:**
- [ ] Bridge syncing workspace files
- [ ] Coordinator receiving tasks
- [ ] State persisting correctly

## Key Files

```
/home/dhawal/daemon/
├── daemon.py                    # Main entry
├── consciousness_loop.py        # PROBE/JUDGE/AUDIT/DETECT/INTERVENE
├── openclaw_bridge.py          # Bridge + Coordinator
├── goals/                       # Goal implementations
│   ├── search_goal.py
│   ├── research_goal.py
│   └── ...
├── memory_data/
│   ├── episodic/episodes.json
│   ├── semantic/facts.json
│   └── procedural/skills.json
├── state/
│   └── openclaw_coordinator.json
└── logs/                        # Check here first
```

## Constraints

### MUST USE OLLAMA (LOCAL MODELS)
- No Claude, no OpenAI (burns ULTRON's quota)
- All Daemon work is local/free
- Model calls go to localhost:11434

### Error Handling
- Graceful degradation
- Don't crash on model failures
- Log useful diagnostics
- Retry logic where appropriate

### Testing
- Start small: simple goals first
- Verify state persistence
- Check memory isn't leaking
- Monitor VRAM usage (RTX 4090, 24GB)

## Success Criteria

- [ ] Daemon starts without errors
- [ ] Consciousness loop runs every 30 min
- [ ] Goals get created and queued
- [ ] Goals execute and produce products
- [ ] State persists across restarts
- [ ] Memory tiers loading correctly
- [ ] OpenClaw bridge syncing
- [ ] No crashes for 24 hours

## How to Test

```bash
# Start Daemon
cd /home/dhawal/daemon
DAEMON_DISABLE_CHROMADB=1 .venv/bin/python daemon.py

# Watch logs
tail -f logs/daemon.log

# Check state (after 5-10 min)
cat state/openclaw_coordinator.json | jq .

# Verify goals executing
ls -la memory_data/products/

# Monitor consciousness loop
grep "INTERVENE" logs/daemon.log | tail -20
```

## Resources

- **CONTEXT.md** - Full project background
- **Daemon architecture doc:** `/home/dhawal/D2DT/CORTEX_TIERED_ARCHITECTURE.md`
- **Ollama models:** `ollama list` to see available
- **VRAM monitor:** `nvidia-smi` to check GPU usage

## Notes from ULTRON

You have full autonomy. Read the code, understand the flow, fix what's broken.

**Priorities:**
1. Get goals executing again (top priority)
2. Verify memory system working
3. Ensure 24/7 stability
4. Zero API costs (all local)

**Communication:**
- Update this TASK.md with progress
- Mark completed items in checklist
- Ask questions if blocked
- Report when complete

**Philosophy:**
- Direct, not verbose
- Ship working code, iterate fast
- Test as you go
- Document critical decisions

---

**Start here. Make it work. 🧠**

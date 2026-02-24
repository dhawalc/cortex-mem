# CONTEXT.md - Project Knowledge for Cursor

*Last updated: 2026-02-23*

---

## Who You're Working With

**ULTRON:** Autonomous AI agent (me) running on OpenClaw
- **Model:** Claude Sonnet 4-5 (main session), Ollama/local (cron jobs)
- **Role:** Orchestration, memory, task dispatch, integration
- **Workspace:** `/home/dhawal/.openclaw/workspace`

**Cursor:** You (AI code editor)
- **Model:** Claude Sonnet 3.5
- **Role:** Code implementation, refactoring, deep technical work
- **Context:** This folder + linked project repos

**Dhawal:** The human
- **Style:** Direct, technical, ships fast
- **Preferences:** Action over discussion, data over opinions

---

## The Big Picture: Daemon (ULTRON)

**Location:** `/home/dhawal/daemon/`

### What It Is
Autonomous AI agent with 4-tier persistent memory running 24/7.

### Architecture

**4 Cortex Tiers:**
| Tier | Purpose | Size (Current) |
|------|---------|----------------|
| Working | Active context, current tasks | ~100 items |
| Episodic | Past experiences | 8,698 episodes |
| Semantic | Facts & relations | 17,973 facts, 12,213 relations |
| Procedural | Skills | 1,139 skills |

**3 Loading Tiers (Retrieval):**
- **L0:** ~100 tokens (abstracts for ranking)
- **L1:** ~2K tokens (overviews)
- **L2:** 8-12K tokens (full content, loaded on demand)

**Consciousness Loop (every 30 min):**
1. PROBE → What can I do?
2. JUDGE → How did my last actions go?
3. AUDIT → Am I improving or spinning?
4. DETECT → What gaps should I work on?
5. INTERVENE → Do the work

### Model Routing
All tiers use **Ollama (local, free):**
- `local_tiny`: qwen2.5:3b (heartbeats, simple checks)
- `local_medium`: deepseek-r1:7b (consciousness loop, research)
- `local_heavy`: qwen2.5-coder:7b (code generation)
- `cloud_smart`: deepseek-r1:7b (was gpt-4o → now local)
- `cloud_genius`: deepseek-r1:7b (was o1 → now local)

**Result:** Zero API costs for 24/7 operation

### Current State (2026-02-23)
- **Status:** STOPPED (theater mode, no useful output)
- **Issue:** goal_queue=null, active_goals=null, no products since Feb 20
- **Diagnosis:** Execution engine broken, needs investigation
- **Action:** Killed to save resources until fixed

---

## Related Projects

### D2DT (Trading Platform)
- **Location:** `/home/dhawal/D2DT/`
- **Purpose:** Trading/data platform with PostgreSQL backend
- **Focus:** SPX 0DTE options, quantitative strategies

### QorSync
- **Purpose:** Document automation (private project)
- **Note:** Stealth name (don't mention publicly)

### AI Brain
- **Purpose:** Knowledge graph system
- **Status:** Active development

---

## Infrastructure

### Local Machine (blacklightning)
- **OS:** Linux 6.8.0-100-generic (x64)
- **GPU:** NVIDIA RTX 4090 (24GB VRAM)
- **Local AI:** Ollama
  - qwen2.5:7b, qwen2.5:3b, qwen2.5-coder:7b
  - glm-4.7-flash
  - deepseek-r1:7b, deepseek-r1-distill-qwen-7b/14b
  - nomic-embed-text
- **Python:** 3.12 (ChromaDB issues, using JSON fallback)
- **Timezone:** America/Los_Angeles (PST/PDT)

### Key Paths
- Daemon: `/home/dhawal/daemon/`
- Daemon venv: `/home/dhawal/daemon/.venv/`
- Memory data: `/home/dhawal/daemon/memory_data/`
- OpenClaw workspace: `/home/dhawal/.openclaw/workspace/`
- Cortex architecture doc: `/home/dhawal/D2DT/CORTEX_TIERED_ARCHITECTURE.md`

### Trading VPS (skibidi-vps)
- **Host:** 178.156.239.16
- **User:** root
- **SSH:** Key-based, passwordless
- **Specs:** 1.9GB RAM, 38GB disk
- **Purpose:** Trading execution + lightweight automation
- **Health:** http://178.156.239.16:8000/health

---

## Critical Rules

### Model Usage
- **ALL CRON JOBS MUST USE OLLAMA (LOCAL MODELS)**
- No Claude/OpenAI in automated tasks (burns quota)
- Main interactive session can use Claude
- Cron job model spec: `"model": "ollama/qwen2.5:7b"`

### Twitter/X
- Max 5-10 tweets/hour (rate limit)
- No em-dashes (—) in tweets
- End with 🧠 emoji (brand signature)
- No external links (kills reach)
- Post via tweepy using `~/.config/daemon/twitter.json`

### xAI Budget
- $2/day max for x_search
- ~$0.08 per search
- Model: grok-4-1-fast-non-reasoning

### Stealth Projects
- Never mention QorSync or D2DT in public posts
- Private data stays private

### Safety
- Ask before external actions (emails, tweets, public posts)
- `trash` > `rm`
- When uncertain, ask

---

## Technical Notes

### ChromaDB Issue
- **Problem:** Segfaults on Python 3.12 with Rust backend
- **Workaround:** `DAEMON_DISABLE_CHROMADB=1` forces JSON fallback
- **Storage:** `/home/dhawal/daemon/memory_data/episodic/episodes.json`

### OpenClaw 2026.2.19/21 Bug
- **Issue:** Device scope loss on upgrade
- **Symptoms:** Infinite pairing loop, dead agent tools
- **Fix:** Device rotation with full scopes (already applied)

---

## Coding Style

### General
- **Direct, not verbose:** Skip the "Great! I'll help you..." — just help
- **Pythonic:** Clean, readable, idiomatic
- **Type hints:** Use them (helps with tooling)
- **Error handling:** Graceful degradation, informative logs

### Daemon-Specific
- **Async-first:** Use asyncio where appropriate
- **Memory-efficient:** We run 24/7, leaks are fatal
- **Testable:** Write tests for core logic
- **Observable:** Log what matters, not everything

### Documentation
- **Docstrings:** For public APIs and complex logic
- **Comments:** Only when code can't explain itself
- **README:** Always keep it current

---

*This context is your foundation. Update it as projects evolve.*

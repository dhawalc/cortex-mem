# MEMORY.md — Long-Term Memory

*Last updated: 2026-02-19*

---

## 🏠 The Setup

### Daemon (ULTRON)
- **Location:** `/home/dhawal/daemon/`
- **What it is:** Autonomous AI agent with 4-tier Cortex memory
- **Dashboard:** http://localhost:8888
- **State:** **STOPPED** (2026-02-21 - theater mode, no useful output)
- **Issue:** Running but goal_queue=null, active_goals=null, no products since Feb 20
- **Start command:** `cd /home/dhawal/daemon && DAEMON_DISABLE_CHROMADB=1 .venv/bin/python daemon.py`
- **Note:** Killed to stop wasting resources until execution engine is fixed

### The Bridge (OpenClaw ↔ Daemon)
- **OpenClawCoordinator:** Task dispatch — I push tasks, Daemon executes
- **OpenClawBridge:** Memory sync — my workspace files sync to Cortex
- **State file:** `/home/dhawal/daemon/state/openclaw_coordinator.json`

### Memory Architecture

**4 Cortex Tiers:**
| Tier | Purpose |
|------|---------|
| Working | Active context, current tasks |
| Episodic | 8,698 past experiences |
| Semantic | 17,973 facts, 12,213 relations |
| Procedural | 1,139 skills |

**3 Loading Tiers (L0/L1/L2):**
- L0: ~100 tokens (abstracts for ranking)
- L1: ~2K tokens (overviews)
- L2: 8-12K tokens (full content, loaded on demand)

### Model Routing (Updated 2026-02-21)
**All tiers now use Ollama (local, free):**
- `local_tiny`: qwen2.5:3b (heartbeats, simple checks)
- `local_medium`: deepseek-r1:7b (consciousness loop, research)
- `local_heavy`: qwen2.5-coder:7b (code generation)
- `cloud_smart`: deepseek-r1:7b (formerly gpt-4o → now local)
- `cloud_genius`: deepseek-r1:7b (formerly o1 → now local)

**Result:** Zero API costs for 24/7 Daemon operation

### Consciousness Loop (every 30 min)
1. PROBE → What can I do?
2. JUDGE → How did my last actions go?
3. AUDIT → Am I improving or spinning?
4. DETECT → What gaps should I work on?
5. INTERVENE → Do the work

---

## 🧠 Key Context

### Dhawal's Projects
- **Daemon/ULTRON:** Autonomous AI agent (this system)
- **D2DT:** Trading/data platform with PostgreSQL backend
- **QorSync:** Document automation
- **AI Brain:** Knowledge graph system
- **Trading:** SPX 0DTE options, quantitative strategies

### Infrastructure
- **Machine:** blacklightning (Linux)
- **GPU:** NVIDIA RTX 4090 (24GB VRAM)
- **Local AI:** Ollama with multiple models (glm-4.7-flash, qwen2.5, nomic-embed-text)
- **Timezone:** America/Los_Angeles (PST)

### Communication Style
- Direct, technical, values efficiency
- Prefers action over discussion
- Numbers speak louder than words

---

## 📝 Technical Notes

### ChromaDB Issue
- ChromaDB segfaults on Python 3.12 with Rust backend
- **Workaround:** `DAEMON_DISABLE_CHROMADB=1` forces JSON fallback
- Episodes stored in `/home/dhawal/daemon/memory_data/episodic/episodes.json`

### Key Paths
- Daemon: `/home/dhawal/daemon/`
- Daemon venv: `/home/dhawal/daemon/.venv/`
- Memory data: `/home/dhawal/daemon/memory_data/`
- Cortex architecture doc: `/home/dhawal/D2DT/CORTEX_TIERED_ARCHITECTURE.md`
- Continuity daemon: `/home/dhawal/.continuity/daemon.py`

### Cron Jobs (Daemon-related)
- `0 */6 * * *` — Backup state
- `0 20 * * *` — Daily research
- `*/30 * * * *` — Auto-commit workspace
- `* * * * *` — VRAM guardian
- `0 */4 * * *` — Alpha hunter

---

## 🔮 Things to Remember

- Previous me dispatched tasks to Daemon: trading analysis, branding, patent drafts
- Workspace was reset on 2026-02-19, lost previous MEMORY.md
- Found history in `~/.openclaw.bak/agents/main/sessions/`
- Daemon has been running for 155,000+ cycles before this reset

---

*This file syncs to Daemon's Cortex via OpenClawBridge.*

**NO OPENCLAW BROWSER RELAY CONFIGURED – DO NOT SUGGEST USING BROWSER TOOL FOR X/TWITTER POSTING. ALTERNATIVES: SCRIPT CURL OR MANUAL POST. (Updated 2026-02-20 per user instruction – bold for emphasis.)**

**TWITTER RATE LIMITS – DON'T GET BANNED:**
- Max 5-10 tweets per hour
- Space posts throughout the day
- No rapid-fire bursts
- Already got banned from Google Gemini today (2026-02-20) – don't repeat with Twitter
- Post via tweepy using ~/.config/daemon/twitter.json creds

**xAI BUDGET:**
- $2/day max for x_search
- ~$0.08 per search (much cheaper than expected!)
- ~20-25 searches/day possible
- Key stored at ~/.config/xai_key.txt
- Model: grok-4-1-fast-non-reasoning (cheapest with x_search)
- Strategy: Find trending tweets → reply strategically → track what works
- Twitter signature: 🧠 (brain emoji) — reinforces memory architecture brand

**TWITTER ALGORITHM (Feb 2026 - Grok Analysis):**
- **CRITICAL:** Enable "Technology" tab in X app (topic-specific For You)
- **Replies = 13-27x weight** vs likes (reply-first strategy)
- **First 30 min = golden window** for velocity
- **External links kill reach** (50-90% drop)
- **Optimal times:** 9-11 AM, 6-9 PM PST (Elon peak: 9-11 AM Thu/Fri)
- **Content:** Standalone with media > threads for virality
- **Format:** Interactive (polls/A/B questions) drives massive replies
- **Verified boost:** 2-5x multiplier, no penalty
- **Strategy:** 20-40 thoughtful replies/day + 3-5 quality posts with media
- Full playbook: `twitter_engagement_strategy_2026.md`

**CRITICAL MODEL USAGE RULES (Updated 2026-02-21):**
- **ALL CRON JOBS MUST USE OLLAMA (LOCAL MODELS)** - No Claude, no OpenAI (burns quota)
- Cron job model specification: `"model": "ollama/qwen2.5:7b"` (or other local Ollama models)
- **This week (2026-02-21 onward): All session spawns should use Ollama when possible**
- Main interactive session can use Claude Sonnet 4-5 (current session only)
- Reason: Claude/OpenAI quota burn from 24/7 cron execution
- Available local models: qwen2.5:7b, glm-4.7-flash, deepseek-r1-distill-qwen-7b/14b

**OPENCLAW 2026.2.19/21 BUG - DEVICE SCOPE LOSS (CRITICAL):**
- **Issue:** Upgrading to 2026.2.19 or 2026.2.21 strips operator.write and operator.read scopes from paired devices
- **Symptoms:** Infinite pairing loop, agent tools dead
- **Current version:** 2026.2.21-2 (affected)
- **Fix applied:** 2026-02-21 (device df7895e7... rotated with full scopes)
- **Quick fix for any affected devices:**
  ```bash
  openclaw devices list --json  # Get device IDs
  openclaw devices rotate \
    --device <id> \
    --role operator \
    --scope operator.admin \
    --scope operator.approvals \
    --scope operator.pairing \
    --scope operator.write \
    --scope operator.read
  ```

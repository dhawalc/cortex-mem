# llmfit Quick Reference

## TL;DR

Your RTX 4090 is **massively underutilized**. Current models use 6-10% VRAM for tiny/medium tiers. Recommended upgrades:

### 🎯 Recommended Model Tier Updates (Option A)

| Tier | Current | → | Recommended | Gain |
|------|---------|---|-------------|------|
| **Tiny** | qwen2.5:3b | → | **deepseek-r1-distill-qwen-7b** | 2.5x params, SOTA reasoning |
| **Medium** | glm-4.7-flash | → | **deepseek-r1-distill-qwen-14b** | 3x params, advanced reasoning |
| **Heavy** | qwen2.5-coder:32b | → | **qwen3-coder-30b-a3b-instruct** | MoE architecture, 8x context |

### Quick Install

```bash
# Start Ollama
ollama serve

# Pull new models
ollama pull deepseek-r1-distill-qwen-7b
ollama pull deepseek-r1-distill-qwen-14b
ollama pull qwen3-coder:30b-a3b-instruct-q4_K_M

# Or use llmfit TUI
~/.local/bin/llmfit
# Press 'd' on any model to download via Ollama
```

### Expected Improvements

- ✅ **Reasoning:** +50-70% (R1 models are SOTA)
- ✅ **Context:** 32k → 131k-262k tokens (+300-700%)
- ✅ **Quality:** +20-30% overall composite scores
- ✅ **Coding:** MoE efficiency (similar quality, better speed)
- ⚠️ **Speed:** Tiny/medium are 30% slower (acceptable trade-off)

### Why These Models?

1. **DeepSeek-R1** - Recent breakthrough in reasoning (Jan 2025)
2. **Qwen3-Coder** - MoE architecture (128 experts, only ~13B active)
3. **Better quantization** - Your VRAM allows Q8_0 instead of Q4
4. **Massive context** - 131k-262k vs. current 32k

### Usage Examples

```bash
# Run llmfit to see all recommendations
~/.local/bin/llmfit --memory=24G

# Get coding-specific recommendations
~/.local/bin/llmfit --memory=24G recommend --use-case coding --json

# Get reasoning-specific recommendations  
~/.local/bin/llmfit --memory=24G recommend --use-case reasoning --json

# Check system detection
~/.local/bin/llmfit --memory=24G system --json

# Launch interactive TUI
~/.local/bin/llmfit --memory=24G
```

### llmfit TUI Keybindings

| Key | Action |
|-----|--------|
| `d` | Download selected model via Ollama |
| `i` | Toggle installed-first sorting |
| `r` | Refresh installed models |
| `/` | Search models |
| `f` | Filter by fit (All/Perfect/Good/Marginal) |
| `p` | Provider filter |
| `q` | Quit |

## Full Analysis

See `llmfit-analysis.md` for complete details, benchmarks, and migration strategy.

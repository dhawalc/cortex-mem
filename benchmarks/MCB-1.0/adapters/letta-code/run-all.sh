#!/usr/bin/env bash
# Sequential execution of every scored run in this cycle.
#
# Runs are serialised deliberately: two model-driven runs sharing one Ollama
# would contend and corrupt both latency columns.
#
# The freeze is verified by runner.py on every run and re-verified here before
# and after the whole sequence. The scorer's --skip-freeze-check is never used.
set -u

MCB=/home/dhawal/cortex-mem/aoms-mcb/benchmarks/MCB-1.0
PY=/home/dhawal/cortex-mem/cortex-mem/.venv/bin/python
SCRATCH="$1"
mkdir -p "$SCRATCH"

hashes () {
  echo "--- freeze $1 ---"
  sha256sum "$MCB/cases.json" "$MCB/score.py"
}

cd "$MCB" || exit 1
hashes BEFORE

# 1. Same-day AOMS replication at the pinned commit, adapter unchanged.
echo "=== AOMS replication ==="
$PY runner.py --adapter adapters/aoms/adapter.py --config adapters/aoms/config.json \
  --output "$MCB/results-aoms-sameday-replication.json" \
  --run-dir "$SCRATCH/aoms-sameday" 2>&1 | tail -20

# 2. Letta Code, qwen3:8b, three runs.
for N in 1 2 3; do
  echo "=== letta-code qwen3:8b run $N ==="
  $PY runner.py --adapter adapters/letta-code/adapter.py \
    --config adapters/letta-code/config.json \
    --output "$MCB/results-letta-code-qwen3-8b-run$N.json" \
    --run-dir "$SCRATCH/lc-8b-$N" 2>&1 | tail -20
done

# 3. Non-conforming bare-model control, qwen3:8b, three runs.
for N in 1 2 3; do
  echo "=== CONTROL qwen3:8b run $N ==="
  $PY adapters/model-only-control/control.py --model qwen3:8b \
    --output "$MCB/results-control-qwen3-8b-run$N.json" 2>&1 | tail -20
done

# 4. Letta Code, qwen3.6:27b, three runs. Slowest; last so that a time
#    shortfall costs the least valuable column.
for N in 1 2 3; do
  echo "=== letta-code qwen3.6:27b run $N ==="
  $PY runner.py --adapter adapters/letta-code/adapter.py \
    --config adapters/letta-code/config-qwen3.6-27b.json \
    --output "$MCB/results-letta-code-qwen36-27b-run$N.json" \
    --run-dir "$SCRATCH/lc-27b-$N" 2>&1 | tail -20
done

hashes AFTER
echo "=== SEQUENCE COMPLETE ==="

# Troubleshooting

## Service Won't Start

### Port already in use

```
ERROR: [Errno 98] Address already in use
```

Another process is using port 9100. Find and stop it:

```bash
lsof -i :9100
kill <PID>
cortex-mem start --daemon
```

Or start on a different port:

```bash
cortex-mem start --daemon --port 9200
```

### Missing config.yaml

```
Error: service/config.yaml not found
```

The CLI needs to find the service root directory. Set the env var:

```bash
export CORTEX_MEM_ROOT=/path/to/cortex-mem
cortex-mem start --daemon
```

### Permission denied (systemd)

```
Failed to enable unit: Permission denied
```

Use `--user` flag for systemd commands:

```bash
systemctl --user enable cortex-mem
systemctl --user start cortex-mem
```

Make sure lingering is enabled:

```bash
loginctl enable-linger $USER
```

## Connection Issues

### `cortex-mem status` shows "not running"

1. Check if the process is alive:
   ```bash
   cat ~/.cortex-mem/cortex-mem.pid
   ps aux | grep cortex_mem
   ```

2. Check service logs:
   ```bash
   journalctl --user -u cortex-mem --since "5 min ago"
   ```

3. Try a direct health check:
   ```bash
   curl http://localhost:9100/health
   ```

### Timeout on search/write

Increase the client timeout:

```python
from service.client import MemoryClient
client = MemoryClient(timeout=30.0)
```

Or via curl:

```bash
curl --max-time 30 -X POST http://localhost:9100/memory/search ...
```

## Data Issues

### Duplicate entries after migration re-run

The export script (`scripts/export_daemon_memory.py`) tracks migrated IDs in `scripts/migrated_ids.json`. If this file is deleted, a re-run will create duplicates.

To deduplicate manually:

```bash
# Back up first
cp modules/memory/episodic/experiences.jsonl experiences.jsonl.bak

# Deduplicate by entry ID
python3 -c "
import json
seen = set()
with open('modules/memory/episodic/experiences.jsonl') as f:
    lines = f.readlines()
with open('modules/memory/episodic/experiences.jsonl', 'w') as f:
    for line in lines:
        entry = json.loads(line)
        eid = entry.get('id')
        if eid not in seen:
            seen.add(eid)
            f.write(line)
print(f'Kept {len(seen)} unique entries from {len(lines)} total')
"
```

### Search returns no results

1. Verify entries exist:
   ```bash
   cortex-mem status
   # Check entry counts
   ```

2. Try a broader query:
   ```bash
   cortex-mem search "a" --limit 1
   ```

3. Check the JSONL files directly:
   ```bash
   wc -l modules/memory/episodic/experiences.jsonl
   head -1 modules/memory/episodic/experiences.jsonl | python3 -m json.tool
   ```

### Weight not changing

Weight adjustment requires both `entry_id` and `tier`:

```bash
curl -X POST http://localhost:9100/memory/weight \
  -H "Content-Type: application/json" \
  -d '{"entry_id": "YOUR_ID", "tier": "episodic", "task_score": 0.9}'
```

If you get a 404, the entry ID doesn't exist in that tier. Search for it first to confirm the correct tier.

## Performance

### Slow searches with large datasets

For 10k+ entries, searches may take 200-500ms. This is expected for keyword-based JSONL scanning. To speed up:

1. Use tier filters to narrow scope:
   ```bash
   cortex-mem search "query" --tier episodic
   ```

2. Use date range filters via the API:
   ```json
   {"query": "...", "date_from": "2026-02-01", "date_to": "2026-02-28"}
   ```

3. Use the Cortex query endpoint for large documents (L0 summaries are pre-computed):
   ```bash
   curl -X POST http://localhost:9100/cortex/query \
     -d '{"query": "topic", "token_budget": 2000}'
   ```

### High memory usage

ChromaDB and ONNX Runtime load embedding models into memory. Expected baseline is ~300-500 MB. If you don't need embeddings:

In `service/config.yaml`:
```yaml
retrieval:
  embeddings: false
```

## Getting Help

- GitHub Issues: https://github.com/dhawalc/cortex-mem/issues
- API Docs: http://localhost:9100/docs (when service is running)

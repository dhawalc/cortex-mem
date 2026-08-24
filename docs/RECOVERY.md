# AOMS disaster recovery

This runbook recovers the v2 SQLite store without copying a live WAL database. Always restore into a new scratch directory, prove the result there, stop every writer, and only then replace the data directory. Do not extract or restore over `~/.local/share/aoms`.

The shipped backup job writes these generations by default:

- `~/openclaw_archives/aoms-v2/daily/aoms-v2-YYYY-MM-DD.sqlite3.zst`: a daily physical SQLite snapshot;
- `~/openclaw_archives/aoms-v2/weekly/aoms-v2-weekly-YYYY-MM-DD.sqlite3.zst`: a weekly physical snapshot; and
- `~/openclaw_archives/aoms-v2/weekly/aoms-v2-portable-YYYY-MM-DD.tar.zst`: a weekly portable export.

Each archive has adjacent `.sha256` and `.metadata.json` files. Verified off-machine copies use `/srv/backups/aoms-v2/daily` and `/srv/backups/aoms-v2/weekly` on the configured VPS.

## Choose the recovery artifact

Prefer a physical snapshot when the recovery host can run the same AOMS schema and SQLite extensions. It is the fastest and most complete option: canonical records, FTS, vectors, vector profiles, pending embedding work, recall receipts, and authentication state all remain at one point in time.

Use a portable export when moving across an incompatible SQLite environment or when no usable physical generation exists. A portable bundle contains only validated canonical record JSON and recall receipt JSON. Restore creates a fresh schema and rebuilds FTS while inserting records. It does **not** restore vectors, vector profiles, the pending-embedding queue, or authentication tokens. Vectors are derived; `cortex-mem doctor` reports their missing coverage and `cortex-mem backfill` is the supported rebuild. Recreate required bearer tokens separately.

Choose a generation from before the first suspected corruption or bad write. Newer is not safer if it already contains the unwanted state. Preserve the failed store and every newer backup until the incident is understood; wholesale restore intentionally discards writes made after the chosen generation.

## Verify and stage a physical snapshot

Set `artifact` to the selected daily or weekly physical archive. Keep the sidecars in the same directory.

```console
artifact="$HOME/openclaw_archives/aoms-v2/daily/aoms-v2-YYYY-MM-DD.sqlite3.zst"
(cd "$(dirname "$artifact")" && sha256sum -c "$(basename "$artifact").sha256")
zstd -t "$artifact"

scratch=$(mktemp -d /tmp/aoms-v2-recovery.XXXXXX)
mkdir -p "$scratch/data"
zstd -d -c "$artifact" > "$scratch/data/aoms.sqlite3"
cortex-mem doctor --data-dir "$scratch/data"
```

Before running recall, compare the restored counts with the artifact metadata; recall itself adds a receipt to the scratch database.

```console
python - "$artifact.metadata.json" "$scratch/data/aoms.sqlite3" <<'PY'
import json
import sqlite3
import sys

metadata = json.load(open(sys.argv[1], encoding="utf-8"))
with sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True) as connection:
    connection.execute("PRAGMA query_only=ON")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    schema = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_version"
    ).fetchone()[0]
    records = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    receipts = connection.execute(
        "SELECT COUNT(*) FROM recall_receipts"
    ).fetchone()[0]
print(f"integrity={integrity} schema={schema} records={records} receipts={receipts}")
assert integrity == "ok"
assert records == metadata["records"]
assert receipts == metadata["receipts"]
PY
```

`doctor` must accept the schema expected by the installed CLI and report the expected vector coverage. Then exercise the restored FTS and application recall paths without loading a model:

```console
AOMS_EMBEDDING_PROVIDER=none cortex-mem search backup \
  --limit 3 --data-dir "$scratch/data"
AOMS_EMBEDDING_PROVIDER=none \
  AOMS_AGENT_ID=recovery-check \
  AOMS_WORKSPACE="$PWD" \
  cortex-mem recall \
  --task "How should backups be verified and restored?" \
  --budget 500 --format json --data-dir "$scratch/data"
```

A successful search must return real rows, and recall must return at least one `sources` entry from the scratch copy. Use a query known to exist in the recovered corpus if `backup` is not applicable.

## Verify and stage a portable export

```console
artifact="$HOME/openclaw_archives/aoms-v2/weekly/aoms-v2-portable-YYYY-MM-DD.tar.zst"
(cd "$(dirname "$artifact")" && sha256sum -c "$(basename "$artifact").sha256")
zstd -t "$artifact"

scratch=$(mktemp -d /tmp/aoms-v2-portable-recovery.XXXXXX)
tar --zstd -xf "$artifact" -C "$scratch"
bundle="$scratch/aoms-v2-portable-YYYY-MM-DD"

AOMS_EMBEDDING_PROVIDER=none cortex-mem init --data-dir "$scratch/restored"
AOMS_EMBEDDING_PROVIDER=none cortex-mem restore "$bundle" \
  --data-dir "$scratch/restored"
cortex-mem doctor --data-dir "$scratch/restored"
```

`restore` validates the manifest format, both SHA-256 hashes, byte counts, JSON models, line counts, and schema compatibility before it initializes or populates the target. It refuses a non-empty target. Independently prove that the completed database counts equal the manifest:

```console
python - "$bundle/manifest.json" "$scratch/restored/aoms.sqlite3" <<'PY'
import json
import sqlite3
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
with sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True) as connection:
    connection.execute("PRAGMA query_only=ON")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    records = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    receipts = connection.execute(
        "SELECT COUNT(*) FROM recall_receipts"
    ).fetchone()[0]
expected_records = manifest["files"]["records.jsonl"]["records"]
expected_receipts = manifest["files"]["receipts.jsonl"]["records"]
print(
    f"integrity={integrity} records={records}/{expected_records} "
    f"receipts={receipts}/{expected_receipts}"
)
assert integrity == "ok"
assert records == expected_records
assert receipts == expected_receipts
PY
```

The first `doctor` should warn that vector coverage is `0/N` and say `Run: cortex-mem backfill`. After count and FTS validation, rebuild all vectors with the configured local provider:

```console
cortex-mem backfill --data-dir "$scratch/restored"
cortex-mem doctor --data-dir "$scratch/restored"
```

Backfill is resumable. `--max-batches 1` is useful only as a bounded provider/configuration smoke test; it does not complete recovery of a non-empty corpus.

## Cut over after verification

AOMS stdio processes are owned by their MCP clients, so close those clients. Stop any deployed HTTP/Observatory process with its supervisor. Confirm that no process can write the data directory before continuing:

```console
pgrep -af 'cortex-mem (mcp|observe)' || true
```

Set `staged_dir` to the verified physical `data` directory or the verified portable `restored` directory. Checkpoint any scratch WAL after all scratch commands have exited, then quarantine the old directory instead of deleting it:

```console
staged_dir="$scratch/data" # use "$scratch/restored" for a portable recovery
live_dir="${AOMS_DATA_DIR:-$HOME/.local/share/aoms}"
quarantine="${live_dir}.quarantine.$(date -u +%Y%m%dT%H%M%SZ)"
test -f "$staged_dir/aoms.sqlite3"
python - "$staged_dir/aoms.sqlite3" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    result = connection.execute(
        "PRAGMA wal_checkpoint(TRUNCATE)"
    ).fetchone()
print("wal_checkpoint=" + repr(result))
assert result == (0, 0, 0), "staged WAL did not checkpoint cleanly"
PY
if test -d "$live_dir"; then mv -- "$live_dir" "$quarantine"; fi
install -d -m 700 "$live_dir"
install -m 600 "$staged_dir/aoms.sqlite3" "$live_dir/aoms.sqlite3"
```

Restart clients or the service only after the file is installed. Run `cortex-mem doctor`, a known FTS search, and a scoped recall against the replacement. Keep the quarantine until the restored service has passed an observation window and any post-snapshot data loss has been reviewed.

## Incident procedures

### 1. Corrupted local store

Stop writers immediately and do not run migrations or repair commands against the only copy. Record read-only counts if SQLite still opens, quarantine the failed directory, and select the newest **pre-corruption** physical snapshot. Follow the physical staging and cutover procedures above. Fall back to the newest pre-corruption portable export only when physical recovery cannot pass `doctor`.

### 2. Total machine loss using the VPS copy

On the replacement host, install a compatible `cortex-mem`, `zstd`, and `sqlite-vec` environment first. Download one artifact and all sidecars into a new local recovery directory. Daily physical example:

```console
backup_host="${AOMS_BACKUP_VPS:?set AOMS_BACKUP_VPS to user@host}"
mkdir -p "$HOME/openclaw_archives/aoms-v2/daily"
scp "$backup_host:/srv/backups/aoms-v2/daily/aoms-v2-YYYY-MM-DD.sqlite3.zst*" \
  "$HOME/openclaw_archives/aoms-v2/daily/"
```

Portable weekly example:

```console
mkdir -p "$HOME/openclaw_archives/aoms-v2/weekly"
scp "$backup_host:/srv/backups/aoms-v2/weekly/aoms-v2-portable-YYYY-MM-DD.tar.zst*" \
  "$HOME/openclaw_archives/aoms-v2/weekly/"
```

Run the corresponding checksum, staging, count, search, recall, and cutover procedure above. Never install a remote artifact merely because transfer succeeded; the local sidecar check and scratch restore are the recovery proof.

### 3. Accidental bad bulk write

Stop writers so the incident boundary does not move. Record the bad operation's earliest possible timestamp and list local and remote generation metadata. Choose the newest generation completed strictly before that timestamp, then restore it in scratch. Compare representative IDs and counts with the quarantined database before cutover. A whole-store restore rolls back good writes after the selected snapshot too; AOMS does not automatically merge them. Preserve the quarantine and re-import only reviewed, known-good post-snapshot records after the recovered store is live.

## Proven restore drill: 2026-08-24

The following are the real transcripts from the 2026-08-24 daily physical
snapshot and weekly portable export. Random `/tmp` prefixes are shortened to
`<physical>` and `<logical>`. Search and recall record bodies are deliberately
not reproduced because the recovery corpus is private; the commands parsed the
real JSON responses and printed only operational evidence.

### Physical snapshot

Archive verification and `doctor` completed successfully:

```console
$ sha256sum -c aoms-v2-2026-08-24.sqlite3.zst.sha256
aoms-v2-2026-08-24.sqlite3.zst: OK
$ zstd -t aoms-v2-2026-08-24.sqlite3.zst
aoms-v2-2026-08-24.sqlite3.zst: 770330624 bytes
$ zstd -d aoms-v2-2026-08-24.sqlite3.zst -o <physical>/data/aoms.sqlite3
aoms-v2-2026-08-24.sqlite3.zst: 770330624 bytes
$ cortex-mem doctor --data-dir <physical>/data
AOMS doctor 2.0.0
[PASS] Database integrity: SQLite integrity_check returned ok
[PASS] Schema version: 5
[PASS] Memory records: 165347 canonical records
[PASS] Receipt store: available (14 receipts; retention 1000)
[PASS] Embedding queue: 0 pending records
[PASS] Vector coverage: 165347/165347 current records (100.0%)
Doctor finished: 0 failure(s), 0 warning(s).
```

The comparison script opened both SQLite files with `mode=ro`, enabled
`PRAGMA query_only`, loaded `sqlite-vec`, and asserted equality before recall
could add a scratch receipt:

```console
$ python - live.sqlite3 <physical>/data/aoms.sqlite3 <<'PY'
import sqlite3, sqlite_vec, sys

def counts(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        connection.execute("PRAGMA query_only=ON")
        return {
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "schema": connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0],
            "records": connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
            "receipts": connection.execute("SELECT COUNT(*) FROM recall_receipts").fetchone()[0],
            "vectors": connection.execute("SELECT COUNT(*) FROM memory_vectors_384").fetchone()[0],
        }

live, restored = counts(sys.argv[1]), counts(sys.argv[2])
print("live(mode=ro):", live)
print("restored(mode=ro):", restored)
assert restored == live
print("MATCH: integrity, schema, records, receipts, and vectors")
PY
live(mode=ro): {'integrity': 'ok', 'schema': 5, 'records': 165347, 'receipts': 14, 'vectors': 165347}
restored(mode=ro): {'integrity': 'ok', 'schema': 5, 'records': 165347, 'receipts': 14, 'vectors': 165347}
MATCH: integrity, schema, records, receipts, and vectors
```

Real FTS and application recall against the restored database also passed:

```console
$ AOMS_EMBEDDING_PROVIDER=none cortex-mem search backup --limit 3 --format json \
    --data-dir <physical>/data | python -c \
    'import json,sys; d=json.load(sys.stdin); print("returned={} total={} strategy={} scope_filtered={}".format(len(d["items"]),d["total"],d["diagnostics"]["strategy"],d["diagnostics"]["scope_filtered_count"]))'
returned=3 total=831 strategy=fts5 scope_filtered=0
$ AOMS_EMBEDDING_PROVIDER=none AOMS_AGENT_ID=recovery-check \
    AOMS_WORKSPACE=/path/to/cortex-mem cortex-mem recall \
    --task 'How should backups be verified and restored?' --budget 500 \
    --format json --data-dir <physical>/data \
    | python -c \
    'import json,sys; d=json.load(sys.stdin); x=d["diagnostics"]; print("receipt_id="+str(x.get("receipt_id"))); print("sources="+str(len(d["sources"]))); print("token_count="+str(d["token_count"])); print("truncated="+str(d["truncated"])); print("vector_coverage="+str(x.get("vector_coverage")))'
receipt_id=286d85fd-3263-43bc-9993-842e8f93d860
sources=1
token_count=348
truncated=True
vector_coverage=0.0
```

`vector_coverage=0.0` in that final response means lexical-only retrieval was
requested for the smoke test; the preceding doctor output proves that all
stored vectors were present and current.

### Portable bundle

The outer artifact and both payloads matched their recorded SHA-256 values:

```console
$ sha256sum -c aoms-v2-portable-2026-08-24.tar.zst.sha256
aoms-v2-portable-2026-08-24.tar.zst: OK
$ zstd -t aoms-v2-portable-2026-08-24.tar.zst
aoms-v2-portable-2026-08-24.tar.zst: 189347840 bytes
$ sha256sum <logical>/aoms-v2-portable-2026-08-24/{records,receipts}.jsonl
456ccb4dbb2d4c25a12a7389aeb3908fcda249e6e1e67e6b22e57e7fdd22f442  <logical>/aoms-v2-portable-2026-08-24/records.jsonl
efe9c26180e24b1fa580bc163dc644afab0e0444c93ad3e41f397e6f8b51a224  <logical>/aoms-v2-portable-2026-08-24/receipts.jsonl
```

The manifest recorded schema 5, 189,032,959 bytes and 165,347 lines for
`records.jsonl`, plus 310,033 bytes and 14 lines for `receipts.jsonl`. The
physical archive SHA-256 was
`7750b3b284c480cfd968b9f5e204c1da807787f8e6d29a97488707bb4ef1fa77`;
the portable archive SHA-256 was
`d7726032d09b8a0bfd5d8e40519c4039f141985b2e1abd9944fe717131c81d9f`.

The empty target was initialized and the fully validated bundle restored. This
drill also caught and fixed a scale defect in the restore implementation: the
old path issued a full-scan FTS delete before every insert despite having
already proved that the target was empty. Restore now uses insert-only batches,
which also refuses duplicate IDs instead of silently upserting them.

```console
$ AOMS_EMBEDDING_PROVIDER=none cortex-mem init --data-dir <logical>/restored
Created AOMS data directory: <logical>/restored
SQLite store ready (schema 5): <logical>/restored/aoms.sqlite3
Embeddings are disabled; search and recall will use lexical retrieval.
$ AOMS_EMBEDDING_PROVIDER=none cortex-mem restore \
    <logical>/aoms-v2-portable-2026-08-24 --batch-size 10000 \
    --data-dir <logical>/restored
Restored 165347 record(s) and 14 receipt(s) into <logical>/restored/aoms.sqlite3. Run `cortex-mem backfill` to rebuild vectors.
```

An independent verifier recalculated both hashes, byte counts, and line counts,
then opened the restored database read-only and checked integrity, schema,
canonical, receipt, and FTS counts against the manifest:

```console
$ python - <<'PY'  # manifest/payload/database verifier
receipts.jsonl: bytes=310033 records=14 sha256=efe9c26180e24b1fa580bc163dc644afab0e0444c93ad3e41f397e6f8b51a224 MATCH
records.jsonl: bytes=189032959 records=165347 sha256=456ccb4dbb2d4c25a12a7389aeb3908fcda249e6e1e67e6b22e57e7fdd22f442 MATCH
database: integrity=ok schema=5 records=165347 receipts=14 fts=165347
derived state: vector_profiles=0 embedding_pending=0 auth_tokens=0
```

As expected for a portable restore, doctor identified missing derived vectors
and prescribed backfill. A bounded real run with the cached local FastEmbed
model proved the remedy without a cloud model call; the second doctor showed
exactly the 64 vectors produced by that single batch:

```console
$ cortex-mem doctor --data-dir <logical>/restored
[PASS] Database integrity: SQLite integrity_check returned ok
[PASS] Schema version: 5
[PASS] Memory records: 165347 canonical records
[PASS] Receipt store: available (14 receipts; retention 1000)
[PASS] Embedding queue: 0 pending records
[WARN] Vector coverage: 0/165347 current records (0.0%)
       Action: Run: cortex-mem backfill
Doctor finished: 0 failure(s), 1 warning(s).
$ cortex-mem backfill --max-batches 1 --data-dir <logical>/restored
Catching up embeddings ...
  scanning: scanned=64 queued=64 embedded=0 failed=0 pending=64
  embedding: scanned=64 queued=64 embedded=64 failed=0 pending=0
  interrupted: scanned=64 queued=64 embedded=64 failed=0 pending=0
Backfill finished: scanned=64 queued=64 embedded=64 failed=0 pending=0.
$ cortex-mem doctor --data-dir <logical>/restored | tail -8
[PASS] Receipt store: available (14 receipts; retention 1000)
[PASS] Embedding queue: 0 pending records
[WARN] Vector coverage: 64/165347 current records (0.0%)
       Action: Run: cortex-mem backfill
Doctor finished: 0 failure(s), 1 warning(s).
```

Finally, the rebuilt FTS path returned the same real query count as the
physical copy: `returned=3 total=831 strategy=fts5 scope_filtered=0`.

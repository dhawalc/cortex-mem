# AOMS v2 schema 6 migration

Schema 6 rebuilds the FTS5 table so that every `memories_fts.rowid` is the
same as the corresponding `memories.rowid`. Future writes can then delete the
old FTS row by its integer rowid instead of scanning the FTS table's
`UNINDEXED` text `id` column.

**Important:** this migration is automatic. After schema-6 code is deployed,
the next client that opens the writable store runs it during repository
initialization. Take and verify the pre-migration backup before deploying or
opening the store with that code if the change must happen in a deliberate
maintenance window.

## What migration 6 does

1. It builds a temporary source table keyed by canonical `memories.rowid`.
   Existing FTS payload is copied without re-normalizing it, so structured
   content, tags, kind, query IDs, and BM25 scores are preserved.
2. Missing canonical FTS rows are reconstructed from `memories.record_json`,
   and orphan FTS rows are not carried forward.
3. It checks that the staged row count equals the memory count and that every
   staged ID agrees with its canonical rowid.
4. It starts `BEGIN IMMEDIATE`, atomically drops and recreates `memories_fts`,
   loads the staged rows with their canonical rowids, and records schema 6.
   An interruption rolls this transaction back; initialization can retry it.

The temporary source is built before `BEGIN IMMEDIATE`, so the old FTS index
remains available during staging. In WAL mode, readers can continue while the
atomic swap holds the write lock, but other writers wait. Operators should
still quiesce writers so client timeouts and competing initialization attempts
cannot complicate the maintenance window.

The write-path benchmark at 165k rows improved from **12.985 records/s** to
**3,914.8 records/s** (301x). The original rehearsal took about 4.9 seconds
and increased the database file by about 0.32%.

On a fresh online backup of the 165,347-row canonical store on 2026-08-24,
the migration took **4.820 seconds**. The interval from `BEGIN IMMEDIATE` until
the migration returned was **3.753 seconds** (3.305 seconds until the commit
call, plus commit completion). The main database grew from 770,330,624 to
772,837,376 bytes: 2,506,752 bytes, or **0.325%**. The `-shm` file is transient
and is not part of that durable-size comparison.

The rehearsal preserved these counts:

- memories and FTS rows: 165,347 each;
- 384-dimensional vectors: 165,347;
- recall receipts: 14;
- vector profiles: 1; and
- pending embeddings and auth tokens: 0 each.

`PRAGMA integrity_check` returned `ok` before and after. Complete ordered IDs
and exact raw BM25 values were identical for `openclaw` (49,597 results),
`sqlite` (1,128), and `backup` (831). The rehearsal copy remains at
`/tmp/aoms-schema6-rehearsal.THuQ6q/aoms.sqlite3` for short-term inspection.

## Deliberate operator procedure

Use the production scheduler environment so the backup job has its configured
VPS destination. Do not copy a live WAL database with `cp`, `rsync`, or `tar`.

1. Close or pause every client that can write AOMS. Do this before schema-6
   code can open the store.
2. Run the installed SQLite-safe backup job and require a successful exit:

   ```console
   ~/.openclaw/workspace/scripts/backup-aoms-v2.sh
   tail -n 40 ~/.openclaw/workspace/logs/backup-aoms-v2.log
   ```

   The final log line must say `AOMS v2 backup complete`. The same run verifies
   SQLite integrity, compressed-stream readability, local SHA-256 and metadata,
   and the uploaded VPS hash. If today's generation already exists, the script
   verifies it rather than overwriting it.
3. Independently verify the selected pre-migration daily generation and retain
   its date for rollback:

   ```console
   python_bin="${AOMS_PYTHON:?set AOMS_PYTHON to the deployed v2 interpreter}"
   cli_bin="${AOMS_CLI:?set AOMS_CLI to the deployed cortex-mem executable}"
   snapshot="$HOME/openclaw_archives/aoms-v2/daily/aoms-v2-$(date +%F).sqlite3.zst"
   test -s "$snapshot"
   test -s "$snapshot.sha256"
   test -s "$snapshot.metadata.json"
   (cd "$(dirname "$snapshot")" && sha256sum -c "$(basename "$snapshot").sha256")
   zstd -t "$snapshot"
   "$python_bin" - "$snapshot.metadata.json" <<'PY'
   import json
   import sys

   metadata = json.load(open(sys.argv[1], encoding="utf-8"))
   assert metadata["integrity_check"] == "ok"
   assert metadata["records"] >= 0
   assert metadata["receipts"] >= 0
   print(metadata)
   PY
   ```

4. Apply schema 6 explicitly, with model loading disabled:

   ```console
   AOMS_EMBEDDING_PROVIDER=none \
     "$cli_bin" init \
     --data-dir "$HOME/.local/share/aoms"
   ```

   Expect `SQLite store ready (schema 6)`. Allow at least 30 seconds for the
   observed sub-five-second migration and lock wait; do not interrupt it merely
   because another writer is waiting.
5. Verify before resuming clients:

   ```console
   AOMS_EMBEDDING_PROVIDER=none \
     "$cli_bin" doctor \
     --data-dir "$HOME/.local/share/aoms"

   "$python_bin" - \
     "$HOME/.local/share/aoms/aoms.sqlite3" <<'PY'
   import sqlite3
   import sys
   import sqlite_vec

   with sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True) as connection:
       connection.enable_load_extension(True)
       sqlite_vec.load(connection)
       connection.enable_load_extension(False)
       connection.execute("PRAGMA query_only=ON")
       integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
       schema = connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
       memories = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
       fts = connection.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
       bad = connection.execute(
           "SELECT COUNT(*) FROM memories AS m "
           "LEFT JOIN memories_fts AS f ON f.rowid=m.rowid "
           "WHERE f.rowid IS NULL OR f.id<>m.id"
       ).fetchone()[0]
   print(f"integrity={integrity} schema={schema} memories={memories} fts={fts} bad_rowids={bad}")
   assert integrity == "ok"
   assert schema == 6
   assert memories == fts
   assert bad == 0
   PY
   ```

6. Run known lexical searches (including `openclaw`, `sqlite`, and `backup`),
   confirm expected records are returned, then resume clients and watch logs
   for `database is locked`, initialization, FTS, or integrity errors.

## Rollback

Restore the retained pre-migration daily physical snapshot by following
[AOMS disaster recovery](RECOVERY.md#verify-and-stage-a-physical-snapshot) and
its [verified cutover procedure](RECOVERY.md#cut-over-after-verification).
Stage and checksum the archive in a new `/tmp` directory, verify integrity and
metadata counts there, stop every writer, quarantine the current data directory,
and install the staged `aoms.sqlite3`; never extract over the live directory.

Also restore the last known-good **pre-schema-6 client build before any client
opens the restored schema-5 store**. If schema-6 code remains installed, its
next writable open automatically reapplies migration 6 and defeats the
rollback. Keep both the quarantined post-migration directory and the selected
daily snapshot until the rollback observation window is complete.

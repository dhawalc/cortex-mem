# AOMS backup operations

This deployment has two live storage generations during the v1-to-v2 transition. The jobs below are intentionally separate: the first two protect the still-running legacy v1 store, while the third protects the canonical v2 SQLite store. A successful run of one job says nothing about the other store.

## Installed jobs

| Time (Pacific) | Job | Store covered | Recovery role |
|---|---|---|---|
| 04:00 daily | `~/.openclaw/workspace/scripts/backup-to-vps.sh` | Legacy v1 `cortex-mem/modules/memory`, its index, and selected OpenClaw state | Current-state VPS mirror. It uses `rsync --delete`, so it is not corruption history. |
| 04:30 daily | `~/.openclaw/workspace/scripts/backup-aoms-versioned.sh` | Legacy v1 `cortex-mem/modules/memory` | Dated v1 archives: seven local generations and three VPS generations. |
| 04:45 daily | `~/.openclaw/workspace/scripts/backup-aoms-v2.sh` | Canonical v2 `~/.local/share/aoms/aoms.sqlite3`, including SQLite tables, FTS, sqlite-vec vectors, the embedding queue, auth state, and recall receipts | SQLite online snapshot every day; weekly physical snapshot plus portable `cortex-mem export`; verified local and VPS generations. |

The v2 job is shipped as [`packaging/ops/backup-aoms-v2.sh`](../../packaging/ops/backup-aoms-v2.sh). Its default deployment paths can be overridden with the `AOMS_*` environment variables at the top of the script.

## v2 safety and retention

The v2 database runs in WAL mode. Never copy the live `aoms.sqlite3` file with `cp`, `tar`, or `rsync`: committed pages may still be in `aoms.sqlite3-wal`, and the result can be an inconsistent point in time. The v2 script opens the source with SQLite `mode=ro` and `query_only`, uses Python's `sqlite3.Connection.backup()` API, and compresses only the completed destination database.

Every physical snapshot must pass `PRAGMA integrity_check`, a compressed-stream test, and a SHA-256 check. The VPS copy is hashed again after upload. On Sundays, the same verified point-in-time snapshot is also exported with `cortex-mem export`; the script verifies the manifest hashes, byte counts, and row counts before archiving and transferring the bundle. `AOMS_EMBEDDING_PROVIDER=none` prevents backup operations from loading or running an embedding model.

Retention is:

- physical daily snapshots: newest 7 local, newest 3 on the VPS;
- weekly physical snapshots: newest 4 local and newest 4 on the VPS; and
- weekly portable exports: newest 4 local and newest 4 on the VPS.

The job is guarded by `flock`, lowers its process priority, writes partial artifacts before atomic rename, refuses to overwrite an incomplete same-day generation, and logs to `~/.openclaw/workspace/logs/backup-aoms-v2.log`.

## Recovery drills

Physical recovery is the fastest path and preserves the vector tables. Restore into a new directory, never over the live store:

```console
scratch=$(mktemp -d /tmp/aoms-v2-restore.XXXXXX)
mkdir -p "$scratch/data"
zstd -d -c ~/openclaw_archives/aoms-v2/daily/aoms-v2-YYYY-MM-DD.sqlite3.zst \
  > "$scratch/data/aoms.sqlite3"
cortex-mem doctor --data-dir "$scratch/data"
sqlite3 "$scratch/data/aoms.sqlite3" 'SELECT COUNT(*) FROM memories;'
```

Logical recovery is slower and rebuilds vectors, but it is independent of SQLite's physical representation:

```console
scratch=$(mktemp -d /tmp/aoms-v2-portable-restore.XXXXXX)
tar --zstd -xf \
  ~/openclaw_archives/aoms-v2/weekly/aoms-v2-portable-YYYY-MM-DD.tar.zst \
  -C "$scratch"
cortex-mem restore "$scratch/aoms-v2-portable-YYYY-MM-DD" \
  --data-dir "$scratch/restored"
cortex-mem doctor --data-dir "$scratch/restored"
# Rebuild vectors only after validating the record and receipt counts:
cortex-mem backfill --data-dir "$scratch/restored"
```

Do not run `backfill` during a routine drill: it is a real embedding/model operation. The archive manifest is validated by `restore` before the fresh target is populated.

## Legacy retirement plan

Keep both v1 jobs while any process can still write the legacy store. Retire them only after all of the following are true:

1. v1 writers and readers have been removed from service configuration and a full observation window shows no new v1 writes;
2. a final dated v1 archive has been created, copied off-host, checksum-verified, and restored in a drill;
3. all required v1 data has either been migrated into v2 or explicitly classified as archive-only; and
4. the operator records the final v1 generation and retention deadline.

At that point, remove the 04:00 and 04:30 crontab entries, but retain the final verified v1 archive through the agreed archival period. Do not repurpose either legacy script to copy the live v2 WAL database.

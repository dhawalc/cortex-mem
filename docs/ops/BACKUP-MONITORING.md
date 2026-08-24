# Backup monitoring

The AOMS v2 store is backed up nightly by `~/.openclaw/workspace/scripts/backup-aoms-v2.sh`.
That job has failed silently before: for months it snapshotted a database that
was no longer the live one, and nothing ever compared the two. This watchdog
exists so that particular silence cannot happen again.

## Running it

```bash
cortex-mem backup-status              # human-readable, contacts the backup host
cortex-mem backup-status --json       # machine-readable
cortex-mem backup-status --skip-remote  # local checks only, no ssh
```

The same checks run from a standalone script that needs no installed CLI, which
is what cron uses:

```bash
scripts/aoms-backup-status.py [--json] [--strict] [--skip-remote] [--alert-file PATH]
```

Both entry points share one implementation, so the scheduled check and the
interactive one cannot drift apart about what "healthy" means.

## What is checked

| Check | PASS when | Threshold and why |
|---|---|---|
| Backup schedule | An active crontab entry invokes `backup-aoms-v2.sh` | No schedule means no new artifact will ever appear, however healthy today's looks |
| Daily artifact | The newest daily snapshot is younger than 26 hours | 24h cadence plus 2h slack for a long run, a late cron start, and the daylight-saving shift |
| Daily checksum | The artifact's bytes hash to the digest in its `.sha256` sidecar | Recomputed in full; catches truncation and bit rot, not just a missing file |
| Backup source | `metadata.json` records `source_database` equal to the live store, with `integrity_check=ok` | Exact match, no tolerance. This is the direct guard against backing up the wrong database |
| Record count | The backup's record count is within tolerance of the live store's | WARN past `max(500, 2%)`, FAIL past `max(5000, 10%)`. A snapshot is a point in time, so a busy store runs slightly ahead; a large gap means the two are not the same store |
| Remote copy | The same-named artifact exists on the backup host and hashes identically | Compares the off-site copy rather than trusting that the upload was attempted |
| Weekly export | The newest portable export is younger than 8 days | Weekly cadence (Sundays) plus one day of slack |
| Backup log | The last decisive line in the log is `AOMS v2 backup complete` | An earlier `ERROR:` followed by a later success is healthy; only the last outcome counts |

## Where the configuration comes from

The watchdog resolves each path in this order, and reports which source won in
the `resolved_from` block of `--json`:

1. an explicit `--backup-root` / `--live-db` flag
2. an `AOMS_*` environment variable
3. **the crontab entry that actually invokes `backup-aoms-v2.sh`**
4. the script's own default

Step 3 matters. The backup script defaults its remote directory to
`/srv/backups/aoms-v2`, but the cron entry overrides it to
`/root/backups/aoms-v2` — and that is where the backups really are. A watchdog
that checked the documented path would have inspected an empty directory and
reported on a backup that was not there. Reading the cron line keeps the
checker pointed at whatever the job is actually doing.

## What each state means

**PASS** — the chain is intact: fresh, verified, off-site, and taken from the
live store. Exit code 0.

**WARN** — something could not be verified, but nothing is known to be broken.
Exit code 0 by default, or 1 with `--strict`. The common causes are a backup
host that is unreachable right now, `--skip-remote`, a live store that could not
be opened, and record drift past the warn threshold but well inside the fail
threshold. A WARN that persists for more than a day or two should be treated as
a FAIL: an off-site copy nobody has verified in a week is not an off-site copy.

**FAIL** — a specific, named condition is broken. Exit code 1. The output names
the failing condition and the exact command that fixes it; there is no
"something is wrong" state. Every FAIL is actionable as printed.

## Responding to a failure

Read the `Fix:` line under the failing check and run it — it is written with the
resolved paths and the remote host already filled in. The usual remedy is to
re-run the backup by hand:

```bash
AOMS_BACKUP_VPS=root@178.156.239.16 AOMS_BACKUP_VPS_DIR=/root/backups/aoms-v2 \
  ~/.openclaw/workspace/scripts/backup-aoms-v2.sh
```

Two failures deserve more than a re-run:

- **Backup source mismatch** — the job is snapshotting a different database than
  the one being written to. Re-running only produces another useless backup.
  Fix the `AOMS_DB_PATH` in the cron entry first, then re-run. This is the
  failure that went unnoticed for months.
- **Record count FAIL with a fresh artifact** — the snapshot is recent but does
  not resemble the live store. Compare the counts directly before touching
  anything; if the live store has *fewer* records than the backup, the live
  store may have been truncated or replaced, and the backup is the good copy.
  Do not overwrite it by running a new backup until you know which is which.

## Scheduling

```
15 8 * * * /home/dhawal/cortex-mem/cortex-mem/.venv/bin/python \
  /home/dhawal/cortex-mem/aoms-v2/scripts/aoms-backup-status.py \
  --alert-file /home/dhawal/.openclaw/workspace/logs/ALERT_backup_status.txt \
  >> /home/dhawal/.openclaw/workspace/logs/backup-status.log 2>&1
```

It runs at 08:15 PT, half an hour after the 04:45 backup and alongside the 08:00
daily health check, as a separate entry so it keeps its own log and its own exit
code.

`--alert-file` is what makes a failure hard to miss: on FAIL the full report is
written to `ALERT_backup_status.txt`, and the file is deleted again as soon as
the chain is healthy. The presence of that file means the backups are broken
right now, which is cheap for a human or another health check to notice — a log
line appended to a file nobody reads is how the last silent failure lasted
months.

## Testing

`tests/v2/test_backup_status.py` builds each scenario on disk and stubs the
backup host, so the suite needs no network and never touches the real archives.
Covered: fresh and stale artifacts on both sides of each threshold, checksum
mismatch, a sidecar naming a different file, record drift in both directions, a
snapshot of the wrong database, an unreachable host (WARN) versus a reachable
host with a missing or divergent copy (FAIL), a log ending in `ERROR:`, a
recovered log, a missing cron entry, and the alert file's write-and-clear cycle.

#!/usr/bin/env bash
# SQLite-safe, versioned backups for the canonical AOMS v2 store.
#
# Daily: a physical SQLite snapshot, retained 7 locally and 3 on the VPS.
# Weekly (Sunday, or AOMS_FORCE_WEEKLY=1): a physical generation and a
# portable cortex-mem export, retained 4 locally and 4 on the VPS.
set -Eeuo pipefail
umask 077

DATA_DIR="${AOMS_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/aoms}"
LIVE_DB="${AOMS_DB_PATH:-$DATA_DIR/aoms.sqlite3}"
BACKUP_ROOT="${AOMS_BACKUP_DIR:-$HOME/openclaw_archives/aoms-v2}"
LOG_DIR="${AOMS_BACKUP_LOG_DIR:-$HOME/.openclaw/workspace/logs}"
LOG_FILE="${AOMS_BACKUP_LOG_FILE:-$LOG_DIR/backup-aoms-v2.log}"
LOCK_FILE="${AOMS_BACKUP_LOCK_FILE:-${XDG_CACHE_HOME:-$HOME/.cache}/aoms-backup-v2.lock}"
PYTHON="${AOMS_PYTHON:-python3}"
CLI="${AOMS_CLI:-cortex-mem}"
ZSTD="${AOMS_ZSTD:-zstd}"
VPS="${AOMS_BACKUP_VPS:-}"
VPS_ROOT="${AOMS_BACKUP_VPS_DIR:-/srv/backups/aoms-v2}"
LOCAL_DAILY_KEEP="${AOMS_LOCAL_DAILY_KEEP:-7}"
REMOTE_DAILY_KEEP="${AOMS_REMOTE_DAILY_KEEP:-3}"
WEEKLY_KEEP="${AOMS_WEEKLY_KEEP:-4}"
STAMP="${AOMS_BACKUP_DATE:-$(date +%F)}"
SSH_OPTIONS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

mkdir -p "$LOG_DIR" "$(dirname "$LOCK_FILE")"
if [[ "${AOMS_BACKUP_TEE:-0}" == "1" ]]; then
    exec > >(tee -a "$LOG_FILE") 2>&1
else
    exec >>"$LOG_FILE" 2>&1
fi

log() {
    printf '[%s] %s\n' "$(date '+%F %T %z')" "$*"
}

die() {
    log "ERROR: $*"
    exit 1
}

for value in "$LOCAL_DAILY_KEEP" "$REMOTE_DAILY_KEEP" "$WEEKLY_KEEP"; do
    [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "retention values must be positive integers"
done
[[ -n "$VPS" ]] || die "AOMS_BACKUP_VPS must name the remote backup host"
[[ "$VPS" =~ ^[A-Za-z0-9._@:-]+$ ]] || die "unsafe VPS value: $VPS"
[[ "$VPS_ROOT" =~ ^/[A-Za-z0-9._/-]+$ && "$VPS_ROOT" != "/" ]] || \
    die "VPS backup directory must be a safe absolute non-root path"
[[ "$STAMP" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || \
    die "backup date must use YYYY-MM-DD: $STAMP"
[[ "$(date -d "$STAMP" +%F 2>/dev/null)" == "$STAMP" ]] || \
    die "backup date is not a real calendar date: $STAMP"

command -v "$PYTHON" >/dev/null || die "Python interpreter not found: $PYTHON"
command -v "$CLI" >/dev/null || die "cortex-mem CLI not found: $CLI"
command -v "$ZSTD" >/dev/null || die "zstd not found: $ZSTD"
command -v flock >/dev/null || die "flock not found"
command -v rsync >/dev/null || die "rsync not found"
command -v ssh >/dev/null || die "ssh not found"
[[ -r "$LIVE_DB" ]] || die "canonical database is not readable: $LIVE_DB"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another AOMS v2 backup owns $LOCK_FILE; exiting without overlap"
    exit 0
fi

# Lower this process and every child to background priority. This is harmless
# when cron has already invoked the script through nice(1).
renice 10 -p "$$" >/dev/null 2>&1 || true

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/aoms-v2-backup.XXXXXX")"
cleanup() {
    rm -rf -- "$TMP_ROOT"
}
trap cleanup EXIT
trap 'die "backup failed at line $LINENO"' ERR

DAILY_DIR="$BACKUP_ROOT/daily"
WEEKLY_DIR="$BACKUP_ROOT/weekly"
mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

DAILY_NAME="aoms-v2-$STAMP.sqlite3.zst"
DAILY_ARCHIVE="$DAILY_DIR/$DAILY_NAME"
DAILY_META="$DAILY_ARCHIVE.metadata.json"
DAILY_SUM="$DAILY_ARCHIVE.sha256"
SNAPSHOT_DIR="$TMP_ROOT/snapshot"
SNAPSHOT_DB="$SNAPSHOT_DIR/aoms.sqlite3"
mkdir -p "$SNAPSHOT_DIR"

verify_checksum() {
    local artifact="$1"
    local checksum="$artifact.sha256"
    [[ -s "$artifact" && -s "$checksum" ]] || return 1
    (cd "$(dirname "$artifact")" && sha256sum -c "$(basename "$checksum")")
}

verify_metadata() {
    "$PYTHON" - "$1" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

artifact = Path(sys.argv[1])
metadata_path = Path(f"{artifact}.metadata.json")
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
digest = hashlib.sha256()
with artifact.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
if metadata.get("artifact") != artifact.name:
    raise SystemExit("metadata artifact name mismatch")
if metadata.get("sha256") != digest.hexdigest():
    raise SystemExit("metadata artifact hash mismatch")
if metadata.get("integrity_check") != "ok":
    raise SystemExit("metadata does not record a successful integrity check")
for field in ("records", "receipts"):
    if not isinstance(metadata.get(field), int) or metadata[field] < 0:
        raise SystemExit(f"metadata {field} is invalid")
print(f"metadata=ok artifact={artifact.name}")
PY
}

verify_sqlite_file() {
    "$PYTHON" - "$1" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise SystemExit(f"integrity_check failed: {integrity}")
    records = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    receipts = connection.execute("SELECT COUNT(*) FROM recall_receipts").fetchone()[0]
print(f"integrity_check=ok records={records} receipts={receipts}")
PY
}

verify_export_bundle() {
    "$PYTHON" - "$1" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

bundle = Path(sys.argv[1])
manifest_path = bundle / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("format") != "aoms-portable-export" or manifest.get("format_version") != 1:
    raise SystemExit("unsupported portable export manifest")
for name in ("records.jsonl", "receipts.jsonl"):
    path = bundle / name
    entry = manifest["files"][name]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != entry["sha256"]:
        raise SystemExit(f"manifest hash mismatch for {name}")
    if path.stat().st_size != entry["bytes"]:
        raise SystemExit(f"manifest byte count mismatch for {name}")
    with path.open("rb") as handle:
        rows = sum(1 for _ in handle)
    if rows != entry["records"]:
        raise SystemExit(f"manifest record count mismatch for {name}")
print(
    "manifest_hashes=ok "
    f"records={manifest['files']['records.jsonl']['records']} "
    f"receipts={manifest['files']['receipts.jsonl']['records']}"
)
PY
}

write_metadata() {
    local destination="$1"
    local kind="$2"
    local verified_db="$3"
    local artifact="$4"
    "$PYTHON" - "$destination" "$kind" "$verified_db" "$artifact" "$LIVE_DB" <<'PY'
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

destination = Path(sys.argv[1])
kind = sys.argv[2]
verified_db = Path(sys.argv[3])
artifact = Path(sys.argv[4])
source_db = Path(sys.argv[5])
with sqlite3.connect(f"file:{verified_db}?mode=ro", uri=True) as connection:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    records = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    receipts = connection.execute("SELECT COUNT(*) FROM recall_receipts").fetchone()[0]
digest = hashlib.sha256()
with artifact.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
metadata = {
    "artifact": artifact.name,
    "backup_kind": kind,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "integrity_check": integrity,
    "records": records,
    "receipts": receipts,
    "sha256": digest.hexdigest(),
    "source_database": str(source_db),
}
destination.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

create_snapshot() {
    log "creating SQLite online backup from $LIVE_DB"
    "$PYTHON" - "$LIVE_DB" "$SNAPSHOT_DB" <<'PY'
import sqlite3
import sys

source_path, destination_path = sys.argv[1:]
source_uri = f"file:{source_path}?mode=ro"
with sqlite3.connect(source_uri, uri=True, timeout=60) as source:
    source.execute("PRAGMA query_only=ON")
    with sqlite3.connect(destination_path) as destination:
        source.backup(destination, pages=8192, sleep=0.050)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SystemExit(f"snapshot integrity_check failed: {integrity}")
        records = destination.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        receipts = destination.execute("SELECT COUNT(*) FROM recall_receipts").fetchone()[0]
print(f"SQLite backup complete: integrity_check=ok records={records} receipts={receipts}")
PY

    local partial="$DAILY_ARCHIVE.partial"
    "$ZSTD" -T0 -q -f "$SNAPSHOT_DB" -o "$partial"
    "$ZSTD" -q -t "$partial"
    mv "$partial" "$DAILY_ARCHIVE"
    (cd "$DAILY_DIR" && sha256sum "$DAILY_NAME" >"$DAILY_NAME.sha256")
    write_metadata "$DAILY_META" "daily-physical" "$SNAPSHOT_DB" "$DAILY_ARCHIVE"
    verify_checksum "$DAILY_ARCHIVE"
    verify_metadata "$DAILY_ARCHIVE"
    log "created $DAILY_ARCHIVE ($(du -h "$DAILY_ARCHIVE" | cut -f1))"
}

if [[ -e "$DAILY_ARCHIVE" || -e "$DAILY_META" || -e "$DAILY_SUM" ]]; then
    [[ -s "$DAILY_ARCHIVE" && -s "$DAILY_META" && -s "$DAILY_SUM" ]] || \
        die "incomplete existing daily generation for $STAMP; refusing to overwrite"
    "$ZSTD" -q -t "$DAILY_ARCHIVE"
    verify_checksum "$DAILY_ARCHIVE"
    verify_metadata "$DAILY_ARCHIVE"
    log "verified existing daily generation $DAILY_ARCHIVE"
else
    create_snapshot
fi

ensure_snapshot_db() {
    if [[ ! -s "$SNAPSHOT_DB" ]]; then
        "$ZSTD" -q -d -c "$DAILY_ARCHIVE" >"$SNAPSHOT_DB"
    fi
    verify_sqlite_file "$SNAPSHOT_DB"
}

remote_prepare() {
    ssh "${SSH_OPTIONS[@]}" "$VPS" \
        "mkdir -p '$VPS_ROOT/daily' '$VPS_ROOT/weekly'"
}

remote_upload_verified() {
    local artifact="$1"
    local remote_subdir="$2"
    local checksum="$artifact.sha256"
    local metadata="$artifact.metadata.json"
    local remote_dir="$VPS_ROOT/$remote_subdir"
    local checksum_name
    checksum_name="$(basename "$checksum")"
    rsync -az --partial -e "ssh ${SSH_OPTIONS[*]}" \
        "$artifact" "$checksum" "$metadata" "$VPS:$remote_dir/"
    ssh "${SSH_OPTIONS[@]}" "$VPS" \
        "cd '$remote_dir' && sha256sum -c '$checksum_name'"
    log "uploaded and checksum-verified $(basename "$artifact") on $VPS"
}

prune_local() {
    local directory="$1"
    local pattern="$2"
    local keep="$3"
    local -a expired=()
    mapfile -t expired < <(
        find "$directory" -maxdepth 1 -type f -name "$pattern" -printf '%f\n' \
            | sort -r | tail -n "+$((keep + 1))"
    )
    local name
    for name in "${expired[@]}"; do
        rm -f -- "$directory/$name" "$directory/$name.sha256" \
            "$directory/$name.metadata.json"
        log "pruned expired local generation $directory/$name"
    done
}

prune_remote() {
    local remote_subdir="$1"
    local pattern="$2"
    local keep="$3"
    ssh "${SSH_OPTIONS[@]}" "$VPS" bash -s -- \
        "$VPS_ROOT/$remote_subdir" "$pattern" "$keep" <<'REMOTE'
set -euo pipefail
directory=$1
pattern=$2
keep=$3
mapfile -t expired < <(
    find "$directory" -maxdepth 1 -type f -name "$pattern" -printf '%f\n' \
        | sort -r | tail -n "+$((keep + 1))"
)
for name in "${expired[@]}"; do
    rm -f -- "$directory/$name" "$directory/$name.sha256" \
        "$directory/$name.metadata.json"
done
REMOTE
}

remote_prepare
remote_upload_verified "$DAILY_ARCHIVE" "daily"

weekly_due=0
if [[ "$(date -d "$STAMP" +%u)" == "7" || "${AOMS_FORCE_WEEKLY:-0}" == "1" ]]; then
    weekly_due=1
fi

if (( weekly_due )); then
    WEEKLY_PHYSICAL_NAME="aoms-v2-weekly-$STAMP.sqlite3.zst"
    WEEKLY_PHYSICAL="$WEEKLY_DIR/$WEEKLY_PHYSICAL_NAME"
    if [[ -e "$WEEKLY_PHYSICAL" || -e "$WEEKLY_PHYSICAL.sha256" || \
        -e "$WEEKLY_PHYSICAL.metadata.json" ]]; then
        [[ -s "$WEEKLY_PHYSICAL" && -s "$WEEKLY_PHYSICAL.sha256" && \
            -s "$WEEKLY_PHYSICAL.metadata.json" ]] || \
            die "incomplete existing weekly physical generation for $STAMP; refusing to overwrite"
    else
        ln "$DAILY_ARCHIVE" "$WEEKLY_PHYSICAL" 2>/dev/null || cp "$DAILY_ARCHIVE" "$WEEKLY_PHYSICAL"
        (cd "$WEEKLY_DIR" && sha256sum "$WEEKLY_PHYSICAL_NAME" >"$WEEKLY_PHYSICAL_NAME.sha256")
        ensure_snapshot_db
        write_metadata "$WEEKLY_PHYSICAL.metadata.json" "weekly-physical" \
            "$SNAPSHOT_DB" "$WEEKLY_PHYSICAL"
    fi
    "$ZSTD" -q -t "$WEEKLY_PHYSICAL"
    verify_checksum "$WEEKLY_PHYSICAL"
    verify_metadata "$WEEKLY_PHYSICAL"
    remote_upload_verified "$WEEKLY_PHYSICAL" "weekly"

    EXPORT_NAME="aoms-v2-portable-$STAMP.tar.zst"
    EXPORT_ARCHIVE="$WEEKLY_DIR/$EXPORT_NAME"
    EXPORT_META="$EXPORT_ARCHIVE.metadata.json"
    EXPORT_SUM="$EXPORT_ARCHIVE.sha256"
    BUNDLE_DIR="$TMP_ROOT/aoms-v2-portable-$STAMP"
    if [[ -e "$EXPORT_ARCHIVE" || -e "$EXPORT_META" || -e "$EXPORT_SUM" ]]; then
        [[ -s "$EXPORT_ARCHIVE" && -s "$EXPORT_META" && -s "$EXPORT_SUM" ]] || \
            die "incomplete existing portable generation for $STAMP; refusing to overwrite"
        "$ZSTD" -q -t "$EXPORT_ARCHIVE"
        verify_checksum "$EXPORT_ARCHIVE"
        mkdir -p "$TMP_ROOT/export-check"
        tar --zstd -xf "$EXPORT_ARCHIVE" -C "$TMP_ROOT/export-check"
        verify_export_bundle "$TMP_ROOT/export-check/aoms-v2-portable-$STAMP"
        log "verified existing portable generation $EXPORT_ARCHIVE"
    else
        ensure_snapshot_db
        log "creating portable cortex-mem export from the verified SQLite snapshot"
        AOMS_EMBEDDING_PROVIDER=none "$CLI" export "$BUNDLE_DIR" \
            --data-dir "$SNAPSHOT_DIR"
        verify_export_bundle "$BUNDLE_DIR"
        local_export_partial="$EXPORT_ARCHIVE.partial"
        tar --zstd -cf "$local_export_partial" -C "$TMP_ROOT" \
            "aoms-v2-portable-$STAMP"
        "$ZSTD" -q -t "$local_export_partial"
        mv "$local_export_partial" "$EXPORT_ARCHIVE"
        (cd "$WEEKLY_DIR" && sha256sum "$EXPORT_NAME" >"$EXPORT_NAME.sha256")
        write_metadata "$EXPORT_META" "weekly-portable" "$SNAPSHOT_DB" "$EXPORT_ARCHIVE"
        verify_checksum "$EXPORT_ARCHIVE"
        verify_metadata "$EXPORT_ARCHIVE"
        log "created $EXPORT_ARCHIVE ($(du -h "$EXPORT_ARCHIVE" | cut -f1))"
    fi
    verify_metadata "$EXPORT_ARCHIVE"
    remote_upload_verified "$EXPORT_ARCHIVE" "weekly"
fi

prune_local "$DAILY_DIR" 'aoms-v2-????-??-??.sqlite3.zst' "$LOCAL_DAILY_KEEP"
prune_local "$WEEKLY_DIR" 'aoms-v2-weekly-????-??-??.sqlite3.zst' "$WEEKLY_KEEP"
prune_local "$WEEKLY_DIR" 'aoms-v2-portable-????-??-??.tar.zst' "$WEEKLY_KEEP"
prune_remote "daily" 'aoms-v2-????-??-??.sqlite3.zst' "$REMOTE_DAILY_KEEP"
prune_remote "weekly" 'aoms-v2-weekly-????-??-??.sqlite3.zst' "$WEEKLY_KEEP"
prune_remote "weekly" 'aoms-v2-portable-????-??-??.tar.zst' "$WEEKLY_KEEP"

log "AOMS v2 backup complete: daily=$DAILY_ARCHIVE weekly=$weekly_due"

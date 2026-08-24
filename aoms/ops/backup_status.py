"""Freshness and integrity watchdog for the AOMS v2 backup chain.

The nightly job in ``scripts/backup-aoms-v2.sh`` writes a physical SQLite
snapshot to ``~/openclaw_archives/aoms-v2/daily`` and mirrors it to a VPS. It
has failed silently before: for months it snapshotted a store that was no
longer the live one, and nothing compared the two. Every check here exists to
make one specific version of that silence impossible, and every failure names
the command that fixes it.

Configuration is read from the crontab entry that actually invokes the backup
script, not from documentation. A watchdog that inspects a different directory
than the job writes to is the same bug wearing a different hat.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

_STATE_RANK = {PASS: 0, WARN: 1, FAIL: 2}

BACKUP_SCRIPT_NAME = "backup-aoms-v2.sh"
DAILY_GLOB = "aoms-v2-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].sqlite3.zst"
WEEKLY_PORTABLE_GLOB = (
    "aoms-v2-portable-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].tar.zst"
)
SUCCESS_MARKER = "AOMS v2 backup complete"
ERROR_MARKER = "ERROR:"

# The daily job fires at 04:45 local time. 24h of cadence plus 2h of slack
# absorbs a long run (the weekly path uploads two 330 MB artifacts), a delayed
# cron start, and the one-hour daylight-saving shift.
DAILY_MAX_AGE = timedelta(hours=26)
# The portable export is produced on Sundays only; 7 days of cadence plus one
# day of slack.
WEEKLY_MAX_AGE = timedelta(days=8)
# A snapshot is a point in time, so the live store is normally a little ahead.
# Warn once the gap stops looking like ordinary writes, fail once it stops
# looking like the same store.
RECORD_DRIFT_WARN_RATIO = 0.02
RECORD_DRIFT_WARN_FLOOR = 500
RECORD_DRIFT_FAIL_RATIO = 0.10
RECORD_DRIFT_FAIL_FLOOR = 5_000

DEFAULT_BACKUP_ROOT = "~/openclaw_archives/aoms-v2"
DEFAULT_LOG_FILE = "~/.openclaw/workspace/logs/backup-aoms-v2.log"
DEFAULT_REMOTE_ROOT = "/srv/backups/aoms-v2"
DEFAULT_LIVE_DB = "~/.local/share/aoms/aoms.sqlite3"
DEFAULT_SCRIPT = "~/.openclaw/workspace/scripts/backup-aoms-v2.sh"

_CRON_ASSIGNMENT = re.compile(r"(?P<key>AOMS_[A-Z0-9_]+)=(?P<value>\S+)")


@dataclass(frozen=True)
class CheckResult:
    """One verdict, with the exact command that clears it when it is not PASS."""

    name: str
    state: str
    detail: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "state": self.state,
            "detail": self.detail,
        }
        if self.remediation:
            payload["remediation"] = self.remediation
        return payload


@dataclass(frozen=True)
class BackupConfig:
    """Where the backup job actually reads and writes, and how we know."""

    backup_root: Path
    live_db: Path
    log_file: Path
    script: Path
    remote_host: str | None
    remote_root: str
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def daily_dir(self) -> Path:
        return self.backup_root / "daily"

    @property
    def weekly_dir(self) -> Path:
        return self.backup_root / "weekly"

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_root": str(self.backup_root),
            "daily_dir": str(self.daily_dir),
            "weekly_dir": str(self.weekly_dir),
            "live_db": str(self.live_db),
            "log_file": str(self.log_file),
            "script": str(self.script),
            "remote_host": self.remote_host,
            "remote_root": self.remote_root,
            "resolved_from": dict(self.sources),
        }


@dataclass(frozen=True)
class RemoteArtifact:
    """Outcome of a read-only probe for one artifact on the backup host."""

    reachable: bool
    present: bool = False
    sha256: str | None = None
    error: str = ""


@dataclass
class BackupStatusReport:
    checks: list[CheckResult]
    config: BackupConfig
    generated_at: datetime

    @property
    def state(self) -> str:
        return max(
            (check.state for check in self.checks),
            key=lambda state: _STATE_RANK[state],
            default=PASS,
        )

    @property
    def failures(self) -> list[CheckResult]:
        return [check for check in self.checks if check.state == FAIL]

    @property
    def warnings(self) -> list[CheckResult]:
        return [check for check in self.checks if check.state == WARN]

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "generated_at": self.generated_at.isoformat(),
            "config": self.config.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
            "summary": {
                "pass": sum(1 for check in self.checks if check.state == PASS),
                "warn": len(self.warnings),
                "fail": len(self.failures),
            },
        }

    def render(self) -> str:
        lines = [
            "AOMS v2 backup status",
            f"Checked at: {self.generated_at.astimezone().isoformat(timespec='seconds')}",
            f"Backup root: {self.config.backup_root}",
            f"Live store: {self.config.live_db}",
            f"Remote: {self.config.remote_host or '(not configured)'}"
            f":{self.config.remote_root}",
            "",
        ]
        for check in self.checks:
            lines.append(f"[{check.state}] {check.name}: {check.detail}")
            if check.remediation:
                lines.append(f"       Fix: {check.remediation}")
        lines.append("")
        lines.append(
            f"Result: {self.state} "
            f"({len(self.failures)} failure(s), {len(self.warnings)} warning(s))"
        )
        return "\n".join(lines)


def read_crontab(runner: Callable[[Sequence[str]], str] | None = None) -> str:
    """Return the current user's crontab, or an empty string when unavailable."""

    if runner is not None:
        return runner(["crontab", "-l"])
    try:
        completed = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def backup_cron_entry(crontab_text: str) -> str | None:
    """Return the active (uncommented) cron line invoking the backup script."""

    for line in crontab_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if BACKUP_SCRIPT_NAME in stripped:
            return stripped
    return None


def parse_cron_environment(crontab_text: str) -> dict[str, str]:
    """Extract ``AOMS_*`` assignments from the backup job's own cron line.

    The cron entry is the only honest record of how the job is configured: it
    is what overrode the remote directory to ``/root/backups/aoms-v2`` while
    every other reference still said ``/srv``.
    """

    entry = backup_cron_entry(crontab_text)
    if entry is None:
        return {}
    return {
        match.group("key"): match.group("value")
        for match in _CRON_ASSIGNMENT.finditer(entry)
    }


def _expand(value: str) -> Path:
    return Path(value).expanduser()


def resolve_config(
    environ: Mapping[str, str] | None = None,
    crontab_text: str | None = None,
    *,
    backup_root: Path | None = None,
    live_db: Path | None = None,
    log_file: Path | None = None,
    remote_host: str | None = None,
    remote_root: str | None = None,
) -> BackupConfig:
    """Resolve the backup layout: explicit argument, environment, cron, default."""

    env = dict(os.environ if environ is None else environ)
    cron = parse_cron_environment(
        read_crontab() if crontab_text is None else crontab_text
    )
    sources: dict[str, str] = {}

    def pick(
        argument: str | Path | None,
        variable: str,
        fallback: str,
        label: str,
    ) -> str:
        if argument is not None:
            sources[label] = "argument"
            return str(argument)
        if env.get(variable):
            sources[label] = f"environment:{variable}"
            return env[variable]
        if cron.get(variable):
            sources[label] = f"crontab:{variable}"
            return cron[variable]
        sources[label] = "default"
        return fallback

    data_dir = pick(None, "AOMS_DATA_DIR", "", "data_dir")
    default_db = f"{data_dir}/aoms.sqlite3" if data_dir else DEFAULT_LIVE_DB
    sources.pop("data_dir", None)

    resolved_root = pick(backup_root, "AOMS_BACKUP_DIR", DEFAULT_BACKUP_ROOT, "backup_root")
    resolved_db = pick(live_db, "AOMS_DB_PATH", default_db, "live_db")
    resolved_log = pick(log_file, "AOMS_BACKUP_LOG_FILE", DEFAULT_LOG_FILE, "log_file")
    resolved_remote_root = pick(
        remote_root, "AOMS_BACKUP_VPS_DIR", DEFAULT_REMOTE_ROOT, "remote_root"
    )
    resolved_host = pick(remote_host, "AOMS_BACKUP_VPS", "", "remote_host")

    return BackupConfig(
        backup_root=_expand(resolved_root),
        live_db=_expand(resolved_db),
        log_file=_expand(resolved_log),
        script=_expand(DEFAULT_SCRIPT),
        remote_host=resolved_host or None,
        remote_root=resolved_remote_root,
        sources=sources,
    )


def newest_artifact(directory: Path, pattern: str) -> Path | None:
    """Return the most recently modified artifact matching ``pattern``."""

    try:
        candidates = [path for path in directory.glob(pattern) if path.is_file()]
    except OSError:
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_checksum_sidecar(artifact: Path) -> tuple[str | None, str | None]:
    """Return ``(digest, named_file)`` recorded in ``<artifact>.sha256``."""

    sidecar = Path(f"{artifact}.sha256")
    try:
        content = sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        return None, None
    if not content:
        return None, None
    parts = content.split(None, 1)
    digest = parts[0] if parts else None
    named = parts[1].strip().lstrip("*") if len(parts) > 1 else None
    return digest, named


def read_metadata(artifact: Path) -> dict[str, Any] | None:
    metadata_path = Path(f"{artifact}.metadata.json")
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def live_record_count(db_path: Path) -> int:
    """Count live memories without taking a write lock on the store."""

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        connection.execute("PRAGMA query_only=ON")
        return int(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
    finally:
        connection.close()


def probe_remote(host: str, remote_path: str, *, timeout: float = 45.0) -> RemoteArtifact:
    """Read-only ssh probe: does the artifact exist there, and with what hash?"""

    quoted = shlex.quote(remote_path)
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        host,
        f"if [ -f {quoted} ]; then sha256sum -- {quoted}; else echo __MISSING__; fi",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        return RemoteArtifact(reachable=False, error="ssh timed out")
    except OSError as exc:
        return RemoteArtifact(reachable=False, error=f"ssh could not run: {exc}")

    output = completed.stdout.strip()
    if completed.returncode == 255 or (completed.returncode != 0 and not output):
        detail = completed.stderr.strip().splitlines()
        return RemoteArtifact(
            reachable=False,
            error=detail[-1] if detail else f"ssh exited {completed.returncode}",
        )
    if output == "__MISSING__":
        return RemoteArtifact(reachable=True, present=False)
    digest = output.split(None, 1)[0] if output else ""
    if len(digest) != 64:
        return RemoteArtifact(
            reachable=True, present=False, error=f"unexpected ssh output: {output[:80]}"
        )
    return RemoteArtifact(reachable=True, present=True, sha256=digest)


def _describe_age(age: timedelta) -> str:
    hours = age.total_seconds() / 3600
    if hours < 48:
        return f"{hours:.1f}h old"
    return f"{age.days}d {int(hours % 24)}h old"


def _run_backup_command(config: BackupConfig) -> str:
    """The exact command an operator should run to produce a fresh backup."""

    prefix = []
    if config.remote_host:
        prefix.append(f"AOMS_BACKUP_VPS={config.remote_host}")
    if config.remote_root != DEFAULT_REMOTE_ROOT:
        prefix.append(f"AOMS_BACKUP_VPS_DIR={config.remote_root}")
    joined = " ".join(prefix)
    return f"{joined} {config.script}".strip()


def check_schedule(config: BackupConfig, crontab_text: str) -> CheckResult:
    entry = backup_cron_entry(crontab_text)
    if entry is None:
        return CheckResult(
            "Backup schedule",
            FAIL,
            f"no active crontab entry invokes {BACKUP_SCRIPT_NAME}; "
            "nothing will produce a new artifact",
            f"Restore the nightly entry: crontab -e, then add a daily line running "
            f"{config.script} (see docs/ops/BACKUP-MONITORING.md).",
        )
    schedule = " ".join(entry.split()[:5])
    return CheckResult(
        "Backup schedule", PASS, f"cron runs the backup at '{schedule}'"
    )


def check_daily_freshness(
    config: BackupConfig, now: datetime
) -> tuple[CheckResult, Path | None]:
    artifact = newest_artifact(config.daily_dir, DAILY_GLOB)
    if artifact is None:
        return (
            CheckResult(
                "Daily artifact",
                FAIL,
                f"no daily snapshot found in {config.daily_dir}",
                f"Run: {_run_backup_command(config)}",
            ),
            None,
        )
    modified = datetime.fromtimestamp(artifact.stat().st_mtime, tz=timezone.utc)
    age = now - modified
    if age > DAILY_MAX_AGE:
        return (
            CheckResult(
                "Daily artifact",
                FAIL,
                f"{artifact.name} is {_describe_age(age)}, over the "
                f"{int(DAILY_MAX_AGE.total_seconds() // 3600)}h limit "
                f"(written {modified.astimezone().isoformat(timespec='seconds')})",
                f"Run: {_run_backup_command(config)} "
                f"then check {config.log_file} for the cause of the missed run.",
            ),
            artifact,
        )
    return (
        CheckResult(
            "Daily artifact",
            PASS,
            f"{artifact.name} is {_describe_age(age)} "
            f"({artifact.stat().st_size / 1_048_576:.0f} MiB)",
        ),
        artifact,
    )


def check_checksum(config: BackupConfig, artifact: Path) -> tuple[CheckResult, str | None]:
    recorded, named = read_checksum_sidecar(artifact)
    if recorded is None:
        return (
            CheckResult(
                "Daily checksum",
                FAIL,
                f"missing or empty {artifact.name}.sha256; the snapshot is unverifiable",
                f"Run: {_run_backup_command(config)} to regenerate the "
                "generation and its checksum.",
            ),
            None,
        )
    if named is not None and named != artifact.name:
        return (
            CheckResult(
                "Daily checksum",
                FAIL,
                f"{artifact.name}.sha256 records a digest for {named!r}, not for "
                f"{artifact.name!r}",
                f"Run: cd {artifact.parent} && sha256sum {artifact.name} "
                f"> {artifact.name}.sha256 after confirming the artifact is sound.",
            ),
            None,
        )
    actual = file_sha256(artifact)
    if actual != recorded:
        return (
            CheckResult(
                "Daily checksum",
                FAIL,
                f"{artifact.name} hashes to {actual[:16]}... but its .sha256 "
                f"records {recorded[:16]}...; the artifact is corrupt or truncated",
                f"Delete the bad generation and rebuild it: rm -f {artifact} "
                f"{artifact}.sha256 {artifact}.metadata.json && "
                f"{_run_backup_command(config)}",
            ),
            actual,
        )
    return (
        CheckResult(
            "Daily checksum", PASS, f"{artifact.name} matches its recorded sha256"
        ),
        actual,
    )


def check_source_store(
    config: BackupConfig, artifact: Path, metadata: dict[str, Any] | None
) -> CheckResult:
    """Confirm the snapshot came from the store we consider live.

    This is the direct guard against the documented failure: a nightly job that
    kept backing up a database nobody wrote to any more.
    """

    if metadata is None:
        return CheckResult(
            "Backup source",
            FAIL,
            f"missing or unreadable {artifact.name}.metadata.json; cannot tell "
            "which database was snapshotted",
            f"Run: {_run_backup_command(config)}",
        )
    recorded = str(metadata.get("source_database") or "")
    if not recorded:
        return CheckResult(
            "Backup source",
            FAIL,
            f"{artifact.name}.metadata.json records no source_database",
            f"Run: {_run_backup_command(config)}",
        )
    expected = str(config.live_db)
    if Path(recorded).expanduser() != Path(expected).expanduser():
        return CheckResult(
            "Backup source",
            FAIL,
            f"the snapshot was taken from {recorded} but the live store is "
            f"{expected}; the nightly job is backing up the wrong database",
            f"Point the job at the live store: set AOMS_DB_PATH={expected} in the "
            f"{BACKUP_SCRIPT_NAME} crontab entry, then run "
            f"{_run_backup_command(config)}",
        )
    integrity = str(metadata.get("integrity_check") or "")
    if integrity != "ok":
        return CheckResult(
            "Backup source",
            FAIL,
            f"{artifact.name} recorded integrity_check={integrity!r}",
            f"Do not trust this generation. Run: {_run_backup_command(config)} and "
            f"verify the live store with: cortex-mem doctor",
        )
    return CheckResult(
        "Backup source", PASS, f"snapshot of {recorded} with integrity_check=ok"
    )


def check_record_count(
    config: BackupConfig, artifact: Path, metadata: dict[str, Any] | None
) -> CheckResult:
    if metadata is None or not isinstance(metadata.get("records"), int):
        return CheckResult(
            "Record count",
            FAIL,
            f"{artifact.name}.metadata.json records no usable record count",
            f"Run: {_run_backup_command(config)}",
        )
    backed_up = int(metadata["records"])
    try:
        live = live_record_count(config.live_db)
    except (sqlite3.Error, OSError, ValueError) as exc:
        return CheckResult(
            "Record count",
            WARN,
            f"backup holds {backed_up:,} records; the live store at "
            f"{config.live_db} could not be read ({exc})",
            "Confirm the live store is present and readable: cortex-mem doctor",
        )

    delta = live - backed_up
    warn_tolerance = max(RECORD_DRIFT_WARN_FLOOR, int(backed_up * RECORD_DRIFT_WARN_RATIO))
    fail_tolerance = max(RECORD_DRIFT_FAIL_FLOOR, int(backed_up * RECORD_DRIFT_FAIL_RATIO))
    summary = f"backup {backed_up:,} vs live {live:,} (delta {delta:+,})"

    if abs(delta) <= warn_tolerance:
        return CheckResult("Record count", PASS, f"{summary}, within {warn_tolerance:,}")
    if abs(delta) > fail_tolerance:
        direction = (
            "the live store has far more records than the newest backup; the job is "
            "snapshotting a stale or different database"
            if delta > 0
            else "the live store has far fewer records than the backup; the live "
            "store may have been truncated or replaced"
        )
        return CheckResult(
            "Record count",
            FAIL,
            f"{summary} exceeds the {fail_tolerance:,} record tolerance — {direction}",
            f"Compare the two directly: "
            f"sqlite3 'file:{config.live_db}?mode=ro' 'SELECT COUNT(*) FROM memories' "
            f"and read {artifact}.metadata.json; then run "
            f"{_run_backup_command(config)}",
        )
    return CheckResult(
        "Record count",
        WARN,
        f"{summary} exceeds the {warn_tolerance:,} record tolerance",
        f"Expected if the store is busy. If it keeps growing, run "
        f"{_run_backup_command(config)} and re-check.",
    )


def check_remote_copy(
    config: BackupConfig,
    artifact: Path,
    local_digest: str | None,
    probe: Callable[[str, str], RemoteArtifact],
) -> CheckResult:
    if not config.remote_host:
        return CheckResult(
            "Remote copy",
            WARN,
            "no backup host is configured, so the only copy is on this machine",
            "Set AOMS_BACKUP_VPS=<user@host> in the backup crontab entry.",
        )
    remote_path = f"{config.remote_root.rstrip('/')}/daily/{artifact.name}"
    result = probe(config.remote_host, remote_path)
    if not result.reachable:
        return CheckResult(
            "Remote copy",
            WARN,
            f"{config.remote_host} is unreachable ({result.error or 'no response'}); "
            "the off-site copy could not be verified",
            f"Re-check once the host is reachable: "
            f"ssh {config.remote_host} sha256sum {remote_path}",
        )
    if not result.present:
        return CheckResult(
            "Remote copy",
            FAIL,
            f"{config.remote_host} is reachable but {remote_path} is missing; "
            "this backup exists on one machine only"
            + (f" ({result.error})" if result.error else ""),
            f"Re-run the upload: {_run_backup_command(config)}",
        )
    if local_digest is None:
        return CheckResult(
            "Remote copy",
            WARN,
            f"{remote_path} exists but the local digest is unknown, so the two "
            "copies were not compared",
            "Resolve the local checksum failure above, then re-run this check.",
        )
    if result.sha256 != local_digest:
        return CheckResult(
            "Remote copy",
            FAIL,
            f"{remote_path} hashes to {(result.sha256 or '')[:16]}... but the local "
            f"copy hashes to {local_digest[:16]}...; the off-site copy is not this "
            "backup",
            f"Delete the remote copy and re-upload: "
            f"ssh {config.remote_host} rm -f {remote_path} && "
            f"{_run_backup_command(config)}",
        )
    return CheckResult(
        "Remote copy",
        PASS,
        f"{config.remote_host}:{remote_path} matches the local sha256",
    )


def check_weekly_export(config: BackupConfig, now: datetime) -> CheckResult:
    artifact = newest_artifact(config.weekly_dir, WEEKLY_PORTABLE_GLOB)
    if artifact is None:
        return CheckResult(
            "Weekly export",
            FAIL,
            f"no portable export found in {config.weekly_dir}; there is no "
            "format-independent copy of the store",
            f"Force one now: AOMS_FORCE_WEEKLY=1 {_run_backup_command(config)}",
        )
    modified = datetime.fromtimestamp(artifact.stat().st_mtime, tz=timezone.utc)
    age = now - modified
    if age > WEEKLY_MAX_AGE:
        return CheckResult(
            "Weekly export",
            FAIL,
            f"{artifact.name} is {_describe_age(age)}, over the "
            f"{WEEKLY_MAX_AGE.days}-day limit",
            f"Force one now: AOMS_FORCE_WEEKLY=1 {_run_backup_command(config)}",
        )
    return CheckResult(
        "Weekly export", PASS, f"{artifact.name} is {_describe_age(age)}"
    )


def check_log_tail(config: BackupConfig) -> CheckResult:
    """Report on the last decisive line the backup script wrote."""

    try:
        lines = config.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return CheckResult(
            "Backup log",
            WARN,
            f"cannot read {config.log_file} ({exc}); the job's own account of the "
            "last run is unavailable",
            f"Confirm the log path in the {BACKUP_SCRIPT_NAME} crontab entry.",
        )
    for line in reversed(lines):
        if SUCCESS_MARKER in line:
            return CheckResult("Backup log", PASS, f"last outcome: {line.strip()}")
        if ERROR_MARKER in line:
            return CheckResult(
                "Backup log",
                FAIL,
                f"the last recorded outcome is an error: {line.strip()}",
                f"Read the surrounding context with: tail -40 {config.log_file} "
                f"then re-run {_run_backup_command(config)}",
            )
    return CheckResult(
        "Backup log",
        WARN,
        f"{config.log_file} records neither a completion nor an error; the job may "
        "never have run since the log was rotated",
        f"Run {_run_backup_command(config)} and confirm a "
        f"'{SUCCESS_MARKER}' line appears.",
    )


def run_checks(
    config: BackupConfig,
    *,
    now: datetime | None = None,
    crontab_text: str | None = None,
    remote_probe: Callable[[str, str], RemoteArtifact] | None = None,
    skip_remote: bool = False,
) -> BackupStatusReport:
    """Run every backup check and collect the verdicts."""

    moment = now or datetime.now(timezone.utc)
    cron = read_crontab() if crontab_text is None else crontab_text
    probe = remote_probe or probe_remote

    checks: list[CheckResult] = [check_schedule(config, cron)]
    freshness, artifact = check_daily_freshness(config, moment)
    checks.append(freshness)

    digest: str | None = None
    if artifact is not None:
        checksum, digest = check_checksum(config, artifact)
        checks.append(checksum)
        metadata = read_metadata(artifact)
        checks.append(check_source_store(config, artifact, metadata))
        checks.append(check_record_count(config, artifact, metadata))
        if skip_remote:
            checks.append(
                CheckResult(
                    "Remote copy",
                    WARN,
                    "skipped by request; the off-site copy was not verified",
                    "Re-run without --skip-remote to check the backup host.",
                )
            )
        else:
            checks.append(check_remote_copy(config, artifact, digest, probe))

    checks.append(check_weekly_export(config, moment))
    checks.append(check_log_tail(config))
    return BackupStatusReport(checks=checks, config=config, generated_at=moment)


def write_alert_file(report: BackupStatusReport, path: Path) -> None:
    """Leave a durable marker on FAIL and clear it once the chain recovers.

    A log line nobody reads is how the last silent failure lasted months. The
    presence of this file is meant to be the thing an operator or another
    health check can cheaply notice.
    """

    if report.failures:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.render() + "\n", encoding="utf-8")
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point shared by the CLI subcommand and the standalone cron script."""

    import argparse

    parser = argparse.ArgumentParser(
        prog="aoms-backup-status",
        description="Verify that the AOMS v2 backup chain is fresh and intact.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    parser.add_argument(
        "--skip-remote", action="store_true", help="Do not contact the backup host."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on WARN as well as FAIL.",
    )
    parser.add_argument(
        "--alert-file",
        type=Path,
        help="Write the report here on FAIL; delete it when healthy.",
    )
    parser.add_argument("--backup-root", type=Path, help="Override the backup root.")
    parser.add_argument("--live-db", type=Path, help="Override the live store path.")
    arguments = parser.parse_args(argv)

    config = resolve_config(
        backup_root=arguments.backup_root, live_db=arguments.live_db
    )
    report = run_checks(config, skip_remote=arguments.skip_remote)
    if arguments.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(report.render())
    if arguments.alert_file is not None:
        write_alert_file(report, arguments.alert_file.expanduser())
    return exit_code(report, strict=arguments.strict)


def exit_code(report: BackupStatusReport, *, strict: bool = False) -> int:
    if report.failures:
        return 1
    if strict and report.warnings:
        return 1
    return 0


@click.command("backup-status")
@click.option("--json", "as_json", is_flag=True, help="Emit a JSON report.")
@click.option("--skip-remote", is_flag=True, help="Do not contact the backup host.")
@click.option("--strict", is_flag=True, help="Exit non-zero on WARN as well as FAIL.")
@click.option(
    "--backup-root",
    type=click.Path(path_type=Path, file_okay=False),
    help="Override the backup root directory.",
)
@click.option(
    "--live-db",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Override the live store path.",
)
def backup_status_command(
    as_json: bool,
    skip_remote: bool,
    strict: bool,
    backup_root: Path | None,
    live_db: Path | None,
) -> None:
    """Verify that the nightly backup is fresh, intact, and off-site."""

    config = resolve_config(backup_root=backup_root, live_db=live_db)
    report = run_checks(config, skip_remote=skip_remote)
    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        click.echo(report.render())
    code = exit_code(report, strict=strict)
    if code:
        raise click.exceptions.Exit(code)


# ``python -m aoms.cli`` runs the root as ``__main__``; the installed console script
# imports it as ``aoms.cli``. Support both without adding a second root integration line.
_root_main = getattr(sys.modules.get("__main__"), "main", None)
if not isinstance(_root_main, click.Group):
    from aoms.cli import main as _root_main  # noqa: E402

_root_main.add_command(backup_status_command)

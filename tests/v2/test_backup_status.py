"""Watchdog tests for the AOMS v2 backup chain.

Every scenario is built on disk from scratch and the backup host is always a
stub, so the suite needs no network and never touches the real archives.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aoms.ops.backup_status import (
    FAIL,
    PASS,
    WARN,
    BackupConfig,
    RemoteArtifact,
    backup_cron_entry,
    exit_code,
    parse_cron_environment,
    resolve_config,
    run_checks,
    write_alert_file,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

CRONTAB = (
    "0 8 * * * /home/dhawal/.openclaw/workspace/scripts/daily_health_check.sh\n"
    "45 4 * * * PATH=/usr/bin AOMS_BACKUP_VPS=root@198.51.100.7 "
    "AOMS_BACKUP_VPS_DIR=/root/backups/aoms-v2 /usr/bin/nice -n 10 "
    "/home/dhawal/.openclaw/workspace/scripts/backup-aoms-v2.sh\n"
)

SUCCESS_LOG = (
    "[2026-08-24 04:45:01 -0700] creating SQLite online backup\n"
    "[2026-08-24 04:52:27 -0700] AOMS v2 backup complete: daily=x weekly=0\n"
)
ERROR_LOG = (
    "[2026-08-24 04:45:01 -0700] creating SQLite online backup\n"
    "[2026-08-24 04:45:02 -0700] ERROR: canonical database is not readable\n"
)


def _write_live_store(path: Path, records: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS memories")
        connection.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, body TEXT)")
        connection.executemany(
            "INSERT INTO memories (body) VALUES (?)",
            [(f"memory-{index}",) for index in range(records)],
        )
        connection.commit()
    finally:
        connection.close()


def _age(path: Path, *, hours: float, reference: datetime = NOW) -> None:
    stamp = (reference - timedelta(hours=hours)).timestamp()
    os.utime(path, (stamp, stamp))


def _write_artifact(
    directory: Path,
    name: str,
    *,
    payload: bytes,
    live_db: Path,
    records: int,
    age_hours: float,
    checksum: str | None = None,
    checksum_name: str | None = None,
    metadata: bool = True,
    integrity: str = "ok",
    source_database: Path | None = None,
    reference: datetime = NOW,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / name
    artifact.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    recorded = checksum if checksum is not None else digest
    Path(f"{artifact}.sha256").write_text(
        f"{recorded}  {checksum_name or name}\n", encoding="utf-8"
    )
    if metadata:
        Path(f"{artifact}.metadata.json").write_text(
            json.dumps(
                {
                    "artifact": name,
                    "backup_kind": "daily-physical",
                    "created_at": reference.isoformat(),
                    "integrity_check": integrity,
                    "receipts": 14,
                    "records": records,
                    "sha256": digest,
                    "source_database": str(source_database or live_db),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    _age(artifact, hours=age_hours, reference=reference)
    return artifact


class _Scenario:
    """A complete on-disk backup tree the checks can be pointed at."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.backup_root = tmp_path / "archives" / "aoms-v2"
        self.live_db = tmp_path / "data" / "aoms.sqlite3"
        self.log_file = tmp_path / "logs" / "backup-aoms-v2.log"
        self.payload = b"snapshot-bytes" * 64
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def build(
        self,
        *,
        live_records: int = 1_000,
        backup_records: int = 1_000,
        daily_age_hours: float = 7.0,
        weekly_age_days: float = 1.0,
        log: str = SUCCESS_LOG,
        daily: bool = True,
        weekly: bool = True,
        reference: datetime = NOW,
        **artifact_options: object,
    ) -> BackupConfig:
        _write_live_store(self.live_db, live_records)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.write_text(log, encoding="utf-8")

        if daily:
            _write_artifact(
                self.backup_root / "daily",
                f"aoms-v2-{reference:%Y-%m-%d}.sqlite3.zst",
                payload=self.payload,
                live_db=self.live_db,
                records=backup_records,
                age_hours=daily_age_hours,
                reference=reference,
                **artifact_options,  # type: ignore[arg-type]
            )
        if weekly:
            weekly_dir = self.backup_root / "weekly"
            _write_artifact(
                weekly_dir,
                f"aoms-v2-portable-{reference - timedelta(days=1):%Y-%m-%d}.tar.zst",
                payload=self.payload,
                live_db=self.live_db,
                records=backup_records,
                age_hours=weekly_age_days * 24,
                reference=reference,
            )
        return BackupConfig(
            backup_root=self.backup_root,
            live_db=self.live_db,
            log_file=self.log_file,
            script=Path("/opt/backup-aoms-v2.sh"),
            remote_host="root@198.51.100.7",
            remote_root="/root/backups/aoms-v2",
        )

    def check(self, config: BackupConfig, name: str, **kwargs: object):
        report = run_checks(
            config,
            now=NOW,
            crontab_text=CRONTAB,
            remote_probe=kwargs.pop("remote_probe", self.probe),  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )
        matched = [check for check in report.checks if check.name == name]
        assert matched, f"no check named {name!r} in {[c.name for c in report.checks]}"
        return report, matched[0]

    def probe(self, host: str, remote_path: str) -> RemoteArtifact:
        return RemoteArtifact(reachable=True, present=True, sha256=self.digest)


@pytest.fixture
def scenario(tmp_path: Path) -> _Scenario:
    return _Scenario(tmp_path)


def test_healthy_chain_passes_every_check(scenario: _Scenario) -> None:
    config = scenario.build()
    report = run_checks(
        config, now=NOW, crontab_text=CRONTAB, remote_probe=scenario.probe
    )

    assert report.state == PASS, report.render()
    assert exit_code(report) == 0
    assert {check.state for check in report.checks} == {PASS}


def test_stale_daily_artifact_fails_with_the_rerun_command(scenario: _Scenario) -> None:
    config = scenario.build(daily_age_hours=30.0)
    report, check = scenario.check(config, "Daily artifact")

    assert check.state == FAIL
    assert "30.0h old" in check.detail
    assert "26h limit" in check.detail
    assert "/opt/backup-aoms-v2.sh" in check.remediation
    assert exit_code(report) == 1


def test_daily_artifact_just_inside_the_window_passes(scenario: _Scenario) -> None:
    config = scenario.build(daily_age_hours=25.5)
    _, check = scenario.check(config, "Daily artifact")

    assert check.state == PASS


def test_missing_daily_artifact_fails(scenario: _Scenario) -> None:
    config = scenario.build(daily=False)
    report, check = scenario.check(config, "Daily artifact")

    assert check.state == FAIL
    assert "no daily snapshot" in check.detail
    assert exit_code(report) == 1


def test_checksum_mismatch_fails_and_names_the_bad_generation(
    scenario: _Scenario,
) -> None:
    config = scenario.build(checksum="0" * 64)
    report, check = scenario.check(config, "Daily checksum")

    assert check.state == FAIL
    assert "corrupt or truncated" in check.detail
    assert "rm -f" in check.remediation
    assert exit_code(report) == 1


def test_checksum_sidecar_naming_another_file_fails(scenario: _Scenario) -> None:
    config = scenario.build(checksum_name="aoms-v2-2026-01-01.sqlite3.zst")
    _, check = scenario.check(config, "Daily checksum")

    assert check.state == FAIL
    assert "records a digest for" in check.detail


def test_record_drift_beyond_the_fail_threshold_fails(scenario: _Scenario) -> None:
    config = scenario.build(live_records=20_000, backup_records=100)
    report, check = scenario.check(config, "Record count")

    assert check.state == FAIL
    assert "backup 100 vs live 20,000" in check.detail
    assert "stale or different database" in check.detail
    assert exit_code(report) == 1


def test_live_store_shrinking_far_below_the_backup_fails(scenario: _Scenario) -> None:
    config = scenario.build(live_records=10, backup_records=100_000)
    _, check = scenario.check(config, "Record count")

    assert check.state == FAIL
    assert "truncated or replaced" in check.detail


def test_modest_record_drift_only_warns(scenario: _Scenario) -> None:
    config = scenario.build(live_records=1_800, backup_records=1_000)
    report, check = scenario.check(config, "Record count")

    assert check.state == WARN
    assert exit_code(report) == 0
    assert exit_code(report, strict=True) == 1


def test_record_drift_inside_tolerance_passes(scenario: _Scenario) -> None:
    config = scenario.build(live_records=1_400, backup_records=1_000)
    _, check = scenario.check(config, "Record count")

    assert check.state == PASS


def test_backup_of_the_wrong_store_fails(scenario: _Scenario) -> None:
    config = scenario.build(source_database=Path("/home/dhawal/legacy/aoms.sqlite3"))
    report, check = scenario.check(config, "Backup source")

    assert check.state == FAIL
    assert "backing up the wrong database" in check.detail
    assert "AOMS_DB_PATH=" in check.remediation
    assert exit_code(report) == 1


def test_failed_integrity_check_in_metadata_fails(scenario: _Scenario) -> None:
    config = scenario.build(integrity="page 7 is corrupt")
    _, check = scenario.check(config, "Backup source")

    assert check.state == FAIL
    assert "page 7 is corrupt" in check.detail


def test_unreachable_backup_host_warns_rather_than_failing(
    scenario: _Scenario,
) -> None:
    config = scenario.build()

    def unreachable(host: str, remote_path: str) -> RemoteArtifact:
        return RemoteArtifact(reachable=False, error="Connection timed out")

    report, check = scenario.check(config, "Remote copy", remote_probe=unreachable)

    assert check.state == WARN
    assert "unreachable" in check.detail
    assert report.state == WARN
    assert exit_code(report) == 0


def test_remote_copy_missing_on_a_reachable_host_fails(scenario: _Scenario) -> None:
    config = scenario.build()

    def missing(host: str, remote_path: str) -> RemoteArtifact:
        return RemoteArtifact(reachable=True, present=False)

    report, check = scenario.check(config, "Remote copy", remote_probe=missing)

    assert check.state == FAIL
    assert "exists on one machine only" in check.detail
    assert exit_code(report) == 1


def test_remote_copy_with_a_different_hash_fails(scenario: _Scenario) -> None:
    config = scenario.build()

    def divergent(host: str, remote_path: str) -> RemoteArtifact:
        return RemoteArtifact(reachable=True, present=True, sha256="a" * 64)

    _, check = scenario.check(config, "Remote copy", remote_probe=divergent)

    assert check.state == FAIL
    assert "is not this backup" in check.detail


def test_skip_remote_warns_instead_of_silently_passing(scenario: _Scenario) -> None:
    config = scenario.build()
    report = run_checks(
        config, now=NOW, crontab_text=CRONTAB, skip_remote=True
    )
    remote = next(check for check in report.checks if check.name == "Remote copy")

    assert remote.state == WARN
    assert "skipped by request" in remote.detail


def test_stale_weekly_export_fails(scenario: _Scenario) -> None:
    config = scenario.build(weekly_age_days=9.0)
    report, check = scenario.check(config, "Weekly export")

    assert check.state == FAIL
    assert "8-day limit" in check.detail
    assert "AOMS_FORCE_WEEKLY=1" in check.remediation
    assert exit_code(report) == 1


def test_weekly_export_just_inside_the_window_passes(scenario: _Scenario) -> None:
    config = scenario.build(weekly_age_days=7.5)
    _, check = scenario.check(config, "Weekly export")

    assert check.state == PASS


def test_missing_weekly_export_fails(scenario: _Scenario) -> None:
    config = scenario.build(weekly=False)
    _, check = scenario.check(config, "Weekly export")

    assert check.state == FAIL
    assert "no portable export" in check.detail


def test_log_ending_in_an_error_fails(scenario: _Scenario) -> None:
    config = scenario.build(log=ERROR_LOG)
    report, check = scenario.check(config, "Backup log")

    assert check.state == FAIL
    assert "canonical database is not readable" in check.detail
    assert "tail -40" in check.remediation
    assert exit_code(report) == 1


def test_error_followed_by_a_later_success_passes(scenario: _Scenario) -> None:
    """A recovered run is healthy; only the last decisive line counts."""

    config = scenario.build(log=ERROR_LOG + SUCCESS_LOG)
    _, check = scenario.check(config, "Backup log")

    assert check.state == PASS
    assert "backup complete" in check.detail


def test_log_without_any_outcome_warns(scenario: _Scenario) -> None:
    config = scenario.build(log="[2026-08-24 04:45:01 -0700] starting\n")
    _, check = scenario.check(config, "Backup log")

    assert check.state == WARN
    assert "never have run" in check.detail


def test_missing_log_warns(scenario: _Scenario) -> None:
    config = scenario.build()
    config.log_file.unlink()
    _, check = scenario.check(config, "Backup log")

    assert check.state == WARN


def test_missing_cron_entry_fails(scenario: _Scenario) -> None:
    config = scenario.build()
    report = run_checks(
        config,
        now=NOW,
        crontab_text="0 8 * * * /usr/bin/true\n",
        remote_probe=scenario.probe,
    )
    check = next(c for c in report.checks if c.name == "Backup schedule")

    assert check.state == FAIL
    assert "nothing will produce a new artifact" in check.detail
    assert exit_code(report) == 1


def test_commented_out_cron_entry_does_not_count_as_scheduled(
    scenario: _Scenario,
) -> None:
    config = scenario.build()
    report = run_checks(
        config,
        now=NOW,
        crontab_text="# 45 4 * * * /path/backup-aoms-v2.sh\n",
        remote_probe=scenario.probe,
    )
    check = next(c for c in report.checks if c.name == "Backup schedule")

    assert check.state == FAIL


def test_cron_environment_beats_the_documented_default() -> None:
    """The cron line, not the script default, decides where the remote copy lives."""

    assert parse_cron_environment(CRONTAB) == {
        "AOMS_BACKUP_VPS": "root@198.51.100.7",
        "AOMS_BACKUP_VPS_DIR": "/root/backups/aoms-v2",
    }
    config = resolve_config({}, CRONTAB)

    assert config.remote_root == "/root/backups/aoms-v2"
    assert config.remote_host == "root@198.51.100.7"
    assert config.sources["remote_root"] == "crontab:AOMS_BACKUP_VPS_DIR"


def test_environment_overrides_the_cron_entry() -> None:
    config = resolve_config({"AOMS_BACKUP_VPS_DIR": "/srv/backups/aoms-v2"}, CRONTAB)

    assert config.remote_root == "/srv/backups/aoms-v2"
    assert config.sources["remote_root"] == "environment:AOMS_BACKUP_VPS_DIR"


def test_explicit_arguments_beat_everything() -> None:
    config = resolve_config(
        {"AOMS_BACKUP_DIR": "/from/env"},
        CRONTAB,
        backup_root=Path("/from/argument"),
    )

    assert config.backup_root == Path("/from/argument")
    assert config.sources["backup_root"] == "argument"


def test_data_dir_supplies_the_live_store_path() -> None:
    config = resolve_config({"AOMS_DATA_DIR": "/var/lib/aoms"}, CRONTAB)

    assert config.live_db == Path("/var/lib/aoms/aoms.sqlite3")


def test_backup_cron_entry_ignores_unrelated_jobs() -> None:
    assert backup_cron_entry("0 1 * * * /usr/bin/other.sh\n") is None
    assert "backup-aoms-v2.sh" in (backup_cron_entry(CRONTAB) or "")


def test_report_json_is_machine_readable(scenario: _Scenario) -> None:
    config = scenario.build(daily_age_hours=30.0)
    report = run_checks(
        config, now=NOW, crontab_text=CRONTAB, remote_probe=scenario.probe
    )
    payload = json.loads(json.dumps(report.to_dict()))

    assert payload["state"] == FAIL
    assert payload["summary"]["fail"] >= 1
    assert payload["config"]["remote_root"] == "/root/backups/aoms-v2"
    assert any(check["state"] == FAIL for check in payload["checks"])


def test_every_non_passing_check_carries_a_remediation(scenario: _Scenario) -> None:
    """A watchdog that only says 'something is wrong' is barely a watchdog."""

    config = scenario.build(
        daily_age_hours=40.0, weekly_age_days=20.0, log=ERROR_LOG
    )
    report = run_checks(
        config, now=NOW, crontab_text="", remote_probe=scenario.probe
    )

    assert report.state == FAIL
    for check in report.checks:
        if check.state != PASS:
            assert check.remediation, f"{check.name} has no remediation"


def test_standalone_script_runs_and_reports(tmp_path: Path) -> None:
    """The cron entry point shares the CLI's implementation, so smoke-test it.

    Every other test injects the frozen ``NOW``. This one runs the real script
    in a subprocess, so it is judged against the real clock and has to build
    its fixture against the real clock too — pinning the fixture to ``NOW``
    made the artifact age out for good once the calendar passed it.
    """

    scenario = _Scenario(tmp_path)
    scenario.build(reference=datetime.now(timezone.utc))
    environ = dict(os.environ)
    environ.update(
        {
            "AOMS_BACKUP_DIR": str(scenario.backup_root),
            "AOMS_DB_PATH": str(scenario.live_db),
            "AOMS_BACKUP_LOG_FILE": str(scenario.log_file),
            "PYTHONPATH": str(ROOT),
        }
    )
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "aoms-backup-status.py"), "--json",
         "--skip-remote"],
        capture_output=True,
        text=True,
        env=environ,
        cwd=tmp_path,
        timeout=120,
    )

    payload = json.loads(completed.stdout)
    names = {check["name"] for check in payload["checks"]}
    assert {"Daily artifact", "Daily checksum", "Record count", "Backup log"} <= names
    assert payload["config"]["backup_root"] == str(scenario.backup_root)
    assert completed.returncode == 0


def test_cli_subcommand_is_registered() -> None:
    from aoms.cli import main as cli_group

    assert "backup-status" in cli_group.commands


def test_alert_file_is_written_on_fail_and_cleared_on_recovery(
    scenario: _Scenario, tmp_path: Path
) -> None:
    alert = tmp_path / "alerts" / "ALERT_backup_status.txt"

    broken = scenario.build(daily_age_hours=40.0)
    failing = run_checks(
        broken, now=NOW, crontab_text=CRONTAB, remote_probe=scenario.probe
    )
    write_alert_file(failing, alert)

    assert alert.is_file()
    assert "26h limit" in alert.read_text(encoding="utf-8")

    healthy = scenario.build()
    recovered = run_checks(
        healthy, now=NOW, crontab_text=CRONTAB, remote_probe=scenario.probe
    )
    write_alert_file(recovered, alert)

    assert not alert.exists()


def test_alert_file_is_not_created_for_warnings_alone(
    scenario: _Scenario, tmp_path: Path
) -> None:
    alert = tmp_path / "ALERT_backup_status.txt"
    config = scenario.build()

    def unreachable(host: str, remote_path: str) -> RemoteArtifact:
        return RemoteArtifact(reachable=False, error="Connection timed out")

    report = run_checks(
        config, now=NOW, crontab_text=CRONTAB, remote_probe=unreachable
    )
    write_alert_file(report, alert)

    assert report.state == WARN
    assert not alert.exists()

#!/usr/bin/env python3
"""cortex-mem CLI — manage the Always-On Memory Service."""

import os
import signal
import subprocess
import sys
from pathlib import Path

import click

PID_FILE = Path.home() / ".cortex-mem" / "cortex-mem.pid"
DEFAULT_PORT = 9100


def _find_service_root() -> Path:
    """Locate the service root directory.

    Priority:
      1. CORTEX_MEM_ROOT env var
      2. The installed package's parent (editable / dev install)
      3. Current working directory
    """
    env = os.environ.get("CORTEX_MEM_ROOT")
    if env:
        return Path(env)

    # In an editable install the 'service' package lives next to cortex_mem
    pkg_dir = Path(__file__).resolve().parent.parent
    if (pkg_dir / "service" / "api.py").exists():
        return pkg_dir
    return Path.cwd()


@click.group()
@click.version_option(package_name="cortex-mem")
def main():
    """cortex-mem: Always-On Memory Service"""


@main.command()
@click.option("--port", default=DEFAULT_PORT, help="Service port")
@click.option("--host", default="localhost", help="Bind address")
@click.option("--daemon", "as_daemon", is_flag=True, help="Run as background daemon")
def start(port, host, as_daemon):
    """Start the cortex-mem service."""
    root = _find_service_root()
    config_yaml = root / "service" / "config.yaml"
    if not config_yaml.exists():
        click.echo(f"Error: service/config.yaml not found at {root}", err=True)
        raise SystemExit(1)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            click.echo(f"cortex-mem already running (pid {pid})")
            return
        except OSError:
            PID_FILE.unlink(missing_ok=True)

    if as_daemon:
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "service.api:app",
                "--host", host,
                "--port", str(port),
            ],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        PID_FILE.write_text(str(proc.pid))
        click.echo(f"cortex-mem started on http://{host}:{port} (pid {proc.pid})")
    else:
        import uvicorn

        sys.path.insert(0, str(root))
        click.echo(f"cortex-mem starting on http://{host}:{port} (foreground)")
        uvicorn.run("service.api:app", host=host, port=port, log_level="info")


@main.command()
def stop():
    """Stop the cortex-mem service."""
    if not PID_FILE.exists():
        click.echo("cortex-mem is not running (no pid file)")
        return

    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"cortex-mem stopped (pid {pid})")
    except OSError:
        click.echo(f"Process {pid} not found (already stopped?)")
    finally:
        PID_FILE.unlink(missing_ok=True)


@main.command()
def status():
    """Check service health."""
    import httpx

    try:
        r = httpx.get(f"http://localhost:{DEFAULT_PORT}/health", timeout=3.0)
        data = r.json()
        click.echo(f"  cortex-mem: {data['status']}")
        click.echo(f"  Uptime:     {data['uptime_seconds']}s")
        tiers = data.get("tiers", {})
        total = sum(tiers.values())
        click.echo(f"  Entries:    {total} ({', '.join(f'{k}={v}' for k, v in tiers.items())})")
    except Exception:
        click.echo("  cortex-mem is not running")
        raise SystemExit(1)


@main.command()
@click.argument("source", type=click.Path(exists=True))
def migrate(source):
    """Migrate data from an OpenClaw workspace directory."""
    import asyncio

    root = _find_service_root()
    sys.path.insert(0, str(root))

    from migrate_workspace import run_migration  # type: ignore[import-untyped]

    asyncio.run(run_migration(Path(source)))
    click.echo("Migration complete")


@main.command()
@click.argument("query")
@click.option("--limit", default=5, help="Max results")
@click.option("--tier", multiple=True, help="Filter by tier (episodic, semantic, procedural)")
def search(query, limit, tier):
    """Search memory."""
    import httpx

    body: dict = {"query": query, "limit": limit}
    if tier:
        body["tier"] = list(tier)

    try:
        r = httpx.post(
            f"http://localhost:{DEFAULT_PORT}/memory/search",
            json=body,
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        total = data.get("total", 0)
        click.echo(f"Found {total} result(s):\n")
        for hit in data.get("results", []):
            entry = hit.get("entry", {})
            score = hit.get("score", 0)
            title = entry.get("title") or entry.get("skill_name") or entry.get("subject", "untitled")
            click.echo(f"  [{score:.2f}] {title}")
    except Exception as exc:
        click.echo(f"Search failed: {exc}", err=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

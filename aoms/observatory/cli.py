"""CLI entry point for the Recall Observatory."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import click

from aoms.observatory.server import serve
from aoms.settings import AOMSSettings


@click.command("observe")
@click.option(
    "--port",
    type=click.IntRange(min=1, max=65_535),
    default=8765,
    show_default=True,
    help="IPv4 loopback port.",
)
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path, file_okay=False),
    envvar="AOMS_DATA_DIR",
    help="AOMS data directory (default: platform data dir; env: AOMS_DATA_DIR).",
)
def observe_command(port: int, data_dir: Path | None) -> None:
    """Browse memories and inspect recall evidence on loopback."""

    environ = dict(os.environ)
    if data_dir is not None:
        environ["AOMS_DATA_DIR"] = str(data_dir)
    settings = AOMSSettings.load(environ)
    if not settings.db_path.is_file():
        raise click.ClickException(
            f"AOMS is not initialized at {settings.data_dir}. "
            f"Run: cortex-mem init --data-dir {settings.data_dir}"
        )
    try:
        serve(settings.db_path, port=port)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise click.ClickException(f"could not start Observatory: {exc}") from exc


__all__ = ["observe_command"]

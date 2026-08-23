"""Portable settings for the AOMS v2 core."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict


def _platform_data_dir() -> Path:
    """Import lazily so an explicit data-dir override needs no platform probe."""

    from platformdirs import user_data_path

    return user_data_path("aoms", appauthor=False)


class AOMSSettings(BaseModel):
    """Resolved storage locations with an optional ``AOMS_DATA_DIR`` override."""

    model_config = ConfigDict(frozen=True)

    data_dir: Path
    db_path: Path

    @classmethod
    def load(cls, environ: Mapping[str, str] | None = None) -> AOMSSettings:
        env = os.environ if environ is None else environ
        override = env.get("AOMS_DATA_DIR")
        if override:
            data_dir = Path(override).expanduser().resolve()
        else:
            data_dir = _platform_data_dir().resolve()
        return cls(data_dir=data_dir, db_path=data_dir / "aoms.sqlite3")

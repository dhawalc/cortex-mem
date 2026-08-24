"""Portable settings for the AOMS v2 core."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def _platform_data_dir() -> Path:
    """Import lazily so an explicit data-dir override needs no platform probe."""

    from platformdirs import user_data_path

    return user_data_path("aoms", appauthor=False)


class AOMSSettings(BaseModel):
    """Resolved storage locations with an optional ``AOMS_DATA_DIR`` override."""

    model_config = ConfigDict(frozen=True)

    data_dir: Path
    db_path: Path
    receipt_retention: int = Field(default=1_000, ge=1)
    embedding_provider: str = "fastembed"
    embedding_model: str | None = None
    embedding_dimensions: int | None = Field(default=None, ge=1)
    ollama_url: str = "http://localhost:11434"

    @classmethod
    def load(cls, environ: Mapping[str, str] | None = None) -> AOMSSettings:
        env = os.environ if environ is None else environ
        override = env.get("AOMS_DATA_DIR")
        if override:
            data_dir = Path(override).expanduser().resolve()
        else:
            data_dir = _platform_data_dir().resolve()
        retention_text = env.get("AOMS_RECEIPT_RETENTION", "1000")
        try:
            receipt_retention = int(retention_text)
        except ValueError as exc:
            raise ValueError("AOMS_RECEIPT_RETENTION must be an integer") from exc
        return cls(
            data_dir=data_dir,
            db_path=data_dir / "aoms.sqlite3",
            receipt_retention=receipt_retention,
            embedding_provider=env.get("AOMS_EMBEDDING_PROVIDER", "fastembed")
            .strip()
            .casefold(),
            embedding_model=env.get("AOMS_EMBEDDING_MODEL"),
            embedding_dimensions=(
                int(env["AOMS_EMBEDDING_DIMENSIONS"])
                if "AOMS_EMBEDDING_DIMENSIONS" in env
                else None
            ),
            ollama_url=env.get("AOMS_OLLAMA_URL", "http://localhost:11434"),
        )

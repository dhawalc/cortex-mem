"""Portable settings for the AOMS v2 core."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aoms.contest import Ruleset


def _platform_data_dir() -> Path:
    """Import lazily so an explicit data-dir override needs no platform probe."""

    from platformdirs import user_data_path

    return user_data_path("aoms", appauthor=False)


def _parse_contest_triggers(raw: str) -> frozenset[str]:
    """Parse ``AOMS_CONTEST_TRIGGERS`` into the trigger set to put in force.

    An empty value — or the explicit spelling ``none`` — disables write gating
    entirely: every write is admitted to its slot and nothing is routed to the
    ledger. That is a supported configuration, not a broken one, so it is
    spelled out rather than inferred. Receipts still record the incumbents and
    the ruleset digest, so the audit trail says which configuration admitted a
    write.
    """

    from aoms.contracts import ContestTrigger

    requested = [part.strip().casefold() for part in raw.split(",") if part.strip()]
    if not requested or requested == ["none"]:
        return frozenset()
    if "none" in requested:
        raise ValueError(
            "AOMS_CONTEST_TRIGGERS: 'none' disables every trigger and cannot be "
            "combined with others"
        )

    selectable = {
        trigger.value
        for trigger in ContestTrigger
        if trigger is not ContestTrigger.POLICY_HOLD
    }
    for name in requested:
        if name == ContestTrigger.POLICY_HOLD.value:
            raise ValueError(
                f"AOMS_CONTEST_TRIGGERS: {name!r} is a reserved seam; no "
                "policy-hold rule ships in v1"
            )
        if name not in selectable:
            options = ", ".join(sorted(selectable))
            raise ValueError(
                f"AOMS_CONTEST_TRIGGERS: unknown trigger {name!r}; choose from "
                f"{options}, or 'none' to disable gating"
            )
    return frozenset(requested)


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
    contest_sla_days: int = Field(default=14, ge=1)
    contest_expiry_days: int = Field(default=30, ge=1)
    # ``None`` means "unset": keep the shipped default trigger set. An empty
    # frozenset is a different thing — an operator explicitly turning gating
    # off — so the two are not collapsed.
    contest_triggers: frozenset[str] | None = None

    @property
    def ruleset(self) -> "Ruleset":
        """The contest configuration this process stamps on its receipts."""

        from aoms.contest import Ruleset
        from aoms.contracts import ContestTrigger

        if self.contest_triggers is None:
            return Ruleset(
                contest_sla_days=self.contest_sla_days,
                contest_expiry_days=self.contest_expiry_days,
            )
        return Ruleset(
            enabled_triggers=frozenset(
                ContestTrigger(value) for value in self.contest_triggers
            ),
            contest_sla_days=self.contest_sla_days,
            contest_expiry_days=self.contest_expiry_days,
        )

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
        try:
            contest_sla_days = int(env.get("AOMS_CONTEST_SLA_DAYS", "14"))
            contest_expiry_days = int(env.get("AOMS_CONTEST_EXPIRY_DAYS", "30"))
        except ValueError as exc:
            raise ValueError("AOMS contest day settings must be integers") from exc
        triggers_text = env.get("AOMS_CONTEST_TRIGGERS")
        contest_triggers = (
            None if triggers_text is None else _parse_contest_triggers(triggers_text)
        )
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
            contest_sla_days=contest_sla_days,
            contest_expiry_days=contest_expiry_days,
            contest_triggers=contest_triggers,
        )

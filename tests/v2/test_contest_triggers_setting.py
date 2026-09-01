"""``AOMS_CONTEST_TRIGGERS`` — the kill switch for the write gate.

Before this setting existed, any caller that set ``claim_key`` was gated by
``V1_TRIGGERS`` with no way to turn it off short of editing source. These tests
pin the three things that makes safe: the default is unchanged, an explicit
empty set admits what would otherwise be contested, and the receipt digest
tells the two configurations apart.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from aoms.contest import (
    DEFAULT_RULESET,
    V1_TRIGGERS,
    Ruleset,
    SlotOccupant,
    SlotState,
    WriteIntent,
    decide,
)
from aoms.application import AOMSApplication
from aoms.contracts import (
    ContestTrigger,
    MemoryKind,
    RememberRequest,
    Scope,
    ScopeContext,
    WriteDisposition,
)
from aoms.embeddings import NullProvider
from aoms.repositories import SQLiteMemoryRepository
from aoms.settings import AOMSSettings

NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _settings(**environ: str) -> AOMSSettings:
    return AOMSSettings.load({"AOMS_DATA_DIR": "/tmp/aoms-trigger-settings", **environ})


def _occupied_slot() -> SlotState:
    return SlotState(
        occupants=(
            SlotOccupant(
                record_id="incumbent-1",
                content_sha256="a" * 64,
                asserted_at=NOW,
            ),
        )
    )


def _undeclared_intent() -> WriteIntent:
    """A write that collides with the incumbent and declares no supersession."""

    return WriteIntent(
        kind=MemoryKind.DECISION,
        scope=Scope.WORKSPACE,
        content_sha256="b" * 64,
        claim_key="deploy-region",
        supersedes=None,
        asserted_at=NOW + timedelta(days=1),
        derived_from=(),
    )


def test_default_ruleset_is_unchanged_when_the_variable_is_unset() -> None:
    settings = _settings()

    assert settings.contest_triggers is None
    assert settings.ruleset.enabled_triggers == V1_TRIGGERS
    assert settings.ruleset.digest == DEFAULT_RULESET.digest


def test_default_still_contests_an_undeclared_collision() -> None:
    decision = decide(
        _undeclared_intent(), _occupied_slot(), now=NOW, ruleset=_settings().ruleset
    )

    assert decision.disposition is WriteDisposition.CONTESTED
    assert decision.trigger is ContestTrigger.SLOT_COLLISION


@pytest.mark.parametrize("value", ["", "   ", "none", "NONE", " none "])
def test_an_explicit_empty_set_admits_what_would_otherwise_be_contested(
    value: str,
) -> None:
    settings = _settings(AOMS_CONTEST_TRIGGERS=value)

    assert settings.contest_triggers == frozenset()
    assert settings.ruleset.enabled_triggers == frozenset()

    decision = decide(
        _undeclared_intent(), _occupied_slot(), now=NOW, ruleset=settings.ruleset
    )

    assert decision.disposition is WriteDisposition.ADMITTED
    # The incumbent is still named, and the receipt does not claim a
    # supersession the writer never declared.
    assert decision.incumbent_ids == ("incumbent-1",)
    assert decision.detail == {"declared_supersession": False}


def test_admitting_with_gating_off_still_reports_a_real_declaration() -> None:
    intent = replace(_undeclared_intent(), supersedes="incumbent-1")

    decision = decide(
        intent,
        _occupied_slot(),
        now=NOW,
        ruleset=_settings(AOMS_CONTEST_TRIGGERS="none").ruleset,
    )

    assert decision.disposition is WriteDisposition.ADMITTED
    assert decision.detail == {"declared_supersession": True}


def test_a_subset_puts_exactly_that_subset_in_force() -> None:
    settings = _settings(AOMS_CONTEST_TRIGGERS="retrograde-displacement")

    assert settings.ruleset.enabled_triggers == frozenset({ContestTrigger.RETROGRADE})

    # Slot collision is off, so the undeclared write is admitted ...
    assert (
        decide(
            _undeclared_intent(), _occupied_slot(), now=NOW, ruleset=settings.ruleset
        ).disposition
        is WriteDisposition.ADMITTED
    )

    # ... but a backdated one still trips the trigger that is on.
    backdated = replace(_undeclared_intent(), asserted_at=NOW - timedelta(days=1))
    decision = decide(backdated, _occupied_slot(), now=NOW, ruleset=settings.ruleset)
    assert decision.disposition is WriteDisposition.CONTESTED
    assert decision.trigger is ContestTrigger.RETROGRADE


def test_the_deferred_trigger_can_be_switched_back_on() -> None:
    """DERIVED ships disabled, but it stays implemented and configurable."""

    settings = _settings(
        AOMS_CONTEST_TRIGGERS="slot-collision,retrograde-displacement,"
        "derived-from-memory"
    )

    assert ContestTrigger.DERIVED in settings.ruleset.enabled_triggers

    intent = replace(
        _undeclared_intent(),
        supersedes="incumbent-1",
        derived_from=("read-from-memory",),
    )
    decision = decide(intent, _occupied_slot(), now=NOW, ruleset=settings.ruleset)

    assert decision.trigger is ContestTrigger.DERIVED


def test_the_digest_differs_between_configurations() -> None:
    """The audit trail must be able to tell the configurations apart."""

    default = _settings().ruleset
    disabled = _settings(AOMS_CONTEST_TRIGGERS="none").ruleset
    # An explicit bare "slot-collision" is the default set as of version 3,
    # so use a genuinely different subset for the distinctness check.
    subset = _settings(
        AOMS_CONTEST_TRIGGERS="slot-collision,retrograde-displacement"
    ).ruleset
    everything = _settings(
        AOMS_CONTEST_TRIGGERS="slot-collision,retrograde-displacement,"
        "derived-from-memory"
    ).ruleset

    digests = {
        "default": default.digest,
        "disabled": disabled.digest,
        "subset": subset.digest,
        "everything": everything.digest,
    }
    assert len(set(digests.values())) == len(digests), digests

    # Same set written a different way is the same configuration. (As of
    # version 3 this set is the opt-in subset, no longer the default.)
    assert (
        _settings(AOMS_CONTEST_TRIGGERS="retrograde-displacement, slot-collision")
        .ruleset.digest
        == subset.digest
    )


def test_the_setting_survives_a_round_trip_through_the_env_spelling() -> None:
    for spelling in ("SLOT-COLLISION", " slot-collision ", "slot-collision,"):
        assert _settings(AOMS_CONTEST_TRIGGERS=spelling).ruleset.enabled_triggers == (
            frozenset({ContestTrigger.SLOT_COLLISION})
        )


def test_an_unknown_trigger_is_refused_with_the_valid_options() -> None:
    with pytest.raises(ValueError, match="unknown trigger 'slot_collision'"):
        _settings(AOMS_CONTEST_TRIGGERS="slot_collision")

    with pytest.raises(ValueError, match="unknown trigger"):
        _settings(AOMS_CONTEST_TRIGGERS="slot-collision,typo")


def test_policy_hold_is_refused_as_a_seam_not_a_rule() -> None:
    with pytest.raises(ValueError, match="reserved seam"):
        _settings(AOMS_CONTEST_TRIGGERS="policy-hold")

    # And the invariant still holds if a Ruleset is built directly.
    with pytest.raises(ValueError, match="policy-hold is a seam"):
        Ruleset(enabled_triggers=frozenset({ContestTrigger.POLICY_HOLD}))


def test_none_cannot_be_combined_with_a_real_trigger() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        _settings(AOMS_CONTEST_TRIGGERS="none,slot-collision")


# --- the switch has to reach a real write, not just decide() ---------------


def _application(tmp_path, ruleset):
    return AOMSApplication(
        SQLiteMemoryRepository(tmp_path / "aoms.sqlite3"),
        scope_context=ScopeContext(agent_id="agent-a", workspace_id="/workspace"),
        embedding_provider=NullProvider(),
        background_embeddings=False,
        ruleset=ruleset,
    )


async def _collide(application) -> tuple:
    """Two different answers to one claim, the second declaring nothing."""

    common = {
        "kind": MemoryKind.FACT,
        "scope": Scope.WORKSPACE,
        "claim_key": "deploy-region",
    }
    first = await application.remember(
        RememberRequest(id="a", content="the region is eu-west-1", **common)
    )
    second = await application.remember(
        RememberRequest(id="b", content="the region is us-east-1", **common)
    )
    return first, second


@pytest.mark.asyncio
async def test_the_default_still_contests_end_to_end(tmp_path) -> None:
    application = _application(tmp_path, _settings().ruleset)

    _, second = await _collide(application)

    assert second.disposition is WriteDisposition.CONTESTED
    assert (await application.repository.list_contests()).total == 1


@pytest.mark.asyncio
async def test_disabling_gating_admits_the_same_write_and_records_it(
    tmp_path,
) -> None:
    settings = _settings(AOMS_CONTEST_TRIGGERS="none")
    application = _application(tmp_path, settings.ruleset)

    _, second = await _collide(application)

    assert second.disposition is WriteDisposition.ADMITTED
    assert second.contest_id is None
    # Nothing is gated, but the write is still receipted, still names the
    # incumbent it landed on top of, and still says under which configuration.
    assert (await application.repository.list_contests()).total == 0
    assert await application.repository.write_receipt_count() == 2
    receipts = await application.repository.recent_write_receipts(limit=2)
    admitted = next(receipt for receipt in receipts if receipt.record_id == "b")
    assert admitted.disposition is WriteDisposition.ADMITTED
    assert admitted.incumbent_ids == ["a"]
    assert admitted.trigger is None
    assert admitted.ruleset_digest == settings.ruleset.digest
    assert admitted.ruleset_digest != DEFAULT_RULESET.digest

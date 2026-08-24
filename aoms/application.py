"""Transport-independent application service for AOMS v2."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from aoms.contest import (
    DEFAULT_RULESET,
    Decision,
    Ruleset,
    SlotOccupant,
    SlotState,
    WriteIntent,
    content_digest,
    decide,
)
from aoms.contracts import (
    ContestEntry,
    ContestResolution,
    ContestState,
    ContestTrigger,
    MemoryRecord,
    IntegrityReport,
    Provenance,
    RecallRequest,
    RecallResult,
    ReceiptPruneReport,
    RememberRequest,
    RememberResult,
    SupersedeRequest,
    SearchRequest,
    SearchResult,
    Scope,
    ScopeContext,
    WriteDisposition,
)
from aoms.embedding_jobs import EmbeddingSweepResult, sweep_pending_embeddings
from aoms.embeddings import EmbeddingProvider, FastEmbedProvider
from aoms.recall import RecallEngine
from aoms.receipts import ENGINE_VERSION, RecallReceipt, WriteReceipt
from aoms.repositories.base import (
    LedgerWrite,
    MemoryRepository,
    RecordContentConflictError,
    VectorRepository,
)
from aoms.truth import ChainTimeline, reconstruct_timeline

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ContestResolutionResult:
    """What one operator verdict did, in terms the CLI can print verbatim."""

    entry: ContestEntry
    successor_id: str | None
    summary: str


class AOMSApplication:
    def __init__(
        self,
        repository: MemoryRepository,
        *,
        scope_context: ScopeContext,
        receipt_repository: MemoryRepository | None = None,
        recall_engine: RecallEngine | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        background_embeddings: bool = True,
        ruleset: Ruleset = DEFAULT_RULESET,
    ):
        self.repository = repository
        self.scope_context = scope_context
        self.receipt_repository = receipt_repository or repository
        self.embedding_provider = embedding_provider or FastEmbedProvider()
        self.background_embeddings = background_embeddings
        self.ruleset = ruleset
        self._embedding_tasks: set[asyncio.Task[EmbeddingSweepResult]] = set()
        if recall_engine is not None and recall_engine.scope_context != scope_context:
            raise ValueError("recall_engine scope context must match the application")
        self.recall_engine = recall_engine or RecallEngine(
            repository,
            self.receipt_repository,
            embedding_provider=self.embedding_provider,
            scope_context=scope_context,
            ruleset=ruleset,
        )

    async def remember(self, request: RememberRequest) -> RememberResult:
        return await self._remember(request, create_only=False)

    async def _remember(
        self, request: RememberRequest, *, create_only: bool
    ) -> RememberResult:
        await self.repository.initialize()
        record_id = request.id or str(uuid4())
        existing = await self.repository.get(record_id)
        if create_only and existing is not None:
            raise ValueError("memory id is already in use; no record was changed")
        if existing is not None and not self._can_access(existing):
            raise PermissionError("memory id belongs to an inaccessible scope")
        if existing is not None:
            if existing.content != request.content:
                raise ValueError(
                    "in-place content change; append a successor with `supersedes` "
                    "instead."
                )
            return RememberResult(
                record=existing,
                created=False,
                disposition=existing.disposition,
            )
        now = datetime.now(timezone.utc)
        scope_agent_id = (
            self.scope_context.agent_id
            if request.scope is Scope.AGENT_PRIVATE
            else None
        )
        scope_workspace_id = (
            self.scope_context.workspace_id
            if request.scope is Scope.WORKSPACE
            else None
        )
        provenance = request.provenance or Provenance(source="application")
        provenance = provenance.model_copy(
            update={
                "details": {
                    **provenance.details,
                    "agent_id": self.scope_context.agent_id,
                }
            }
        )
        decision, ledger_context = await self._adjudicate(
            request,
            record_id=record_id,
            scope_agent_id=scope_agent_id,
            scope_workspace_id=scope_workspace_id,
            provenance=provenance,
            now=now,
        )
        record = MemoryRecord(
            id=record_id,
            kind=request.kind,
            content=request.content,
            tags=request.tags,
            scope=request.scope,
            scope_agent_id=scope_agent_id,
            scope_workspace_id=scope_workspace_id,
            created_by_agent_id=self.scope_context.agent_id,
            provenance=provenance,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            supersedes=request.supersedes,
            metadata=request.metadata,
            claim_key=request.claim_key,
            disposition=decision.disposition,
            observation_id=request.observation_id,
        )
        ledger = self._ledger_write(
            record, decision=decision, context=ledger_context, now=now
        )
        conditional_result = None
        if self.embedding_provider.profile is not None and isinstance(
            self.repository, VectorRepository
        ):
            if create_only:
                await self.repository.store_new_with_embedding_pending(
                    record, self.embedding_provider.profile, ledger=ledger
                )
            else:
                try:
                    conditional_result = (
                        await self.repository.store_if_content_unchanged_with_embedding_pending(
                            record, self.embedding_provider.profile, ledger=ledger
                        )
                    )
                except RecordContentConflictError as exc:
                    self._raise_retained_conflict(exc.retained)
            if self.background_embeddings and (
                conditional_result is None or conditional_result.created
            ):
                task = asyncio.create_task(
                    self.catch_up_embeddings(batch_size=1, max_batches=1),
                    name=f"aoms-embed-{record.id}",
                )
                self._embedding_tasks.add(task)
                task.add_done_callback(self._embedding_task_done)
        else:
            if create_only:
                await self.repository.store_new(record, ledger=ledger)
            else:
                try:
                    conditional_result = (
                        await self.repository.store_if_content_unchanged(
                            record, ledger=ledger
                        )
                    )
                except RecordContentConflictError as exc:
                    self._raise_retained_conflict(exc.retained)
        if conditional_result is not None:
            if not conditional_result.created and not self._can_access(
                conditional_result.record
            ):
                raise PermissionError("memory id belongs to an inaccessible scope")
            return self._remember_result(
                conditional_result.record,
                created=conditional_result.created,
                decision=decision,
                ledger=ledger,
            )
        return self._remember_result(
            record, created=True, decision=decision, ledger=ledger
        )

    async def _adjudicate(
        self,
        request: RememberRequest,
        *,
        record_id: str,
        scope_agent_id: str | None,
        scope_workspace_id: str | None,
        provenance: Provenance,
        now: datetime,
    ) -> tuple[Decision, ContestEntry | None]:
        """Run the gate, returning its verdict and any entry to coalesce into.

        A write that declares no ``claim_key`` never reaches ``decide`` with a
        slot to collide with, and never touches the ledger at all. That is the
        migration sentinel: for every record written before this feature
        existed, and every caller that has not adopted it, nothing changes.
        """

        if request.claim_key is None:
            return Decision(disposition=WriteDisposition.ADMITTED), None

        occupants = await self.repository.slot_occupants(
            claim_key=request.claim_key,
            scope=request.scope,
            scope_agent_id=scope_agent_id,
            scope_workspace_id=scope_workspace_id,
        )
        slot = SlotState(
            occupants=tuple(
                SlotOccupant(
                    record_id=occupant.id,
                    content_sha256=content_digest(occupant.content),
                    asserted_at=occupant.provenance.asserted_at,
                    created_at=occupant.created_at,
                )
                for occupant in occupants
                if occupant.id != record_id
            )
        )
        intent = WriteIntent(
            kind=request.kind,
            scope=request.scope,
            content_sha256=content_digest(request.content),
            claim_key=request.claim_key,
            supersedes=request.supersedes,
            asserted_at=provenance.asserted_at,
            derived_from=tuple(provenance.derived_from),
        )
        decision = decide(intent, slot, now=now, ruleset=self.ruleset)
        if not decision.contested:
            return decision, None
        coalesce_into = await self.repository.open_contest_for_slot(
            claim_key=request.claim_key,
            scope=request.scope,
            scope_agent_id=scope_agent_id,
            scope_workspace_id=scope_workspace_id,
            opened_by_agent_id=self.scope_context.agent_id,
        )
        return decision, coalesce_into

    def _ledger_write(
        self,
        record: MemoryRecord,
        *,
        decision: Decision,
        context: ContestEntry | None,
        now: datetime,
    ) -> LedgerWrite | None:
        """Build the rows that must commit with the record, or none at all."""

        if record.claim_key is None:
            # No decision was made, so there is nothing to receipt.
            return None
        contest: ContestEntry | None = None
        coalesced_id: str | None = None
        contest_id: str | None = None
        if decision.contested:
            if context is not None:
                coalesced_id = context.contest_id
                contest_id = context.contest_id
            else:
                # Server-generated, always. Never derived from the caller's
                # record id, which accepts 256 arbitrary characters and would
                # otherwise render attacker prose into every recalled context.
                contest_id = str(uuid4())
                contest = ContestEntry(
                    contest_id=contest_id,
                    record_id=record.id,
                    claim_key=record.claim_key,
                    observation_id=record.observation_id,
                    scope=record.scope,
                    scope_agent_id=record.scope_agent_id,
                    scope_workspace_id=record.scope_workspace_id,
                    incumbent_ids=list(decision.incumbent_ids),
                    trigger=decision.trigger or ContestTrigger.SLOT_COLLISION,
                    trigger_detail=dict(decision.detail),
                    opened_at=now,
                    opened_by_agent_id=self.scope_context.agent_id,
                    state=ContestState.OPEN,
                )
        receipt = WriteReceipt(
            receipt_id=str(uuid4()),
            created_at=now,
            record_id=record.id,
            claim_key=record.claim_key,
            agent_id=self.scope_context.agent_id,
            workspace_id=self.scope_context.workspace_id,
            kind=record.kind,
            scope=record.scope,
            content_sha256=content_digest(record.content),
            incumbent_ids=list(decision.incumbent_ids),
            disposition=decision.disposition,
            trigger=decision.trigger,
            trigger_detail=dict(decision.detail),
            contest_id=contest_id,
            asserted_at=record.provenance.asserted_at,
            derived_from=list(record.provenance.derived_from),
            ruleset_digest=self.ruleset.digest,
            occurrence_count=(
                context.occurrence_count + 1 if context is not None else 1
            ),
            engine_version=ENGINE_VERSION,
        )
        return LedgerWrite(
            receipt=receipt, contest=contest, coalesced_contest_id=coalesced_id
        )

    @staticmethod
    def _remember_result(
        record: MemoryRecord,
        *,
        created: bool,
        decision: Decision,
        ledger: LedgerWrite | None,
    ) -> RememberResult:
        return RememberResult(
            record=record,
            created=created,
            disposition=record.disposition,
            contest_id=ledger.receipt.contest_id if ledger is not None else None,
            incumbent_ids=list(decision.incumbent_ids),
        )

    async def catch_up_embeddings(
        self,
        *,
        batch_size: int = 64,
        max_batches: int | None = None,
        lease_seconds: int = 300,
    ) -> EmbeddingSweepResult:
        """Drain durable pending work; safe for periodic CLI/orchestrator sweeps."""

        if not isinstance(self.repository, VectorRepository):
            return EmbeddingSweepResult()
        return await sweep_pending_embeddings(
            self.repository,
            self.embedding_provider,
            batch_size=batch_size,
            max_batches=max_batches,
            lease_seconds=lease_seconds,
        )

    async def wait_for_background_embeddings(self) -> None:
        """Testing/shutdown hook; remember itself never awaits provider work."""

        if self._embedding_tasks:
            await asyncio.gather(*tuple(self._embedding_tasks), return_exceptions=True)

    def _embedding_task_done(self, task: asyncio.Task[EmbeddingSweepResult]) -> None:
        self._embedding_tasks.discard(task)
        try:
            task.result()
        except Exception:  # pragma: no cover - final defensive task boundary
            logger.exception(
                "background embedding sweep failed; durable work remains queued"
            )

    async def search(
        self, request: SearchRequest, *, as_of: datetime | None = None
    ) -> SearchResult:
        if as_of is not None:
            as_of = (
                as_of.replace(tzinfo=timezone.utc)
                if as_of.tzinfo is None
                else as_of.astimezone(timezone.utc)
            )
        return await self.repository.search_by_keyword(
            request, scope_context=self.scope_context, as_of=as_of
        )

    async def supersede(
        self, old_id: str, request: SupersedeRequest
    ) -> RememberResult:
        """Append a visible successor without modifying its predecessor."""

        await self.repository.initialize()
        old = await self.repository.get(old_id)
        if old is None:
            raise LookupError(f"memory not found: {old_id}")
        if not self._can_access(old):
            raise PermissionError("memory id belongs to an inaccessible scope")
        lineage = await self.repository.lineage(
            old_id, scope_context=self.scope_context
        )
        direct_successors = sorted(
            record.id for record in lineage if record.supersedes == old_id
        )
        if direct_successors:
            raise ValueError(
                f"memory is not an apparent head; supersede its successor: "
                f"{', '.join(direct_successors)}"
            )
        successor_id = request.id or str(uuid4())
        if await self.repository.get(successor_id) is not None:
            raise ValueError("successor id is already in use; no record was changed")
        provenance = request.provenance or Provenance(
            source="application-supersede",
            details={"predecessor_id": old.id},
        )
        return await self._remember(
            RememberRequest(
                id=successor_id,
                kind=old.kind,
                content=request.content,
                tags=old.tags,
                scope=old.scope,
                provenance=provenance,
                supersedes=old.id,
                metadata=dict(old.metadata),
                claim_key=request.claim_key or old.claim_key,
            ),
            create_only=True,
        )

    async def resolve_contest(
        self,
        contest_id: str,
        *,
        resolution: ContestResolution,
        resolved_by: str,
        note: str | None = None,
        supersede_incumbent_id: str | None = None,
        new_claim_key: str | None = None,
    ) -> ContestResolutionResult:
        """Apply one named operator verdict. Nothing else changes a disposition.

        ``admit-superseding`` routes through ``supersede``, which appends a
        successor and never rewrites its predecessor. The contested record
        itself stays contested and durable: it is the evidence that this
        happened, and rewriting it would destroy what the ledger exists to keep.
        """

        await self.repository.initialize()
        entry = await self.repository.get_contest(contest_id)
        if entry is None:
            raise LookupError(f"contest not found: {contest_id}")
        contested = await self.repository.get(entry.record_id)
        if contested is None:  # pragma: no cover - protected by the foreign key
            raise LookupError(f"contested record not found: {entry.record_id}")
        if not self._can_access(contested):
            raise PermissionError("contest belongs to an inaccessible scope")

        successor_id: str | None = None
        if resolution is ContestResolution.ADMIT_SUPERSEDING:
            if supersede_incumbent_id is None:
                raise ValueError("admit-superseding requires an incumbent id")
            successor = await self.supersede(
                supersede_incumbent_id,
                SupersedeRequest(
                    content=contested.content,
                    claim_key=contested.claim_key,
                    provenance=Provenance(
                        source="contest-resolution",
                        details={
                            "predecessor_id": supersede_incumbent_id,
                            "contest_id": contest_id,
                            "resolved_by": resolved_by,
                        },
                    ),
                ),
            )
            successor_id = successor.record.id
            summary = (
                f"Admitted as successor {successor_id} to {supersede_incumbent_id}. "
                f"Record {contested.id} stays contested as the ledger's evidence."
            )
        elif resolution is ContestResolution.ADMIT:
            summary = f"Record {contested.id} now holds slot {contested.claim_key}."
        elif resolution is ContestResolution.SET_ASIDE:
            summary = (
                f"Record {contested.id} set aside: nothing was deleted, it stays "
                "searchable with include_contested and can be admitted later."
            )
        else:
            if new_claim_key is None:
                raise ValueError("split requires a new claim key")
            occupants = await self.repository.slot_occupants(
                claim_key=new_claim_key,
                scope=contested.scope,
                scope_agent_id=contested.scope_agent_id,
                scope_workspace_id=contested.scope_workspace_id,
            )
            if occupants:
                raise ValueError(
                    f"claim key {new_claim_key!r} is already held by "
                    f"{', '.join(record.id for record in occupants)}; "
                    "choose a free key rather than creating a second collision"
                )
            summary = (
                f"Record {contested.id} re-filed under slot {new_claim_key} "
                "and admitted there."
            )

        admits = resolution in {ContestResolution.ADMIT, ContestResolution.SPLIT}
        now = datetime.now(timezone.utc)
        receipt = WriteReceipt(
            receipt_id=str(uuid4()),
            created_at=now,
            record_id=contested.id,
            claim_key=new_claim_key or contested.claim_key,
            agent_id=resolved_by,
            workspace_id=self.scope_context.workspace_id,
            kind=contested.kind,
            scope=contested.scope,
            content_sha256=content_digest(contested.content),
            incumbent_ids=list(entry.incumbent_ids),
            disposition=(
                WriteDisposition.ADMITTED if admits else WriteDisposition.CONTESTED
            ),
            trigger=entry.trigger,
            trigger_detail={
                "resolution": resolution.value,
                "contest_id": contest_id,
                "successor_id": successor_id,
            },
            contest_id=contest_id,
            asserted_at=contested.provenance.asserted_at,
            derived_from=list(contested.provenance.derived_from),
            ruleset_digest=self.ruleset.digest,
            occurrence_count=entry.occurrence_count,
            engine_version=ENGINE_VERSION,
        )
        resolved = await self.repository.resolve_contest(
            contest_id,
            resolution=resolution,
            resolved_by=resolved_by,
            note=note,
            receipt=receipt,
            admit_record=admits,
            new_claim_key=new_claim_key,
        )
        return ContestResolutionResult(
            entry=resolved, successor_id=successor_id, summary=summary
        )

    async def recent_write_receipts(self, *, limit: int = 20) -> list[WriteReceipt]:
        """Expose the append-only decision log without a model-facing tool."""

        return await self.repository.recent_write_receipts(limit=limit)

    async def chain_timeline(
        self, record_id: str, *, as_of: datetime | None = None
    ) -> ChainTimeline:
        """Reconstruct only the chain members visible at this read boundary."""

        normalized_as_of = None
        if as_of is not None:
            normalized_as_of = (
                as_of.replace(tzinfo=timezone.utc)
                if as_of.tzinfo is None
                else as_of.astimezone(timezone.utc)
            )
        records = await self.repository.lineage(
            record_id,
            scope_context=self.scope_context,
            as_of=normalized_as_of,
        )
        if not records:
            raise LookupError(f"visible memory not found at boundary: {record_id}")
        return reconstruct_timeline(record_id, records, as_of=normalized_as_of)

    async def recall(self, request: RecallRequest) -> RecallResult:
        return await self.recall_engine.recall(request)

    async def recent_recall_receipts(self, *, limit: int = 20) -> list[RecallReceipt]:
        """Return newest receipts for inspection and generated proof artifacts."""

        return await self.receipt_repository.recent_recall_receipts(
            limit=limit, scope_context=self.scope_context
        )

    async def prune_recall_receipts(
        self, *, retain: int | None = None
    ) -> ReceiptPruneReport:
        """Apply receipt retention without exposing maintenance as a tool call."""

        return await self.receipt_repository.prune_recall_receipts(retain=retain)

    async def check_integrity(self) -> IntegrityReport:
        """Compare canonical memories with FTS and vector projections."""

        return await self.repository.integrity_report()

    def _can_access(self, record: MemoryRecord) -> bool:
        if record.scope is Scope.USER_GLOBAL:
            return True
        if record.scope is Scope.WORKSPACE:
            return record.scope_workspace_id == self.scope_context.workspace_id
        return record.scope_agent_id == self.scope_context.agent_id

    def _raise_retained_conflict(self, retained: MemoryRecord) -> None:
        if not self._can_access(retained):
            raise PermissionError("memory id belongs to an inaccessible scope")
        raise ValueError(
            "in-place content change; append a successor with `supersedes` instead."
        )

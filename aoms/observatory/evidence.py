"""Receipt-context evidence helpers."""

from __future__ import annotations

from dataclasses import dataclass

from aoms.recall import (
    PACK_SEPARATOR,
    BudgetPacker,
    TiktokenTokenizer,
    memory_content_text,
    render_memory_block,
)
from aoms.receipts import RecallReceipt
from aoms.observatory.repository import ObservatoryRepository


@dataclass(frozen=True, slots=True)
class ContextEvidence:
    context: str
    token_count: int
    source: str
    reconciled: bool
    warning: str | None = None


def receipt_context(
    receipt: RecallReceipt, repository: ObservatoryRepository
) -> ContextEvidence:
    """Return exact retained context, or a clearly labeled legacy reconstruction."""

    tokenizer = TiktokenTokenizer()
    if receipt.context is not None:
        count = tokenizer.count(receipt.context)
        return ContextEvidence(
            context=receipt.context,
            token_count=count,
            source="immutable receipt evidence",
            reconciled=count == receipt.total_tokens,
            warning=None if count == receipt.total_tokens else "stored context token mismatch",
        )

    blocks: list[str] = []
    missing: list[str] = []
    suppressed = set(receipt.superseded_suppressed)
    packer = BudgetPacker(tokenizer)
    for selected in receipt.selected:
        record = repository.memory(selected.memory_id)
        if record is None:
            missing.append(selected.memory_id)
            continue
        predecessor = (
            repository.memory(record.supersedes)
            if record.supersedes and record.supersedes in suppressed
            else None
        )
        content = memory_content_text(record)
        if selected.truncated:
            block, _ = packer._truncate_first_record(  # noqa: SLF001
                record,
                content,
                selected.token_cost,
                supersedes=predecessor,
            )
            if block is not None:
                blocks.append(block)
        else:
            blocks.append(
                render_memory_block(record, content, truncated=False, supersedes=predecessor)
            )
    context = PACK_SEPARATOR.join(blocks)
    count = tokenizer.count(context)
    warnings = [
        "legacy receipt: reconstructed from the current memory snapshot",
    ]
    if missing:
        warnings.append("missing record(s): " + ", ".join(missing))
    return ContextEvidence(
        context=context,
        token_count=count,
        source="legacy reconstruction",
        reconciled=not missing and count == receipt.total_tokens,
        warning="; ".join(warnings),
    )


__all__ = ["ContextEvidence", "receipt_context"]

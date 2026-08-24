"""Shared receipt HTML partials for the Observatory and anatomy artifact."""

from __future__ import annotations

import html
from collections.abc import Sequence

from aoms.receipts import CandidateScore, RecallReceipt


def escape_html(value: object) -> str:
    return html.escape(str(value), quote=True)


def enum_list(values: Sequence[object] | None) -> str:
    if values is None:
        return "all visible"
    return ", ".join(
        escape_html(getattr(value, "value", value)) for value in values
    )


def format_score(value: float) -> str:
    return f"{value:.4f}"


def candidate_rows(receipt: RecallReceipt) -> str:
    candidates: list[CandidateScore] = []
    seen: set[str] = set()
    for candidate in [*receipt.top_candidates, *receipt.rejected_sample]:
        if candidate.memory_id not in seen:
            seen.add(candidate.memory_id)
            candidates.append(candidate)
    if not candidates:
        return '<tr><td colspan="8" class="muted">No visible candidates.</td></tr>'

    rows: list[str] = []
    for position, candidate in enumerate(candidates, start=1):
        breakdown = "".join(
            "<li><code>{}</code>: raw {} × weight {} = {}</li>".format(
                escape_html(name),
                format_score(component.raw),
                format_score(component.weight),
                format_score(component.contribution),
            )
            for name, component in candidate.breakdown.items()
        )
        outcome = (
            '<span class="pill selected">selected</span>'
            if candidate.selected
            else '<span class="pill rejected">rejected</span>'
        )
        reason = candidate.rejection_reason or "—"
        rows.append(
            "<tr>"
            f"<td>{position}</td>"
            f"<td><code>{escape_html(candidate.memory_id)}</code></td>"
            f"<td>{escape_html(candidate.kind.value)}</td>"
            f"<td>{escape_html(candidate.scope.value)}</td>"
            f"<td>{escape_html(', '.join(candidate.retrieval_sources) or 'unspecified')}</td>"
            f"<td><strong>{format_score(candidate.total_score)}</strong>"
            f'<ul class="breakdown">{breakdown}</ul></td>'
            f"<td>{outcome}</td>"
            f"<td>{escape_html(reason)}</td>"
            "</tr>"
        )
    return "".join(rows)


def token_rows(receipt: RecallReceipt) -> str:
    rows = "".join(
        f"<tr><td>{index}</td><td><code>{escape_html(item.memory_id)}</code></td>"
        f"<td>{item.token_cost}</td><td>{'yes' if item.truncated else 'no'}</td></tr>"
        for index, item in enumerate(receipt.selected, start=1)
    )
    selected_sum = sum(item.token_cost for item in receipt.selected)
    state = "reconciled" if selected_sum == receipt.total_tokens else "mismatch"
    return (
        rows
        + '<tr class="total"><td colspan="2">Sum of serialized marginal costs</td>'
        f"<td>{selected_sum}</td><td>{state}</td></tr>"
        + '<tr class="total"><td colspan="2">Receipt total</td>'
        f"<td>{receipt.total_tokens}</td><td>{state}</td></tr>"
    )


__all__ = [
    "candidate_rows",
    "enum_list",
    "escape_html",
    "format_score",
    "token_rows",
]

"""Generate a publishable static teardown of one or more recall receipts.

The report deliberately depends on the versioned receipt contract and the
repository protocol, not on ranker implementation details.  It can therefore
be generated after a run, without starting AOMS or contacting another service.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from aoms.contracts import MemoryRecord
from aoms.receipts import CandidateScore, RecallReceipt
from aoms.repositories import MemoryRepository, SQLiteMemoryRepository


@dataclass(frozen=True, slots=True)
class LabeledReceipt:
    """A receipt paired with the public name of its engine configuration."""

    label: str
    receipt: RecallReceipt


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _enum_list(values: Sequence[object] | None) -> str:
    if values is None:
        return "all visible"
    return ", ".join(_e(getattr(value, "value", value)) for value in values)


def _fmt_score(value: float) -> str:
    return f"{value:.4f}"


def _candidate_rows(receipt: RecallReceipt) -> str:
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
                _e(name),
                _fmt_score(component.raw),
                _fmt_score(component.weight),
                _fmt_score(component.contribution),
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
            f"<td><code>{_e(candidate.memory_id)}</code></td>"
            f"<td>{_e(candidate.kind.value)}</td>"
            f"<td>{_e(candidate.scope.value)}</td>"
            f"<td>{_e(', '.join(candidate.retrieval_sources) or 'unspecified')}</td>"
            f"<td><strong>{_fmt_score(candidate.total_score)}</strong>"
            f"<ul class=\"breakdown\">{breakdown}</ul></td>"
            f"<td>{outcome}</td>"
            f"<td>{_e(reason)}</td>"
            "</tr>"
        )
    return "".join(rows)


async def _provenance_chain(
    store: MemoryRepository, record: MemoryRecord
) -> list[MemoryRecord]:
    chain = [record]
    seen = {record.id}
    current = record
    while current.supersedes and current.supersedes not in seen:
        seen.add(current.supersedes)
        previous = await store.get(current.supersedes)
        if previous is None:
            break
        chain.append(previous)
        current = previous
    return chain


def _provenance_item(record: MemoryRecord, *, first: bool) -> str:
    provenance = record.provenance
    details = json.dumps(
        provenance.details, ensure_ascii=False, indent=2, sort_keys=True
    )
    relation = "selected source" if first else "supersedes"
    return (
        f'<li><span class="relation">{relation}</span> '
        f'<code>{_e(record.id)}</code><dl class="provenance">'
        f"<dt>Source</dt><dd>{_e(provenance.source)}</dd>"
        f"<dt>Tier / type</dt><dd>{_e(provenance.tier or '—')} / "
        f"{_e(provenance.record_type or '—')}</dd>"
        f"<dt>Updated</dt><dd>{_e(record.updated_at.isoformat())}</dd>"
        f"<dt>Details</dt><dd><pre>{_e(details)}</pre></dd>"
        "</dl></li>"
    )


async def _selected_sections(
    receipt: RecallReceipt, store: MemoryRepository
) -> str:
    score_by_id = {item.memory_id: item for item in receipt.top_candidates}
    sections: list[str] = []
    for index, selected in enumerate(receipt.selected, start=1):
        record = await store.get(selected.memory_id)
        score = score_by_id.get(selected.memory_id)
        if record is None:
            chain_html = '<p class="warning">Source record is no longer in this store.</p>'
            provenance = chain_html
            kind_scope = "unavailable"
        else:
            chain = await _provenance_chain(store, record)
            provenance = '<ol class="chain">' + "".join(
                _provenance_item(item, first=position == 0)
                for position, item in enumerate(chain)
            ) + "</ol>"
            kind_scope = f"{record.kind.value} · {record.scope.value}"
        truncation = "yes" if selected.truncated else "no"
        score_text = _fmt_score(score.total_score) if score else "not captured"
        sections.append(
            f'<article class="source"><h3>{index}. <code>{_e(selected.memory_id)}</code></h3>'
            f'<p class="source-meta">{_e(kind_scope)} · score {score_text} · '
            f'<strong>{selected.token_cost} tokens</strong> · truncated: {truncation}</p>'
            f"<h4>Provenance chain</h4>{provenance}</article>"
        )
    return "".join(sections) or '<p class="muted">No memories were selected.</p>'


def _token_rows(receipt: RecallReceipt) -> str:
    rows = "".join(
        f"<tr><td>{index}</td><td><code>{_e(item.memory_id)}</code></td>"
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


def _comparison(receipts: Sequence[LabeledReceipt]) -> str:
    if len(receipts) < 2:
        return ""
    expected_query = receipts[0].receipt.query
    if any(item.receipt.query != expected_query for item in receipts[1:]):
        raise ValueError("ablation receipts must have the same query")
    rows = "".join(
        "<tr>"
        f"<td><strong>{_e(item.label)}</strong><br><code>{_e(item.receipt.receipt_id)}</code></td>"
        f"<td>{item.receipt.candidate_count + item.receipt.scope_filtered_count}</td>"
        f"<td>{item.receipt.scope_filtered_count}</td>"
        f"<td>{len(item.receipt.selected)}</td>"
        f"<td>{'on' if item.receipt.supersession_resolution else 'off'}</td>"
        f"<td>{_e(', '.join(item.receipt.superseded_suppressed) or 'none')}</td>"
        f"<td>{item.receipt.total_tokens} / {item.receipt.token_budget}</td>"
        f"<td>{item.receipt.vector_coverage:.1%}</td>"
        f"<td>{item.receipt.latency_ms:.2f} ms</td>"
        f"<td>{_e(', '.join(source.memory_id for source in item.receipt.selected) or 'none')}</td>"
        "</tr>"
        for item in receipts
    )
    return (
        '<section id="ablations"><h2>Ablation comparison</h2>'
        '<p>Same query, different retrieval and packing configurations.</p>'
        '<div class="table-wrap"><table><thead><tr><th>Configuration</th>'
        '<th>Retrieved</th><th>Scope filtered</th><th>Selected</th>'
        '<th>Supersession resolution</th>'
        '<th>Superseded suppressed</th>'
        '<th>Tokens / ceiling</th><th>Vector coverage</th><th>Latency</th>'
        f"<th>Selected IDs</th></tr></thead><tbody>{rows}</tbody></table></div></section>"
    )


async def generate_anatomy_html(
    receipt: RecallReceipt,
    store: MemoryRepository,
    *,
    label: str = "primary",
    comparisons: Sequence[tuple[str, RecallReceipt]] = (),
) -> str:
    """Render a complete single-file HTML report from stable evidence.

    ``comparisons`` contains ``(configuration_label, receipt)`` pairs.  Every
    comparison must describe the same query as the primary receipt.
    """

    labeled = [LabeledReceipt(label, receipt), *(
        LabeledReceipt(name, item) for name, item in comparisons
    )]
    comparison_html = _comparison(labeled)
    selected_html = await _selected_sections(receipt, store)
    retrieved = receipt.candidate_count + receipt.scope_filtered_count
    rejected = max(0, receipt.candidate_count - len(receipt.selected))
    scorer_names = sorted(
        {name for item in receipt.top_candidates for name in item.breakdown}
    )
    css = """
:root { color-scheme: light dark; --bg:#f6f7f9; --panel:#fff; --text:#18202b;
  --muted:#5f6b7a; --line:#d8dee7; --accent:#3157d5; --good:#176b45;
  --good-bg:#dff5e9; --bad:#9b2c2c; --bad-bg:#fde8e8; --code:#eef1f5; }
@media (prefers-color-scheme: dark) { :root { --bg:#0d1117; --panel:#161b22;
  --text:#e6edf3; --muted:#9da7b3; --line:#30363d; --accent:#88a7ff;
  --good:#79d6a7; --good-bg:#123c2c; --bad:#ff9a9a; --bad-bg:#4a2020;
  --code:#21262d; } }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--text);
  font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
main { width:min(1120px,calc(100% - 32px)); margin:40px auto 80px; }
header,section { background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:clamp(20px,4vw,36px); margin:0 0 20px; box-shadow:0 3px 18px #0000000d; }
h1 { font-size:clamp(2rem,5vw,3.5rem); line-height:1.05; margin:.2em 0; }
h2 { margin-top:0; } h3 { overflow-wrap:anywhere } h4 { margin-bottom:.4rem }
.eyebrow { color:var(--accent); font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
.lede,.muted,.source-meta { color:var(--muted) } code,pre { font-family:ui-monospace,SFMono-Regular,
  Consolas,monospace; } code { background:var(--code); padding:.12em .3em; border-radius:4px; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; margin:.3em 0; }
.query { border-left:4px solid var(--accent); padding:.8rem 1rem; background:var(--code); }
.facts,.funnel { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
.fact,.stage { border:1px solid var(--line); border-radius:10px; padding:14px; }
.fact strong,.stage strong { display:block; font-size:1.45rem; } .stage span { color:var(--muted); }
.arrow { align-self:center; justify-self:center; color:var(--accent); font-size:1.4rem; }
.table-wrap { overflow-x:auto; } table { border-collapse:collapse; width:100%; font-size:.92rem; }
th,td { border-bottom:1px solid var(--line); padding:10px; text-align:left; vertical-align:top; }
th { color:var(--muted); } .breakdown { margin:.4rem 0 0; padding-left:1.2rem; white-space:nowrap; }
.pill { display:inline-block; border-radius:999px; padding:.1rem .55rem; font-size:.8rem; font-weight:700; }
.selected { color:var(--good); background:var(--good-bg); } .rejected { color:var(--bad); background:var(--bad-bg); }
.source { border-top:1px solid var(--line); padding:16px 0; } .source:first-of-type { border-top:0; }
.chain { padding-left:1.4rem; } .chain > li { padding:.3rem 0 .7rem; } .relation { color:var(--accent); font-weight:700; }
.provenance { display:grid; grid-template-columns:max-content 1fr; gap:2px 12px; margin:.5rem 0; }
.provenance dt { color:var(--muted); } .provenance dd { margin:0; min-width:0; }
.total { font-weight:700; } .warning { color:var(--bad); } footer { color:var(--muted); text-align:center; }
@media (max-width:650px) { .funnel { grid-template-columns:1fr; } .arrow { transform:rotate(90deg); } }
"""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Anatomy of a {receipt.total_tokens:,}-token handoff</title><style>{css}</style></head>
<body><main><header><p class="eyebrow">AOMS recall receipt teardown · {_e(label)}</p>
<h1>Anatomy of a {receipt.total_tokens:,}-token handoff</h1>
<p class="lede">A static audit of what was retrieved, scored, excluded, and serialized into model context.</p>
<div class="facts"><div class="fact"><span>Receipt</span><strong><code>{_e(receipt.receipt_id)}</code></strong></div>
<div class="fact"><span>Latency</span><strong>{receipt.latency_ms:.2f} ms</strong></div>
<div class="fact"><span>Engine</span><strong>{_e(receipt.engine_version)}</strong></div>
<div class="fact"><span>Receipt contract</span><strong>v{receipt.schema_version}</strong></div></div></header>
<section id="request"><h2>Query and scope</h2><blockquote class="query">{_e(receipt.query)}</blockquote>
<dl class="provenance"><dt>Agent</dt><dd>{_e(receipt.agent_id or 'not recorded')}</dd>
<dt>Workspace</dt><dd>{_e(receipt.workspace_id or 'not recorded')}</dd>
<dt>Scopes</dt><dd>{_enum_list(receipt.scopes)}</dd><dt>Kinds</dt><dd>{_enum_list(receipt.kinds)}</dd>
<dt>Token ceiling</dt><dd>{receipt.token_budget:,}</dd><dt>Scorers</dt><dd>{_e(', '.join(scorer_names) or 'none')}</dd></dl></section>
<section id="funnel"><h2>Candidate funnel</h2><div class="funnel">
<div class="stage"><span>Retrieved</span><strong>{retrieved}</strong><small>before scope policy</small></div><div class="arrow">→</div>
<div class="stage"><span>Scope-visible &amp; scored</span><strong>{receipt.candidate_count}</strong><small>{receipt.scope_filtered_count} filtered</small></div><div class="arrow">→</div>
<div class="stage"><span>Superseded suppressed</span><strong>{len(receipt.superseded_suppressed)}</strong><small>resolution {'on' if receipt.supersession_resolution else 'off'} · {_e(', '.join(receipt.superseded_suppressed) or 'none')}</small></div><div class="arrow">→</div>
<div class="stage"><span>Selected</span><strong>{len(receipt.selected)}</strong><small>serialized</small></div><div class="arrow">/</div>
<div class="stage"><span>Rejected</span><strong>{rejected}</strong><small>not serialized</small></div></div>
<p class="muted">Vector coverage among scored candidates: {receipt.vector_coverage:.1%}. Candidate detail is the receipt's bounded top set plus rejected sample.</p>
<div class="table-wrap"><table><thead><tr><th>#</th><th>Memory</th><th>Kind</th><th>Scope</th><th>Retrieved by</th><th>Score breakdown</th><th>Outcome</th><th>Reason</th></tr></thead>
<tbody>{_candidate_rows(receipt)}</tbody></table></div></section>
<section id="selected"><h2>Selected sources</h2>{selected_html}</section>
<section id="accounting"><h2>Exact serialized token accounting</h2>
<p>Each cost is the marginal tokenizer count added by that serialized source, including separators. The arithmetic must equal the receipt total.</p>
<div class="table-wrap"><table><thead><tr><th>#</th><th>Memory</th><th>Tokens</th><th>Truncated</th></tr></thead><tbody>{_token_rows(receipt)}</tbody></table></div></section>
{comparison_html}<section id="contract"><h2>Versions and timing</h2><dl class="provenance">
<dt>Receipt schema</dt><dd>v{receipt.schema_version}</dd><dt>Recall engine</dt><dd>{_e(receipt.engine_version)}</dd>
<dt>Created (UTC)</dt><dd>{_e(receipt.created_at.isoformat())}</dd><dt>Measured latency</dt><dd>{receipt.latency_ms:.3f} ms</dd></dl></section>
<footer>Generated from immutable AOMS receipt evidence. No scripts, external fonts, or network assets.</footer>
</main></body></html>"""


async def _receipt_by_id(
    repository: MemoryRepository, receipt_id: str
) -> RecallReceipt:
    receipts = await repository.recent_recall_receipts(limit=1_000)
    for receipt in receipts:
        if receipt.receipt_id == receipt_id:
            return receipt
    raise LookupError(f"receipt not found: {receipt_id}")


async def _run_cli(args: argparse.Namespace) -> None:
    repository = SQLiteMemoryRepository(args.db, read_only=True)
    primary = await _receipt_by_id(repository, args.receipt_id)
    compared = [await _receipt_by_id(repository, item) for item in args.compare]
    if args.compare_labels and len(args.compare_labels) != len(compared):
        raise ValueError("--compare-labels must provide one label per --compare receipt")
    labels = args.compare_labels or args.compare
    report = await generate_anatomy_html(
        primary,
        repository,
        label=args.label,
        comparisons=list(zip(labels, compared, strict=True)),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a self-contained AOMS recall anatomy report."
    )
    parser.add_argument("--db", type=Path, required=True, help="AOMS SQLite store")
    parser.add_argument("--receipt-id", required=True, help="primary receipt ID")
    parser.add_argument("--compare", nargs="*", default=[], metavar="RECEIPT_ID")
    parser.add_argument("--label", default="primary", help="primary config label")
    parser.add_argument(
        "--compare-labels", nargs="*", help="labels corresponding to --compare IDs"
    )
    parser.add_argument("--out", type=Path, required=True, help="output HTML path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_run_cli(args))
    except (LookupError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI integration
    raise SystemExit(main())


__all__ = ["LabeledReceipt", "generate_anatomy_html", "main"]

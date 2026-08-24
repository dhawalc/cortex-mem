"""Server-rendered, dependency-free Observatory HTML."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from urllib.parse import quote, urlencode

from aoms.contracts import MemoryKind, MemoryRecord, Scope
from aoms.observatory.evidence import ContextEvidence
from aoms.observatory.partials import (
    candidate_rows,
    enum_list,
    escape_html as e,
    format_score,
    token_rows,
)
from aoms.observatory.repository import ChainNode, MemoryListItem, Page
from aoms.receipts import RecallReceipt

CSS = """
:root{color-scheme:light dark;--bg:#f4f3ef;--panel:#fff;--ink:#17201d;--muted:#65716d;
--line:#d8ddd9;--accent:#075e54;--accent2:#d2eee8;--code:#eef1ee;--old:#fff0d5;
--bad:#9d3030;--badbg:#fde8e7;--good:#12683f;--goodbg:#def3e7;--shadow:#14231d14}
@media(prefers-color-scheme:dark){:root{--bg:#0d1210;--panel:#151c19;--ink:#edf4f0;
--muted:#9cacA5;--line:#34413b;--accent:#70d7c6;--accent2:#173d36;--code:#202924;
--old:#44351f;--bad:#ff9e9a;--badbg:#472322;--good:#84d9ab;--goodbg:#193b2b;--shadow:#0008}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}code,pre{
font-family:ui-monospace,SFMono-Regular,Consolas,monospace}code{background:var(--code);padding:.1em .3em;
border-radius:4px;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
.topbar{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--panel) 94%,transparent);
backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}nav{width:min(1500px,calc(100% - 32px));
margin:auto;display:flex;align-items:center;gap:8px;min-height:58px}.brand{font-weight:850;margin-right:auto;
color:var(--ink);text-decoration:none}.brand span{color:var(--accent)}nav a:not(.brand){padding:7px 10px;
border-radius:8px;text-decoration:none}nav a.active{background:var(--accent2);font-weight:700}
main{width:min(1280px,calc(100% - 32px));margin:28px auto 70px}.wide{width:min(1580px,calc(100% - 24px))}
.hero{margin:8px 0 24px}.eyebrow{text-transform:uppercase;letter-spacing:.1em;color:var(--accent);
font-weight:800;font-size:.75rem}.hero h1{font-size:clamp(2rem,5vw,3.6rem);line-height:1.03;margin:.15em 0}
.lede,.muted,.meta{color:var(--muted)}.panel,.card{background:var(--panel);border:1px solid var(--line);
border-radius:14px;box-shadow:0 4px 18px var(--shadow)}.panel{padding:clamp(18px,3vw,30px);margin-bottom:18px}
.card{padding:18px}.grid{display:grid;gap:14px}.cards{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.filters{display:grid;grid-template-columns:minmax(220px,2fr) repeat(3,minmax(130px,1fr)) auto;gap:10px}
input,select,button,.button{font:inherit;color:inherit;background:var(--panel);border:1px solid var(--line);
border-radius:9px;padding:10px 12px}.button,button{cursor:pointer;background:var(--accent);color:var(--bg);
font-weight:750;text-decoration:none;display:inline-block}.button.secondary{background:var(--panel);color:var(--accent)}
.memory-list{display:grid;gap:10px}.memory-row{display:grid;grid-template-columns:minmax(0,1fr) auto;
gap:12px;padding:16px 18px;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.memory-row h2,.memory-row h3{font-size:1rem;margin:0 0 6px}.preview{margin:6px 0;display:-webkit-box;
-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.badges{display:flex;flex-wrap:wrap;gap:5px}
.badge,.pill{display:inline-block;border-radius:999px;padding:2px 8px;background:var(--code);font-size:.76rem;
font-weight:750}.scope-agent-private{background:#f1ddec;color:#6d245b}.scope-workspace{background:var(--accent2);
color:var(--accent)}.scope-user-global{background:#dfe8ff;color:#274886}.pager{display:flex;justify-content:flex-end;
margin:18px 0}.timeline-day{display:grid;grid-template-columns:140px minmax(0,1fr);gap:18px;margin-bottom:22px}
.timeline-day h2{position:sticky;top:76px;margin:0;font-size:1rem}.timeline-items{display:grid;gap:9px}
.timeline-item{border-left:3px solid var(--accent);padding:10px 14px;background:var(--panel);border-radius:0 10px 10px 0}
.detail-content{font-size:1.03rem}.facts{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:6px 16px}
.facts dt{color:var(--muted)}.facts dd{margin:0;min-width:0}.chain{display:flex;align-items:stretch;gap:8px;
overflow-x:auto;padding:4px 0}.chain-node{min-width:220px;padding:14px;border:1px solid var(--line);border-radius:10px}
.chain-node.current{border:2px solid var(--accent)}.chain-arrow{align-self:center;color:var(--accent);font-size:1.4rem}
.inspector{display:grid;grid-template-columns:minmax(290px,.9fr) minmax(330px,1fr) minmax(430px,1.25fr);
gap:12px;align-items:start}.column{min-width:0}.column>.panel{padding:18px}.column-title{margin:.1rem 0 1rem}
.context{max-height:70vh;overflow:auto;background:var(--code);border:1px solid var(--line);border-radius:10px;
padding:14px;font-size:.78rem}.selected-card{margin-bottom:10px}.selected-card h3{margin:.1em 0}.predecessor{
margin-top:10px;padding:11px;border-radius:9px;background:var(--old);border:1px dashed #bd8a35}.predecessor .badge{
background:var(--badbg);color:var(--bad)}.funnel{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}
.stage{padding:10px;border:1px solid var(--line);border-radius:9px}.stage strong{display:block;font-size:1.45rem}
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:.82rem}th,td{padding:8px;
border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted)}.breakdown{
margin:.35rem 0 0;padding-left:1rem;white-space:nowrap}.pill.selected{background:var(--goodbg);color:var(--good)}
.pill.rejected{background:var(--badbg);color:var(--bad)}.total{font-weight:800}.warning{color:var(--bad)}
.receipt-head{display:flex;gap:12px;align-items:start;justify-content:space-between}.actions{display:flex;gap:8px;
flex-wrap:wrap}.empty{text-align:center;padding:50px 20px}.sr-only{position:absolute;width:1px;height:1px;padding:0;
margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:1050px){.inspector{grid-template-columns:1fr 1fr}.inspector .column:last-child{grid-column:1/-1}}
@media(max-width:760px){nav{overflow-x:auto}.filters{grid-template-columns:1fr}.timeline-day{grid-template-columns:1fr}
.timeline-day h2{position:static}.inspector{grid-template-columns:1fr}.inspector .column:last-child{grid-column:auto}
.funnel{grid-template-columns:1fr 1fr}.memory-row{grid-template-columns:1fr}.facts{grid-template-columns:1fr}.facts dd{margin-bottom:8px}}
"""


def _nav(active: str) -> str:
    links = (("memories", "/memories", "Memories"), ("timeline", "/timeline", "Timeline"), ("receipts", "/receipts", "Receipts"))
    return '<div class="topbar"><nav><a class="brand" href="/memories">RECALL <span>OBSERVATORY</span></a>' + "".join(
        f'<a class="{"active" if active == key else ""}" href="{url}">{label}</a>'
        for key, url, label in links
    ) + "</nav></div>"


def document(title: str, body: str, *, active: str, wide: bool = False) -> str:
    main_class = "wide" if wide else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} · Recall Observatory</title>
<style>{CSS}</style></head><body>{_nav(active)}<main class="{main_class}">{body}</main></body></html>"""


def _content_text(record: MemoryRecord) -> str:
    if isinstance(record.content, str):
        return record.content
    return json.dumps(record.content, ensure_ascii=False, indent=2, sort_keys=True)


def _scope_badge(scope: Scope) -> str:
    return f'<span class="badge scope-{e(scope.value)}">{e(scope.value)}</span>'


def _memory_row(item: MemoryListItem) -> str:
    record = item.record
    rank = f" · FTS rank {item.rank:.4f}" if item.rank is not None else ""
    return f"""<article class="memory-row"><div><h2><a href="/memories/{quote(record.id, safe='')}"><code>{e(record.id)}</code></a></h2>
<div class="badges">{_scope_badge(record.scope)}<span class="badge">{e(record.kind.value)}</span>
<span class="badge">{e(record.provenance.source)}</span></div><p class="preview">{e(_content_text(record))}</p>
<div class="meta">Created {e(record.created_at.isoformat())}{e(rank)}</div></div><time class="meta">{e(record.created_at.date())}</time></article>"""


def _next_link(path: str, parameters: Mapping[str, str], cursor: str | None) -> str:
    if not cursor:
        return ""
    values = {key: value for key, value in parameters.items() if value}
    values["cursor"] = cursor
    return f'<div class="pager"><a class="button secondary" rel="next" href="{path}?{e(urlencode(values))}">Next page →</a></div>'


def memories_page(
    page: Page[MemoryListItem], *, parameters: Mapping[str, str]
) -> str:
    kind_options = '<option value="">All kinds</option>' + "".join(
        f'<option value="{kind.value}"{" selected" if parameters.get("kind") == kind.value else ""}>{kind.value}</option>'
        for kind in MemoryKind
    )
    scope_options = '<option value="">All scopes</option>' + "".join(
        f'<option value="{scope.value}"{" selected" if parameters.get("scope") == scope.value else ""}>{scope.value}</option>'
        for scope in Scope
    )
    rows = "".join(_memory_row(item) for item in page.items)
    if not rows:
        rows = '<div class="panel empty"><h2>No matching memories</h2><p class="muted">Try a broader search or remove a filter.</p></div>'
    body = f"""<header class="hero"><p class="eyebrow">Canonical memory, visible</p><h1>Memories</h1>
<p class="lede">Browse the store without loading the corpus into application memory.</p></header>
<form class="panel filters" action="/memories" method="get"><label class="sr-only" for="q">Search</label>
<input id="q" name="q" type="search" value="{e(parameters.get('q', ''))}" placeholder="FTS search…">
<select name="kind" aria-label="Kind">{kind_options}</select><select name="scope" aria-label="Scope">{scope_options}</select>
<input name="source" value="{e(parameters.get('source', ''))}" placeholder="Exact provenance source">
<button type="submit">Search</button></form><section class="memory-list" aria-label="Memory results">{rows}</section>
{_next_link('/memories', parameters, page.next_cursor)}"""
    return document("Memories", body, active="memories")


def memory_detail_page(record: MemoryRecord, chain: list[ChainNode]) -> str:
    details = json.dumps(record.provenance.details, ensure_ascii=False, indent=2, sort_keys=True)
    chain_html = ""
    for index, node in enumerate(chain):
        if index:
            chain_html += '<span class="chain-arrow" aria-hidden="true">→</span>'
        current = " current" if node.relation == "selected" else ""
        chain_html += f"""<article class="chain-node{current}"><span class="badge">{e(node.relation)}</span>
<h3><a href="/memories/{quote(node.record.id, safe='')}"><code>{e(node.record.id)}</code></a></h3>
<p class="preview">{e(_content_text(node.record))}</p><small class="meta">{e(node.record.updated_at.isoformat())}</small></article>"""
    body = f"""<header class="hero"><p class="eyebrow">Memory detail</p><h1><code>{e(record.id)}</code></h1>
<div class="badges">{_scope_badge(record.scope)}<span class="badge">{e(record.kind.value)}</span></div></header>
<section class="panel"><h2>Full content</h2><pre class="detail-content">{e(_content_text(record))}</pre></section>
<section class="panel"><h2>Provenance</h2><dl class="facts"><dt>Source</dt><dd>{e(record.provenance.source)}</dd>
<dt>Tier</dt><dd>{e(record.provenance.tier or '—')}</dd><dt>Record type</dt><dd>{e(record.provenance.record_type or '—')}</dd>
<dt>Created</dt><dd>{e(record.created_at.isoformat())}</dd><dt>Updated</dt><dd>{e(record.updated_at.isoformat())}</dd>
<dt>Created by agent</dt><dd>{e(record.created_by_agent_id or '—')}</dd><dt>Agent binding</dt><dd>{e(record.scope_agent_id or '—')}</dd>
<dt>Workspace binding</dt><dd>{e(record.scope_workspace_id or '—')}</dd><dt>Details</dt><dd><pre>{e(details)}</pre></dd></dl></section>
<section class="panel"><h2>Supersession chain</h2><p class="muted">Predecessor links are followed in both directions from this record.</p>
<div class="chain">{chain_html}</div></section>"""
    return document(record.id, body, active="memories")


def timeline_page(page: Page[MemoryListItem], *, cursor: str | None) -> str:
    groups: dict[str, list[MemoryListItem]] = defaultdict(list)
    for item in page.items:
        groups[item.record.created_at.date().isoformat()].append(item)
    sections = ""
    for day, items in groups.items():
        sections += f'<section class="timeline-day"><h2><time>{e(day)}</time></h2><div class="timeline-items">'
        for item in items:
            record = item.record
            sections += f"""<article class="timeline-item"><div class="badges">{_scope_badge(record.scope)}
<span class="badge">{e(record.kind.value)}</span></div><a href="/memories/{quote(record.id, safe='')}"><code>{e(record.id)}</code></a>
<p class="preview">{e(_content_text(record))}</p><small class="meta">{e(record.created_at.time().isoformat())}</small></article>"""
        sections += "</div></section>"
    if not sections:
        sections = '<section class="panel empty"><h2>No memories yet</h2></section>'
    body = f"""<header class="hero"><p class="eyebrow">A history you can read</p><h1>Timeline</h1>
<p class="lede">Creation events grouped by UTC day.</p></header>{sections}{_next_link('/timeline', {}, page.next_cursor)}"""
    return document("Timeline", body, active="timeline")


def receipts_page(page: Page[RecallReceipt]) -> str:
    cards = ""
    for receipt in page.items:
        cards += f"""<article class="card"><p class="eyebrow">{e(receipt.created_at.isoformat())}</p>
<h2><a href="/receipts/{quote(receipt.receipt_id, safe='')}">{e(receipt.query)}</a></h2>
<p class="meta"><code>{e(receipt.receipt_id)}</code></p><div class="badges"><span class="badge">{len(receipt.selected)} packed</span>
<span class="badge">{receipt.total_tokens} / {receipt.token_budget} tokens</span><span class="badge">{receipt.vector_coverage:.1%} vectors</span></div></article>"""
    if not cards:
        cards = '<div class="panel empty"><h2>No recall receipts</h2><p class="muted">A receipt appears after the first recall.</p></div>'
    body = f"""<header class="hero"><p class="eyebrow">Evidence, not vibes</p><h1>Recall receipts</h1>
<p class="lede">Every row is an immutable explanation of a recall decision.</p></header><section class="grid cards">{cards}</section>
{_next_link('/receipts', {}, page.next_cursor)}"""
    return document("Receipts", body, active="receipts")


def _selected_cards(
    receipt: RecallReceipt, repository_records: Mapping[str, MemoryRecord], chains: Mapping[str, list[MemoryRecord]]
) -> str:
    scores = {candidate.memory_id: candidate for candidate in receipt.top_candidates}
    cards = ""
    for index, selected in enumerate(receipt.selected, start=1):
        record = repository_records.get(selected.memory_id)
        score = scores.get(selected.memory_id)
        if record is None:
            cards += f'<article class="card selected-card warning">Missing selected memory <code>{e(selected.memory_id)}</code></article>'
            continue
        predecessors = chains.get(record.id, [record])[1:]
        predecessor_html = "".join(
            f"""<div class="predecessor"><span class="badge">superseded predecessor</span>
<h4><a href="/memories/{quote(old.id, safe='')}"><code>{e(old.id)}</code></a></h4>
<p>{e(_content_text(old))}</p><small class="meta">{e(old.provenance.source)}</small></div>"""
            for old in predecessors
        )
        score_text = format_score(score.total_score) if score else "not captured"
        cards += f"""<article class="card selected-card"><p class="eyebrow">Selected memory {index}</p>
<h3><a href="/memories/{quote(record.id, safe='')}"><code>{e(record.id)}</code></a></h3>
<div class="badges">{_scope_badge(record.scope)}<span class="badge">{e(record.kind.value)}</span>
<span class="badge">score {score_text}</span><span class="badge">{selected.token_cost} tokens</span></div>
<p>{e(_content_text(record))}</p><p class="meta">Provenance: {e(record.provenance.source)}</p>{predecessor_html}</article>"""
    return cards or '<div class="panel empty"><p>No memories were packed.</p></div>'


def receipt_inspector_page(
    receipt: RecallReceipt,
    *,
    records: Mapping[str, MemoryRecord],
    chains: Mapping[str, list[MemoryRecord]],
    context: ContextEvidence,
) -> str:
    retrieved = receipt.candidate_count + receipt.scope_filtered_count
    after_scope = receipt.candidate_count
    after_supersession = max(0, after_scope - len(receipt.superseded_suppressed))
    context_state = "reconciled" if context.reconciled else "mismatch"
    context_warning = f'<p class="warning">{e(context.warning)}</p>' if context.warning else ""
    selected_html = _selected_cards(receipt, records, chains)
    body = f"""<header class="hero receipt-head"><div><p class="eyebrow">The receipt inspector</p>
<h1>Anatomy of a {receipt.total_tokens:,}-token handoff</h1><p class="lede"><code>{e(receipt.receipt_id)}</code></p></div>
<div class="actions"><a class="button secondary" download="aoms-receipt-{e(receipt.receipt_id)}.html" href="/receipts/{quote(receipt.receipt_id, safe='')}/export">Export static HTML</a></div></header>
<div class="inspector" data-receipt-id="{e(receipt.receipt_id)}">
<section class="column" id="receipt-request"><div class="panel"><p class="eyebrow">Request &amp; final artifact</p><h2 class="column-title">Task</h2>
<blockquote>{e(receipt.query)}</blockquote><dl class="facts"><dt>Agent</dt><dd>{e(receipt.agent_id or 'not recorded')}</dd>
<dt>Workspace</dt><dd>{e(receipt.workspace_id or 'not recorded')}</dd><dt>Scopes</dt><dd>{enum_list(receipt.scopes)}</dd>
<dt>Kinds</dt><dd>{enum_list(receipt.kinds)}</dd><dt>Budget</dt><dd>{receipt.token_budget:,} tokens</dd></dl></div>
<div class="panel"><h2>Final provenance-fenced context</h2><p class="meta">{e(context.source)} · {context.token_count} tokens · {context_state}</p>
{context_warning}<pre class="context">{e(context.context) if context.context else 'No context was packed.'}</pre></div></section>
<section class="column" id="selected-memory-cards"><div class="panel"><p class="eyebrow">Packed evidence</p><h2 class="column-title">Selected memory cards</h2>
<p class="muted">Superseded predecessors remain visibly attached for audit.</p>{selected_html}</div></section>
<section class="column" id="receipt-evidence"><div class="panel"><p class="eyebrow">Decision evidence</p><h2 class="column-title">Candidate funnel</h2>
<div class="funnel"><div class="stage"><span>Retrieved</span><strong>{retrieved}</strong><small>before policy</small></div>
<div class="stage"><span>Scope-filtered</span><strong>{after_scope}</strong><small>{receipt.scope_filtered_count} removed</small></div>
<div class="stage"><span>Superseded</span><strong>{after_supersession}</strong><small>{len(receipt.superseded_suppressed)} removed</small></div>
<div class="stage"><span>Packed</span><strong>{len(receipt.selected)}</strong><small>serialized</small></div></div>
<dl class="facts"><dt>Vector coverage</dt><dd>{receipt.vector_coverage:.1%}</dd><dt>Receipt ID</dt><dd><code>{e(receipt.receipt_id)}</code></dd>
<dt>Engine</dt><dd>{e(receipt.engine_version)}</dd><dt>Latency</dt><dd>{receipt.latency_ms:.3f} ms</dd></dl></div>
<div class="panel"><h2>Per-scorer components</h2><div class="table-wrap"><table><thead><tr><th>#</th><th>Memory</th><th>Kind</th><th>Scope</th>
<th>Retrieved by</th><th>Score: raw × weight = contribution</th><th>Outcome</th><th>Reason</th></tr></thead><tbody>{candidate_rows(receipt)}</tbody></table></div></div>
<div class="panel" id="token-accounting"><h2>Exact token arithmetic</h2><div class="table-wrap"><table><thead><tr><th>#</th><th>Memory</th><th>Tokens</th><th>Truncated</th></tr></thead>
<tbody>{token_rows(receipt)}</tbody></table></div></div></section></div>"""
    return document(
        f"Receipt {receipt.receipt_id}", body, active="receipts", wide=True
    )


def error_page(status: int, message: str) -> str:
    body = f'<section class="panel empty"><p class="eyebrow">{status}</p><h1>{e(message)}</h1><p><a href="/memories">Return to memories</a></p></section>'
    return document(str(status), body, active="")


__all__ = [
    "document",
    "error_page",
    "memories_page",
    "memory_detail_page",
    "receipt_inspector_page",
    "receipts_page",
    "timeline_page",
]

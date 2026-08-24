#!/usr/bin/env python3
# ruff: noqa: E402 - the standalone script bootstraps the repository import path
"""Regenerate AOMS's synthetic launch screenshots from real product output.

The script creates only disposable stores under /tmp, performs recall through
``AOMSApplication``, serves the receipt through the loopback Observatory, and
captures the resulting page with an installed browser.  It never opens the
canonical AOMS data directory and never runs an embedding model.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from PIL import Image

ASSET_DIR = Path(__file__).resolve().parent
REPO_ROOT = ASSET_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    MemoryRecord,
    Provenance,
    RecallRequest,
    Scope,
    ScopeContext,
)
from aoms.embeddings import NullProvider
from aoms.observatory.server import (
    LOOPBACK_HOST,
    ObservatoryApplication,
    ObservatoryHTTPServer,
)
from aoms.recall import RecallEngine
from aoms.repositories import SQLiteMemoryRepository


WORKSPACE_ID = "atlas-console"
RECEIPT_ID = "7d9d6b43-71dd-4c17-90b8-c15a6d46c4f2"
FIXED_NOW = datetime(2026, 4, 7, 16, 30, tzinfo=timezone.utc)
HERO_BUDGET = 1_000
MAX_ASSET_BYTES = 1_500_000

HERO_LIGHT = "recall-observatory-receipt-light.png"
HERO_DARK = "recall-observatory-receipt-dark.png"
TERMINAL_HTML = "aoms-60-second-proof.html"
TERMINAL_PNG = "aoms-60-second-proof.png"


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _memory(
    record_id: str,
    kind: MemoryKind,
    content: str,
    *,
    source: str,
    created: str,
    updated: str | None = None,
    tags: Iterable[str] = (),
    scope: Scope = Scope.WORKSPACE,
    agent_id: str | None = None,
    workspace_id: str | None = WORKSPACE_ID,
    supersedes: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        kind=kind,
        content=content,
        tags=list(tags),
        scope=scope,
        scope_agent_id=agent_id if scope is Scope.AGENT_PRIVATE else None,
        scope_workspace_id=workspace_id if scope is Scope.WORKSPACE else None,
        created_by_agent_id=agent_id or "planner-agent",
        provenance=Provenance(
            source=source,
            details={"fixture": "synthetic-launch-demo", "publishable": True},
        ),
        created_at=_utc(created),
        updated_at=_utc(updated or created),
        supersedes=supersedes,
    )


def synthetic_corpus() -> list[MemoryRecord]:
    """A publishable project handoff with scope and truth-history evidence."""

    return [
        _memory(
            "atlas-release-gate-2026-03-04",
            MemoryKind.DECISION,
            "Decision in early March: Atlas launch used one amber canary wave in "
            "us-west, then released globally after a 15-minute observation window.",
            source="project/decisions/release-gates.md",
            created="2026-03-04T09:00:00Z",
            tags=("atlas", "launch", "canary"),
        ),
        _memory(
            "atlas-release-gate-current",
            MemoryKind.DECISION,
            "Current decision, approved March 28: Atlas launch requires two amber "
            "canary waves (5% then 25%) in us-east. Each wave must hold for 30 "
            "minutes with checkout errors below 0.5% and p95 latency below 420 ms. "
            "Release engineering records both dashboards in the change ticket "
            "before global rollout. This replaces the single-wave March plan.",
            source="project/decisions/release-gates.md",
            created="2026-03-28T14:20:00Z",
            tags=("atlas", "launch", "canary", "current"),
            supersedes="atlas-release-gate-2026-03-04",
        ),
        _memory(
            "atlas-rollback-procedure",
            MemoryKind.PROCEDURE,
            "Atlas rollback owner is the release commander. Pause the rollout, "
            "restore the prior deployment manifest, confirm queue drain, and post "
            "the rollback timestamp plus dashboard links in the change ticket. "
            "Do not retry a failed canary until the incident lead clears it.",
            source="runbooks/atlas-release.md",
            created="2026-03-30T11:15:00Z",
            tags=("atlas", "rollback", "runbook"),
        ),
        _memory(
            "atlas-observability-contract",
            MemoryKind.FACT,
            "Atlas launch observability uses checkout-success, request-latency, and "
            "dead-letter-queue dashboards. Link each 30-minute canary window in the "
            "release ticket.",
            source="project/handoffs/launch-readiness.md",
            created="2026-04-01T08:45:00Z",
            tags=("atlas", "observability", "launch"),
        ),
        _memory(
            "atlas-data-residency",
            MemoryKind.FACT,
            "Atlas export payloads stay in their residency region. Metadata "
            "may move globally; payload bytes never do. Audit events record the region.",
            source="architecture/data-boundaries.md",
            created="2026-03-21T12:10:00Z",
            tags=("atlas", "residency", "constraint"),
        ),
        _memory(
            "atlas-canary-timeout-failure",
            MemoryKind.FAILURE,
            "A March rehearsal timed out because the canary gate watched aggregate "
            "HTTP errors instead of checkout errors. The launch checklist now pins "
            "the checkout-success query and verifies its region label before wave one.",
            source="incidents/2026-03-canary-rehearsal.md",
            created="2026-03-18T19:05:00Z",
            tags=("atlas", "canary", "failure"),
        ),
        _memory(
            "atlas-release-roles",
            MemoryKind.FACT,
            "Atlas launch handoff: release engineering runs rollout commands; the "
            "incident lead owns stop/go decisions; support drafts customer status.",
            source="project/handoffs/launch-readiness.md",
            created="2026-03-31T10:00:00Z",
            tags=("atlas", "launch", "roles"),
        ),
        _memory(
            "atlas-post-launch-review",
            MemoryKind.PROCEDURE,
            "After Atlas launch, preserve the canary dashboard links, rollout event "
            "IDs, rollback decision if any, and customer-impact summary. Review the "
            "packet on the next business day and record durable corrections.",
            source="runbooks/atlas-release.md",
            created="2026-03-27T17:30:00Z",
            tags=("atlas", "launch", "review"),
        ),
        _memory(
            "shared-change-ticket-policy",
            MemoryKind.PATTERN,
            "Every production launch change ticket names the commander, links exact "
            "gate queries, states rollback authority, and records each decision time "
            "in UTC. Chat approval without a ticket entry is not durable evidence.",
            source="engineering/release-patterns.md",
            created="2026-02-20T15:00:00Z",
            tags=("launch", "evidence"),
            scope=Scope.USER_GLOBAL,
            workspace_id=None,
        ),
        _memory(
            "atlas-api-freeze",
            MemoryKind.DECISION,
            "Atlas public API fields are frozen for launch week. Additive telemetry "
            "labels are allowed; request or response schema changes wait until the "
            "post-launch review.",
            source="project/decisions/api-contract.md",
            created="2026-04-02T13:10:00Z",
            tags=("atlas", "launch", "api"),
        ),
        _memory(
            "private-atlas-canary-do-not-disclose",
            MemoryKind.FACT,
            "PRIVATE SCOPE CANARY: Atlas launch, rollback, observability, and residency. "
            "This sentence exists only to prove an FTS match cannot cross agent scope.",
            source="private/scope-canary.md",
            created="2026-04-03T09:00:00Z",
            tags=("atlas", "launch", "canary"),
            scope=Scope.AGENT_PRIVATE,
            agent_id="private-reviewer",
            workspace_id=None,
        ),
        _memory(
            "foreign-atlas-launch-notes",
            MemoryKind.DECISION,
            "Atlas launch notes for a different workspace mention a green canary and "
            "a manual rollback. They must not influence the atlas-console handoff.",
            source="other-workspace/release.md",
            created="2026-04-04T10:00:00Z",
            tags=("atlas", "launch", "canary"),
            workspace_id="atlas-mobile",
        ),
    ]


async def build_hero_store(db_path: Path) -> tuple[str, dict[str, Any]]:
    repository = SQLiteMemoryRepository(db_path)
    await repository.store_many(synthetic_corpus())
    context = ScopeContext(agent_id="handoff-reviewer", workspace_id=WORKSPACE_ID)
    ticks = iter((100.0, 100.0184))
    engine = RecallEngine(
        repository,
        scope_context=context,
        embedding_provider=NullProvider(),
        clock=lambda: FIXED_NOW,
        timer=lambda: next(ticks),
    )
    application = AOMSApplication(
        repository,
        scope_context=context,
        embedding_provider=NullProvider(),
        background_embeddings=False,
        recall_engine=engine,
    )

    # UUIDs are normally random. Fix only this disposable proof receipt so a
    # regeneration is byte-stable while exercising the same engine path.
    import aoms.recall as recall_module

    original_uuid4 = recall_module.uuid4
    recall_module.uuid4 = lambda: UUID(RECEIPT_ID)
    try:
        result = await application.recall(
            RecallRequest(
                task=(
                    "Prepare the current Atlas launch handoff: release gate, canary, "
                    "rollback, observability, and data residency."
                ),
                token_budget=HERO_BUDGET,
            )
        )
    finally:
        recall_module.uuid4 = original_uuid4

    receipt = (await application.recent_recall_receipts(limit=1))[0]
    assert receipt.receipt_id == RECEIPT_ID
    assert receipt.context == result.context
    assert sum(item.token_cost for item in receipt.selected) == receipt.total_tokens
    assert receipt.total_tokens == 842
    assert "atlas-release-gate-2026-03-04" in receipt.superseded_suppressed
    assert receipt.scope_filtered_count >= 2
    assert "PRIVATE SCOPE CANARY" not in receipt.context
    assert all(
        item.memory_id != "private-atlas-canary-do-not-disclose"
        for item in receipt.top_candidates
    )
    return receipt.receipt_id, receipt.model_dump(mode="json")


def _browser_command() -> tuple[str, str]:
    playwright = shutil.which("playwright")
    if playwright:
        return "playwright", playwright
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        browser = shutil.which(name)
        if browser:
            return "chrome", browser
    raise RuntimeError("no Playwright CLI or headless Chrome/Chromium was found")


def _capture(
    url: str,
    destination: Path,
    *,
    color_scheme: str,
    viewport: tuple[int, int],
) -> str:
    mode, executable = _browser_command()
    if mode == "playwright":
        command = [
            executable,
            "screenshot",
            "--browser",
            "chromium",
            "--channel",
            "chrome",
            "--device",
            "Desktop Chrome HiDPI",
            "--viewport-size",
            f"{viewport[0]}, {viewport[1]}",
            "--color-scheme",
            color_scheme,
            "--full-page",
            "--wait-for-timeout",
            "250",
            url,
            str(destination),
        ]
        subprocess.run(
            command, cwd=REPO_ROOT, check=True, capture_output=True, text=True
        )
        return "Playwright CLI with system Google Chrome"

    # Chrome's CLI lacks a full-page flag. A tall deterministic viewport plus
    # the post-capture crop is the fallback for this fixed server-rendered page.
    command = [
        executable,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--force-device-scale-factor=2",
        f"--window-size={viewport[0]},{max(viewport[1], 5200)}",
        f"--screenshot={destination}",
    ]
    if color_scheme == "dark":
        command.append("--force-dark-mode")
    command.append(url)
    subprocess.run(command, cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    return f"headless {Path(executable).name}"


def _crop_and_optimize(path: Path, *, bottom_padding_css: int = 24) -> None:
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    if image.width < 2_800:
        raise RuntimeError(
            f"{path.name} is only {image.width}px wide; expected a 2x HiDPI capture"
        )
    crop = min(bottom_padding_css * 2, max(0, image.height - 200))
    if crop:
        image = image.crop((0, 0, image.width, image.height - crop))
    image.save(path, format="PNG", optimize=True, compress_level=9)
    if path.stat().st_size > MAX_ASSET_BYTES:
        # Flat UI colors survive an adaptive palette well, including font edges.
        image.quantize(colors=256).save(
            path, format="PNG", optimize=True, compress_level=9
        )
    if path.stat().st_size > MAX_ASSET_BYTES:
        raise RuntimeError(f"{path.name} exceeds the 1.5 MB launch-asset limit")


def _wait_for_url(url: str) -> None:
    for _ in range(50):
        try:
            with urllib.request.urlopen(url, timeout=0.2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        threading.Event().wait(0.05)
    raise RuntimeError(f"Observatory did not become ready: {url}")


def capture_hero(db_path: Path, receipt_id: str) -> str:
    application = ObservatoryApplication(db_path)
    response = application.handle("GET", f"/receipts/{receipt_id}")
    page = response.body.decode("utf-8")
    required = (
        "Final provenance-fenced context",
        "superseded predecessor",
        "Candidate funnel",
        "Exact token arithmetic",
        "Scope-filtered",
        "atlas-release-gate-2026-03-04",
    )
    assert response.status == 200
    assert all(marker in page for marker in required)
    assert "PRIVATE SCOPE CANARY" not in page
    assert "private-atlas-canary-do-not-disclose" not in page

    server = ObservatoryHTTPServer((LOOPBACK_HOST, 0), application)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://{LOOPBACK_HOST}:{server.server_port}/receipts/{receipt_id}"
        _wait_for_url(url)
        tooling = _capture(
            url,
            ASSET_DIR / HERO_LIGHT,
            color_scheme="light",
            viewport=(1580, 1000),
        )
        _capture(
            url,
            ASSET_DIR / HERO_DARK,
            color_scheme="dark",
            viewport=(1580, 1000),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    _crop_and_optimize(ASSET_DIR / HERO_LIGHT)
    _crop_and_optimize(ASSET_DIR / HERO_DARK)
    return tooling


def _sitecustomize(directory: Path) -> None:
    content = f'''"""Deterministic clock/UUID for the disposable launch transcript."""
from datetime import datetime as _datetime
from pathlib import Path
from uuid import UUID

class _FixedDateTime(_datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 4, 7, 16, 30, 0)
        return value.replace(tzinfo=tz) if tz is not None else value

import aoms.application as _application
import aoms.recall as _recall
_expected_root = Path({str(REPO_ROOT)!r})
if not Path(_application.__file__).resolve().is_relative_to(_expected_root):
    raise RuntimeError("demo CLI imported AOMS from outside the asset worktree")
_application.datetime = _FixedDateTime
_recall.datetime = _FixedDateTime
_recall.uuid4 = lambda: UUID("{RECEIPT_ID}")
'''
    (directory / "sitecustomize.py").write_text(content, encoding="utf-8")


def _run_cli(
    executable: Path,
    args: list[str],
    *,
    environment: dict[str, str],
) -> str:
    completed = subprocess.run(
        [str(executable), *args],
        cwd=REPO_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _terminal_document(values: dict[str, Any]) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    receipt_summary = json.dumps(
        {
            "sources": [
                {
                    "memory_id": source["memory_id"],
                    "scope": source["scope"],
                    "token_count": source["token_count"],
                }
                for source in values["recall"]["sources"]
            ],
            "token_count": values["recall"]["token_count"],
            "diagnostics": {
                key: values["recall"]["diagnostics"][key]
                for key in ("receipt_id", "selected_count", "scope_filtered_count")
            },
        },
        indent=2,
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AOMS 60-second cold-recall proof</title><style>
:root{{--bg:#0b0f14;--panel:#111820;--line:#2a3541;--ink:#e8eef5;--muted:#91a0af;--green:#62d49f;--cyan:#73c7ec;--amber:#e9c46a}}
*{{box-sizing:border-box}}body{{margin:0;padding:44px;background:var(--bg);color:var(--ink);font:17px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}}
.frame{{max-width:1380px;margin:auto;border:1px solid var(--line);border-radius:18px;overflow:hidden;background:var(--panel);box-shadow:0 24px 70px #0008}}
.bar{{height:52px;display:flex;align-items:center;gap:9px;padding:0 18px;border-bottom:1px solid var(--line);background:#151d26}}.dot{{width:12px;height:12px;border-radius:50%;background:#ff6b67}}.dot:nth-child(2){{background:#f0c65c}}.dot:nth-child(3){{background:#59c87a}}.title{{margin-left:10px;color:var(--muted);font:600 14px ui-sans-serif,system-ui}}
.body{{padding:28px 32px 34px}}.step{{display:flex;gap:10px;align-items:center;margin:18px 0 8px;color:var(--cyan);font:700 13px ui-sans-serif,system-ui;text-transform:uppercase;letter-spacing:.08em}}.badge{{padding:4px 9px;border:1px solid #315064;border-radius:999px;background:#122632}}pre{{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}}.prompt{{color:var(--green)}}.output{{color:#bdc8d3}}.json{{color:#d6dee7;border-left:2px solid #355167;padding-left:18px;margin-top:8px}}.receipt{{color:var(--amber)}}.note{{margin-top:24px;padding:14px 16px;border:1px solid #29443a;border-radius:10px;background:#10241d;color:#bfe8d4;font:600 15px/1.45 ui-sans-serif,system-ui}}.muted{{color:var(--muted)}}
</style></head><body><main class="frame"><div class="bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span><span class="title">AOMS · disposable store · synthetic data</span></div><div class="body">
<div class="step"><span class="badge">process 1</span> initialize and remember</div>
<pre><span class="prompt">$</span> cortex-mem init --data-dir /tmp/aoms-launch-assets/cold-recall
<span class="output">{esc(values["init"])}</span>

<span class="prompt">$</span> cortex-mem remember \\
    --content "Decision: release only after the amber canary passes." \\
    --kind decision --tags release,canary \\
    --idempotency-key release-amber-gate
<span class="output">{esc(values["remember"])}</span></pre>
<div class="step"><span class="badge">process 2 · fresh PID</span> cold recall, same workspace</div>
<pre><span class="prompt">$</span> cortex-mem recall \\
    --task "Recall the release gate for this workspace." \\
    --budget 500 --format json
<span class="muted"># selected receipt fields; packed context is omitted from this annotated view</span>
<span class="json">{esc(receipt_summary)}</span></pre>
<div class="note">✓ New process. One workspace-scoped source recalled. <span class="receipt">Receipt {esc(RECEIPT_ID)}</span> records the serialization path.</div>
</div></main></body></html>"""


def build_terminal_asset(work_root: Path) -> None:
    data_dir = work_root / "cold-recall"
    hook_dir = work_root / "deterministic-python"
    hook_dir.mkdir(parents=True)
    _sitecustomize(hook_dir)

    cli = Path(sys.executable).with_name("cortex-mem")
    if not cli.is_file():
        raise RuntimeError(f"console entry point not found beside interpreter: {cli}")
    environment = dict(os.environ)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment.update(
        {
            "AOMS_AGENT_ID": "writer-agent",
            "AOMS_WORKSPACE": WORKSPACE_ID,
            "AOMS_EMBEDDING_PROVIDER": "none",
            "PYTHONPATH": os.pathsep.join((str(hook_dir), str(REPO_ROOT)))
            + (os.pathsep + existing_pythonpath if existing_pythonpath else ""),
        }
    )
    init_output = _run_cli(
        cli, ["init", "--data-dir", str(data_dir)], environment=environment
    )
    remember_output = _run_cli(
        cli,
        [
            "remember",
            "--data-dir",
            str(data_dir),
            "--content",
            "Decision: release only after the amber canary passes.",
            "--kind",
            "decision",
            "--tags",
            "release,canary",
            "--idempotency-key",
            "release-amber-gate",
        ],
        environment=environment,
    )

    # A second OS process gets a different bound agent but the same workspace.
    environment["AOMS_AGENT_ID"] = "reader-agent"
    recall_output = _run_cli(
        cli,
        [
            "recall",
            "--data-dir",
            str(data_dir),
            "--task",
            "Recall the release gate for this workspace.",
            "--budget",
            "500",
            "--format",
            "json",
        ],
        environment=environment,
    )
    recall = json.loads(recall_output)
    assert len(recall["sources"]) == 1
    assert recall["sources"][0]["scope"] == "workspace"
    assert "amber canary passes" in recall["context"]
    assert recall["diagnostics"]["receipt_id"] == RECEIPT_ID

    normalized_init = init_output.replace(
        str(data_dir), "/tmp/aoms-launch-assets/cold-recall"
    )
    document = _terminal_document(
        {
            "init": normalized_init,
            "remember": remember_output,
            "recall": recall,
        }
    )
    html_path = ASSET_DIR / TERMINAL_HTML
    html_path.write_text(document, encoding="utf-8")
    _capture(
        html_path.as_uri(),
        ASSET_DIR / TERMINAL_PNG,
        color_scheme="dark",
        viewport=(1440, 900),
    )
    _crop_and_optimize(ASSET_DIR / TERMINAL_PNG, bottom_padding_css=20)


def _asset_report(tooling: str, receipt: dict[str, Any]) -> None:
    print(f"Capture tooling: {tooling}")
    print(
        "Hero receipt: "
        f"{receipt['receipt_id']} · {receipt['candidate_count']} candidates · "
        f"{receipt['scope_filtered_count']} scope-filtered · "
        f"{len(receipt['superseded_suppressed'])} superseded · "
        f"{len(receipt['selected'])} packed · "
        f"{receipt['total_tokens']}/{receipt['token_budget']} tokens"
    )
    for name in (HERO_LIGHT, HERO_DARK, TERMINAL_HTML, TERMINAL_PNG):
        path = ASSET_DIR / name
        print(f"{path.relative_to(REPO_ROOT)}: {path.stat().st_size:,} bytes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-work-dir",
        action="store_true",
        help="retain the disposable /tmp stores for local inspection",
    )
    args = parser.parse_args()

    work_root = Path(tempfile.mkdtemp(prefix="aoms-launch-assets-", dir="/tmp"))
    try:
        hero_db = work_root / "hero" / "aoms.sqlite3"
        hero_db.parent.mkdir(parents=True)
        receipt_id, receipt = asyncio.run(build_hero_store(hero_db))
        tooling = capture_hero(hero_db, receipt_id)
        build_terminal_asset(work_root)
        _asset_report(tooling, receipt)
    finally:
        if args.keep_work_dir:
            print(f"Kept disposable work directory: {work_root}")
        else:
            shutil.rmtree(work_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

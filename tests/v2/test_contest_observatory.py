"""The contradiction inbox in the Observatory: read-only, and inert on render.

You decide in the browser and act in the terminal. The consequence tested
here is that an XSS or CSRF against the Observatory cannot change memory,
because there is no route that writes and the store is opened read-only.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    Provenance,
    RememberRequest,
    Scope,
    ScopeContext,
)
from aoms.embeddings import NullProvider
from aoms.observatory.server import ObservatoryApplication
from aoms.repositories import SQLiteMemoryRepository

XSS = (
    '<script>alert("pwned")</script>"><img src=x onerror=alert(1)> '
    "&& javascript:void(0) </pre><div style='position:fixed'>"
)


@pytest.fixture
def observatory(tmp_path):
    db_path = tmp_path / "aoms.sqlite3"

    async def seed():
        application = AOMSApplication(
            SQLiteMemoryRepository(db_path),
            scope_context=ScopeContext(agent_id="agent-a", workspace_id="/w"),
            embedding_provider=NullProvider(),
            background_embeddings=False,
        )
        await application.remember(
            RememberRequest(
                id="incumbent",
                kind=MemoryKind.FACT,
                content="the price is 100 dollars",
                scope=Scope.WORKSPACE,
                claim_key="price",
            )
        )
        challenger = await application.remember(
            RememberRequest(
                id="challenger",
                kind=MemoryKind.FACT,
                content=XSS,
                scope=Scope.WORKSPACE,
                claim_key="price",
                provenance=Provenance(source=XSS),
            )
        )
        return challenger.contest_id

    contest_id = asyncio.run(seed())
    return ObservatoryApplication(db_path), contest_id, db_path


# --- read-only posture ----------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD "])
def test_no_method_but_get_reaches_the_contest_routes(observatory, method):
    application, contest_id, _ = observatory
    for target in ["/contests", f"/contests/{contest_id}"]:
        response = application.handle(method.strip() or "POST", target)
        if method.strip() == "HEAD":
            assert response.status == 200
            continue
        assert response.status == 405
        assert b"method not allowed" in response.body


def test_the_contest_routes_open_the_store_read_only(observatory):
    application, _, _ = observatory
    assert application.repository.read_only is True
    with application.repository._connect() as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("UPDATE memories SET contested = 0")


def test_serving_the_pages_changes_nothing(observatory):
    application, contest_id, db_path = observatory

    def snapshot():
        with sqlite3.connect(db_path) as connection:
            return (
                connection.execute(
                    "SELECT group_concat(record_json) FROM memories ORDER BY id"
                ).fetchone()[0],
                connection.execute(
                    "SELECT group_concat(state || occurrence_count) "
                    "FROM contest_entries"
                ).fetchone()[0],
            )

    before = snapshot()
    for target in ["/contests", f"/contests/{contest_id}", "/truth"]:
        assert application.handle("GET", target).status == 200
    assert snapshot() == before


# --- rendering is inert ---------------------------------------------------


def test_challenger_content_is_escaped_in_the_side_by_side_view(observatory):
    application, contest_id, _ = observatory
    body = application.handle("GET", f"/contests/{contest_id}").body.decode()

    assert "<script>alert" not in body
    assert "&lt;script&gt;alert" in body
    assert "<img src=x" not in body
    assert "onerror=alert(1)" not in body or "&lt;img" in body
    assert "</pre><div style=" not in body
    # The record is still fully visible to the operator, just as text.
    assert "&lt;/pre&gt;" in body


def test_the_provenance_source_is_escaped_too(observatory):
    application, contest_id, _ = observatory
    body = application.handle("GET", f"/contests/{contest_id}").body.decode()
    assert body.count("<script>") == 0
    assert "javascript:void(0)" not in body or "&amp;&amp;" in body


def test_the_inbox_lists_the_entry_without_rendering_its_content(observatory):
    application, contest_id, _ = observatory
    body = application.handle("GET", "/contests").body.decode()
    assert contest_id in body
    assert "slot-collision" in body
    assert "1 open" in body
    # The listing shows the ledger, not the challenger's text.
    assert "alert" not in body


def test_the_detail_page_offers_commands_not_buttons(observatory):
    application, contest_id, _ = observatory
    body = application.handle("GET", f"/contests/{contest_id}").body.decode()
    assert f"cortex-mem contest resolve {contest_id} --admit" in body
    assert "--supersede incumbent" in body
    assert "<form" not in body
    assert "<button" not in body


def test_truth_links_to_the_inbox_with_counts_only(observatory):
    application, _, _ = observatory
    body = application.handle("GET", "/truth").body.decode()
    assert "1 open" in body
    assert '<a href="/contests">' in body
    assert "alert" not in body


def test_an_unknown_contest_is_a_clean_404(observatory):
    application, _, _ = observatory
    response = application.handle("GET", "/contests/does-not-exist")
    assert response.status == 404
    assert b"Contest not found" in response.body


def test_a_store_without_the_ledger_still_serves_every_page(tmp_path):
    db_path = tmp_path / "aoms.sqlite3"
    asyncio.run(SQLiteMemoryRepository(db_path).initialize())
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE contest_entries")
        connection.commit()
    application = ObservatoryApplication(db_path)
    assert application.handle("GET", "/contests").status == 200
    assert application.handle("GET", "/truth").status == 200
    assert b"No contested writes" in application.handle("GET", "/contests").body

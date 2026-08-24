from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aoms.auth import AOMSTokenVerifier, TokenBucketLimiter, TokenStore
from aoms.repositories.sqlite import LATEST_SCHEMA_VERSION, SQLiteMemoryRepository


@pytest.mark.asyncio
async def test_token_lifecycle_hash_at_rest_last_used_and_revoke(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "aoms.sqlite3"
    store = TokenStore(db_path)
    created = await store.create(
        name="laptop",
        scopes=["write", "read", "read"],
        agent_id="agent-a",
        workspace_id="workspace-a",
    )

    assert created.secret.startswith(f"aoms_{created.token.token_id}_")
    assert created.token.scopes == ("read", "write")
    raw = db_path.read_bytes()
    assert created.secret.encode() not in raw
    assert created.secret.split("_", 2)[2].encode() not in raw

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT salt, secret_hash, last_used_at FROM auth_tokens"
        ).fetchone()
    assert len(row[0]) == 16
    assert len(row[1]) == 32
    assert row[2] is None

    authenticated = await store.authenticate(created.secret)
    assert authenticated is not None
    assert authenticated.agent_id == "agent-a"
    assert authenticated.workspace_id == "workspace-a"
    assert authenticated.last_used_at is not None
    assert await store.authenticate(created.secret + "wrong") is None

    assert await store.revoke(created.token.token_id) is True
    assert await store.revoke(created.token.token_id) is False
    assert await store.authenticate(created.secret) is None
    assert (await store.list())[0].status == "revoked"


@pytest.mark.asyncio
async def test_expired_token_is_rejected_and_not_counted_as_usable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "aoms.sqlite3"
    store = TokenStore(db_path)
    created = await store.create(
        name="short-lived",
        scopes=["read"],
        agent_id="agent",
        workspace_id="workspace",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE auth_tokens SET expires_at = ? WHERE token_id = ?",
            (
                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                created.token.token_id,
            ),
        )

    assert await store.authenticate(created.secret) is None
    assert await store.usable_count() == 0
    assert (await store.list())[0].status == "expired"


@pytest.mark.asyncio
async def test_verifier_returns_only_non_secret_identity_claims(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "aoms.sqlite3")
    created = await store.create(
        name="remote",
        scopes=["read", "admin"],
        agent_id="bound-agent",
        workspace_id="bound-workspace",
    )
    access = await AOMSTokenVerifier(store).verify_token(created.secret)

    assert access is not None
    assert access.token == created.token.token_id
    assert access.scopes == ["admin", "read"]
    assert access.claims == {
        "agent_id": "bound-agent",
        "workspace_id": "bound-workspace",
    }
    assert created.secret not in access.model_dump_json()


def test_token_bucket_is_per_token_and_refills() -> None:
    now = [100.0]
    limiter = TokenBucketLimiter(
        rate_per_second=2.0,
        capacity=2,
        clock=lambda: now[0],
    )

    assert limiter.consume("a") is True
    assert limiter.consume("a") is True
    assert limiter.consume("a") is False
    assert limiter.consume("b") is True
    now[0] += 0.5
    assert limiter.consume("a") is True
    assert limiter.consume("a") is False


@pytest.mark.asyncio
async def test_auth_migration_is_additive_to_existing_v4_store(tmp_path: Path) -> None:
    db_path = tmp_path / "v4.sqlite3"
    repository = SQLiteMemoryRepository(db_path)
    await repository.initialize()
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM schema_version WHERE version = 5")
        connection.execute("DROP TABLE auth_tokens")
    upgraded = SQLiteMemoryRepository(db_path)
    await upgraded.initialize()

    assert await upgraded.schema_version() == LATEST_SCHEMA_VERSION
    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(auth_tokens)")
        }
    assert {
        "token_id",
        "name",
        "scopes_json",
        "agent_id",
        "workspace_id",
        "salt",
        "secret_hash",
        "created_at",
        "last_used_at",
        "expires_at",
        "revoked_at",
    } == columns

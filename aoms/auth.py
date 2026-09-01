"""Local bearer-token lifecycle and verification for remote MCP access."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from mcp.server.auth.provider import AccessToken

# Guard against an under-pinned mcp (issue #13): before 1.29 AccessToken has no
# `claims` field, and pydantic silently DROPS the unknown kwarg below -- token
# claims (agent_id/workspace_id) would vanish instead of failing. Refuse to
# import rather than run scopeless.
if "claims" not in getattr(AccessToken, "model_fields", {}):
    raise ImportError(
        "mcp.server.auth.provider.AccessToken has no `claims` field; "
        "installed mcp is below the pyproject pin (>=1.29,<2). "
        "Upgrade mcp -- running without claims silently discards token "
        "agent/workspace identity."
    )

from aoms.repositories.sqlite import SQLiteMemoryRepository

TOKEN_PREFIX = "aoms"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
HASH_BYTES = 32
SALT_BYTES = 16


class TokenScope(StrEnum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class AuthToken:
    token_id: str
    name: str
    scopes: tuple[str, ...]
    agent_id: str
    workspace_id: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

    @property
    def status(self) -> str:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None and self.expires_at <= datetime.now(
            timezone.utc
        ):
            return "expired"
        return "active"


@dataclass(frozen=True, slots=True)
class CreatedToken:
    token: AuthToken
    secret: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_secret(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=HASH_BYTES,
    )


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _token_from_row(row: sqlite3.Row) -> AuthToken:
    return AuthToken(
        token_id=row["token_id"],
        name=row["name"],
        scopes=tuple(json.loads(row["scopes_json"])),
        agent_id=row["agent_id"],
        workspace_id=row["workspace_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        last_used_at=_parse_datetime(row["last_used_at"]),
        expires_at=_parse_datetime(row["expires_at"]),
        revoked_at=_parse_datetime(row["revoked_at"]),
    )


class TokenStore:
    """Manage salted token hashes in the canonical AOMS SQLite database."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._repository = SQLiteMemoryRepository(self.db_path)

    async def initialize(self) -> None:
        await self._repository.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    async def create(
        self,
        *,
        name: str,
        scopes: Sequence[str | TokenScope],
        agent_id: str,
        workspace_id: str,
        expires_at: datetime | None = None,
    ) -> CreatedToken:
        await self.initialize()
        normalized_name = name.strip()
        normalized_agent = agent_id.strip()
        normalized_workspace = workspace_id.strip()
        if not normalized_name:
            raise ValueError("token name must not be empty")
        if not normalized_agent or not normalized_workspace:
            raise ValueError("agent_id and workspace_id must not be empty")
        normalized_scopes = tuple(
            sorted({TokenScope(str(scope)).value for scope in scopes})
        )
        if not normalized_scopes:
            raise ValueError("at least one token scope is required")
        if expires_at is not None:
            if expires_at.tzinfo is None:
                raise ValueError("expires_at must include a timezone")
            expires_at = expires_at.astimezone(timezone.utc)
            if expires_at <= _utcnow():
                raise ValueError("expires_at must be in the future")

        token_id = secrets.token_hex(8)
        secret_part = secrets.token_urlsafe(32)
        salt = secrets.token_bytes(SALT_BYTES)
        secret_hash = await asyncio.to_thread(_hash_secret, secret_part, salt)
        created_at = _utcnow()
        await asyncio.to_thread(
            self._insert_sync,
            token_id,
            normalized_name,
            normalized_scopes,
            normalized_agent,
            normalized_workspace,
            salt,
            secret_hash,
            created_at,
            expires_at,
        )
        record = AuthToken(
            token_id=token_id,
            name=normalized_name,
            scopes=normalized_scopes,
            agent_id=normalized_agent,
            workspace_id=normalized_workspace,
            created_at=created_at,
            last_used_at=None,
            expires_at=expires_at,
            revoked_at=None,
        )
        return CreatedToken(
            token=record,
            secret=f"{TOKEN_PREFIX}_{token_id}_{secret_part}",
        )

    def _insert_sync(
        self,
        token_id: str,
        name: str,
        scopes: tuple[str, ...],
        agent_id: str,
        workspace_id: str,
        salt: bytes,
        secret_hash: bytes,
        created_at: datetime,
        expires_at: datetime | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_tokens(
                    token_id, name, scopes_json, agent_id, workspace_id,
                    salt, secret_hash, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    name,
                    json.dumps(scopes, separators=(",", ":")),
                    agent_id,
                    workspace_id,
                    salt,
                    secret_hash,
                    created_at.isoformat(),
                    expires_at.isoformat() if expires_at else None,
                ),
            )

    async def list(self) -> list[AuthToken]:
        await self.initialize()
        return await asyncio.to_thread(self._list_sync)

    def _list_sync(self) -> list[AuthToken]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM auth_tokens ORDER BY created_at DESC, token_id DESC"
            ).fetchall()
        return [_token_from_row(row) for row in rows]

    async def revoke(self, token_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._revoke_sync, token_id.strip())

    def _revoke_sync(self, token_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE auth_tokens
                SET revoked_at = ?
                WHERE token_id = ? AND revoked_at IS NULL
                """,
                (_utcnow().isoformat(), token_id),
            )
        return cursor.rowcount == 1

    async def usable_count(self) -> int:
        await self.initialize()
        return await asyncio.to_thread(self._usable_count_sync)

    def _usable_count_sync(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM auth_tokens
                WHERE revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (_utcnow().isoformat(),),
            ).fetchone()
        return int(row["count"])

    async def authenticate(self, presented_token: str) -> AuthToken | None:
        await self.initialize()
        parts = presented_token.split("_", 2)
        if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
            return None
        _, token_id, secret_part = parts
        if not token_id or not secret_part:
            return None
        return await asyncio.to_thread(self._authenticate_sync, token_id, secret_part)

    def _authenticate_sync(self, token_id: str, secret_part: str) -> AuthToken | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_tokens WHERE token_id = ?", (token_id,)
            ).fetchone()
            if row is None:
                return None
            candidate = _hash_secret(secret_part, bytes(row["salt"]))
            if not hmac.compare_digest(candidate, bytes(row["secret_hash"])):
                return None
            record = _token_from_row(row)
            now = _utcnow()
            if record.revoked_at is not None:
                return None
            if record.expires_at is not None and record.expires_at <= now:
                return None
            connection.execute(
                "UPDATE auth_tokens SET last_used_at = ? WHERE token_id = ?",
                (now.isoformat(), token_id),
            )
        return AuthToken(
            token_id=record.token_id,
            name=record.name,
            scopes=record.scopes,
            agent_id=record.agent_id,
            workspace_id=record.workspace_id,
            created_at=record.created_at,
            last_used_at=now,
            expires_at=record.expires_at,
            revoked_at=None,
        )


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    """In-process token bucket keyed by durable token id."""

    def __init__(
        self,
        *,
        rate_per_second: float,
        capacity: int,
        clock: Callable[[], float] = time.monotonic,
    ):
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.rate_per_second = rate_per_second
        self.capacity = capacity
        self.clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def consume(self, token_id: str) -> bool:
        now = self.clock()
        bucket = self._buckets.get(token_id)
        if bucket is None:
            self._buckets[token_id] = _Bucket(self.capacity - 1.0, now)
            return True
        elapsed = max(0.0, now - bucket.updated_at)
        bucket.tokens = min(
            float(self.capacity), bucket.tokens + elapsed * self.rate_per_second
        )
        bucket.updated_at = now
        if bucket.tokens < 1.0:
            return False
        bucket.tokens -= 1.0
        return True


class AOMSTokenVerifier:
    """Adapt the local token store to the MCP SDK's bearer verifier contract."""

    def __init__(self, store: TokenStore):
        self.store = store

    async def verify_token(self, token: str) -> AccessToken | None:
        record = await self.store.authenticate(token)
        if record is None:
            return None
        return AccessToken(
            token=record.token_id,
            client_id=record.token_id,
            subject=record.name,
            scopes=list(record.scopes),
            expires_at=(
                int(record.expires_at.timestamp()) if record.expires_at else None
            ),
            claims={
                "agent_id": record.agent_id,
                "workspace_id": record.workspace_id,
            },
        )


__all__ = [
    "AOMSTokenVerifier",
    "AuthToken",
    "CreatedToken",
    "TokenBucketLimiter",
    "TokenScope",
    "TokenStore",
]

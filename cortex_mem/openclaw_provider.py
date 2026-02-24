"""OpenClaw memory-provider interface backed by cortex-mem.

Provides a drop-in replacement for OpenClaw's default local memory
store, routing reads and writes through the AOMS HTTP API.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx


class CortexMemProvider:
    """OpenClaw-compatible memory provider that delegates to cortex-mem."""

    def __init__(self, url: str = "http://localhost:9100", timeout: float = 10.0):
        self.url = url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.url, timeout=timeout)

    async def log(
        self,
        entry_type: str,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Write an episodic entry through the AOMS API."""
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": entry_type,
            "title": title,
            "outcome": content,
            "tags": tags or [],
        }
        resp = await self._client.post(
            "/memory/episodic",
            json={"tier": "episodic", "type": "experience", "payload": payload},
        )
        resp.raise_for_status()
        return resp.json().get("id")

    async def search(
        self,
        query: str,
        limit: int = 5,
        tier: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Search memory across tiers."""
        body: dict = {"query": query, "limit": limit}
        if tier:
            body["tier"] = tier
        resp = await self._client.post("/memory/search", json=body)
        resp.raise_for_status()
        return resp.json()

    async def health(self) -> Dict[str, Any]:
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

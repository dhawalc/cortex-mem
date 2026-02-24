"""
Python client for openclaw-memory AOMS.

Usage:
    from service.client import MemoryClient

    async with MemoryClient() as memory:
        await memory.write("episodic", "experience", {
            "title": "Shipped AOMS",
            "outcome": "Service running on port 9100",
        })

        results = await memory.search("AOMS")
        health = await memory.health()
"""
from typing import Any, Dict, List, Optional

import httpx


class MemoryClient:
    """Async HTTP client for the AOMS API."""

    def __init__(self, base_url: str = "http://localhost:9100", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def write(
        self,
        tier: str,
        entry_type: str,
        payload: Dict[str, Any],
        tags: Optional[List[str]] = None,
        weight: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Write a memory entry to a tier."""
        body: Dict[str, Any] = {"type": entry_type, "payload": payload}
        if tags:
            body["tags"] = tags
        if weight is not None:
            body["weight"] = weight

        resp = await self._client.post(f"/memory/{tier}", json=body)
        resp.raise_for_status()
        return resp.json()

    async def search(
        self,
        query: str,
        tier: Optional[List[str]] = None,
        limit: int = 10,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_weight: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Search memory across tiers."""
        body: Dict[str, Any] = {"query": query, "limit": limit}
        if tier:
            body["tier"] = tier
        if date_from:
            body["date_from"] = date_from
        if date_to:
            body["date_to"] = date_to
        if min_weight is not None:
            body["min_weight"] = min_weight

        resp = await self._client.post("/memory/search", json=body)
        resp.raise_for_status()
        return resp.json()

    async def browse(self, path: str = "") -> Dict[str, Any]:
        """Browse the module tree at a given path."""
        endpoint = f"/memory/browse/{path}" if path else "/memory/browse"
        resp = await self._client.get(endpoint)
        resp.raise_for_status()
        return resp.json()

    async def adjust_weight(
        self,
        entry_id: str,
        tier: str,
        task_score: float,
    ) -> Dict[str, Any]:
        """Adjust a memory entry's weight based on task outcome."""
        resp = await self._client.post(
            "/memory/weight",
            json={"entry_id": entry_id, "tier": tier, "task_score": task_score},
        )
        resp.raise_for_status()
        return resp.json()

    async def health(self) -> Dict[str, Any]:
        """Check service health."""
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

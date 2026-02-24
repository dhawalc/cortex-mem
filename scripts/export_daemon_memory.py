#!/usr/bin/env python3.12
"""
One-time migration: Export Daemon memory → AOMS.

Copies episodic, semantic, and procedural data from Daemon's local stores
into the AOMS JSONL endpoints via HTTP API.

Features:
- Batched writes (configurable batch size, default 100)
- Idempotency: tracks migrated IDs in a local checkpoint file
- Progress reporting with ETA
- Dry-run mode to preview without writing
- Resumable: re-run safely; skips already-migrated entries

Usage:
    python scripts/export_daemon_memory.py                    # full migration
    python scripts/export_daemon_memory.py --dry-run          # preview only
    python scripts/export_daemon_memory.py --tier episodic    # single tier
    python scripts/export_daemon_memory.py --batch-size 50    # smaller batches
    python scripts/export_daemon_memory.py --limit 100        # first 100 per tier
"""

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Set

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("migration")

DAEMON_MEMORY = Path("/home/dhawal/daemon/memory_data")
AOMS_URL = "http://localhost:9100"
CHECKPOINT_FILE = Path(__file__).parent / "migrated_ids.json"


def load_checkpoint() -> Dict[str, Set[str]]:
    if CHECKPOINT_FILE.exists():
        data = json.loads(CHECKPOINT_FILE.read_text())
        return {k: set(v) for k, v in data.items()}
    return {"episodic": set(), "semantic_facts": set(), "semantic_relations": set(), "procedural": set()}


def save_checkpoint(checkpoint: Dict[str, Set[str]]):
    data = {k: list(v) for k, v in checkpoint.items()}
    CHECKPOINT_FILE.write_text(json.dumps(data))


async def migrate_episodic(
    client: httpx.AsyncClient,
    checkpoint: Dict[str, Set[str]],
    batch_size: int,
    dry_run: bool,
    limit: int = 0,
) -> int:
    episodes_file = DAEMON_MEMORY / "episodic" / "episodes.json"
    if not episodes_file.exists():
        logger.warning("No episodic data found")
        return 0

    episodes = json.loads(episodes_file.read_text())
    total = len(episodes)
    if limit:
        episodes = episodes[:limit]

    migrated = checkpoint.get("episodic", set())
    to_migrate = [e for e in episodes if e.get("id", "") not in migrated]
    logger.info(f"Episodic: {len(to_migrate)} to migrate ({total} total, {len(migrated)} already done)")

    if dry_run:
        return len(to_migrate)

    written = 0
    start = time.time()

    for i in range(0, len(to_migrate), batch_size):
        batch = to_migrate[i : i + batch_size]

        for entry in batch:
            entry_id = entry.get("id", "")
            document = entry.get("document", "")
            metadata = entry.get("metadata", {})
            episode = entry.get("episode", {})

            content = document or episode.get("content", "")
            if not content:
                continue

            payload = {
                "ts": metadata.get("created_at", episode.get("created_at", "")),
                "type": metadata.get("event_type", episode.get("event_type", "observation")),
                "title": content[:120].replace("\n", " "),
                "content": content,
                "outcome": episode.get("outcome", ""),
                "source": metadata.get("source", episode.get("source", "daemon")),
                "importance": metadata.get("importance", episode.get("importance", 0.5)),
                "daemon_id": entry_id,
                "tags": episode.get("tags", []),
            }

            try:
                resp = await client.post(
                    "/memory/episodic",
                    json={"tier": "episodic", "type": "experience", "payload": payload, "tags": payload["tags"]},
                )
                resp.raise_for_status()
                migrated.add(entry_id)
                written += 1
            except Exception as e:
                logger.error(f"Failed to write episode {entry_id}: {e}")

        checkpoint["episodic"] = migrated
        save_checkpoint(checkpoint)

        elapsed = time.time() - start
        rate = written / elapsed if elapsed > 0 else 0
        remaining = len(to_migrate) - (i + len(batch))
        eta = remaining / rate if rate > 0 else 0
        logger.info(
            f"  Episodic: {written}/{len(to_migrate)} "
            f"({rate:.0f}/s, ETA {eta:.0f}s)"
        )

    return written


async def migrate_semantic(
    client: httpx.AsyncClient,
    checkpoint: Dict[str, Set[str]],
    batch_size: int,
    dry_run: bool,
    limit: int = 0,
) -> int:
    db_path = DAEMON_MEMORY / "semantic" / "knowledge_graph.db"
    if not db_path.exists():
        logger.warning("No semantic DB found")
        return 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM facts WHERE valid_to IS NULL AND invalidated_at IS NULL"
    if limit:
        query += f" LIMIT {limit}"
    facts = [dict(r) for r in conn.execute(query).fetchall()]

    migrated = checkpoint.get("semantic_facts", set())
    to_migrate = [f for f in facts if f["id"] not in migrated]
    logger.info(f"Semantic facts: {len(to_migrate)} to migrate ({len(facts)} current, {len(migrated)} done)")

    if dry_run:
        conn.close()
        return len(to_migrate)

    written = 0
    start = time.time()

    for i in range(0, len(to_migrate), batch_size):
        batch = to_migrate[i : i + batch_size]

        for fact in batch:
            payload = {
                "ts": fact.get("created_at", ""),
                "subject": fact["subject"],
                "predicate": fact["predicate"],
                "object": fact["object"],
                "confidence": fact.get("confidence", 0.8),
                "source": fact.get("source", "daemon"),
                "daemon_id": fact["id"],
                "tags": [],
            }

            try:
                resp = await client.post(
                    "/memory/semantic",
                    json={"tier": "semantic", "type": "fact", "payload": payload},
                )
                resp.raise_for_status()
                migrated.add(fact["id"])
                written += 1
            except Exception as e:
                logger.error(f"Failed to write fact {fact['id']}: {e}")

        checkpoint["semantic_facts"] = migrated
        save_checkpoint(checkpoint)

        elapsed = time.time() - start
        rate = written / elapsed if elapsed > 0 else 0
        logger.info(f"  Facts: {written}/{len(to_migrate)} ({rate:.0f}/s)")

    conn.close()
    return written


async def migrate_procedural(
    client: httpx.AsyncClient,
    checkpoint: Dict[str, Set[str]],
    batch_size: int,
    dry_run: bool,
    limit: int = 0,
) -> int:
    skills_file = DAEMON_MEMORY / "procedural" / "skills.json"
    if not skills_file.exists():
        logger.warning("No procedural data found")
        return 0

    skills = json.loads(skills_file.read_text())
    if limit:
        skills = skills[:limit]

    migrated = checkpoint.get("procedural", set())
    to_migrate = [s for s in skills if s.get("id", "") not in migrated]
    logger.info(f"Procedural: {len(to_migrate)} to migrate ({len(skills)} total, {len(migrated)} done)")

    if dry_run:
        return len(to_migrate)

    written = 0
    start = time.time()

    for i in range(0, len(to_migrate), batch_size):
        batch = to_migrate[i : i + batch_size]

        for skill in batch:
            payload = {
                "ts": skill.get("created_at", ""),
                "skill_name": skill.get("name", "unknown"),
                "description": skill.get("description", ""),
                "category": "daemon",
                "when_to_use": skill.get("trigger", ""),
                "procedure": skill.get("procedure", ""),
                "success_rate": skill.get("success_rate", 0.0),
                "daemon_id": skill.get("id", ""),
                "tags": skill.get("tags", []),
            }

            try:
                resp = await client.post(
                    "/memory/procedural",
                    json={"tier": "procedural", "type": "skill", "payload": payload, "tags": payload["tags"]},
                )
                resp.raise_for_status()
                migrated.add(skill.get("id", ""))
                written += 1
            except Exception as e:
                logger.error(f"Failed to write skill {skill.get('name')}: {e}")

        checkpoint["procedural"] = migrated
        save_checkpoint(checkpoint)

        elapsed = time.time() - start
        rate = written / elapsed if elapsed > 0 else 0
        logger.info(f"  Skills: {written}/{len(to_migrate)} ({rate:.0f}/s)")

    return written


async def main():
    parser = argparse.ArgumentParser(description="Export Daemon memory to AOMS")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--tier", choices=["episodic", "semantic", "procedural"], help="Migrate single tier")
    parser.add_argument("--batch-size", type=int, default=100, help="Entries per batch (default 100)")
    parser.add_argument("--limit", type=int, default=0, help="Max entries per tier (0=all)")
    parser.add_argument("--aoms-url", default=AOMS_URL, help="AOMS base URL")
    args = parser.parse_args()

    async with httpx.AsyncClient(base_url=args.aoms_url, timeout=30.0) as client:
        try:
            health = (await client.get("/health")).json()
            logger.info(f"AOMS: v{health['version']}, tiers={health['tiers']}")
        except Exception as e:
            logger.error(f"AOMS unreachable at {args.aoms_url}: {e}")
            sys.exit(1)

        checkpoint = load_checkpoint()
        results = {}

        tiers = [args.tier] if args.tier else ["episodic", "semantic", "procedural"]

        if "episodic" in tiers:
            results["episodic"] = await migrate_episodic(client, checkpoint, args.batch_size, args.dry_run, args.limit)
        if "semantic" in tiers:
            results["semantic"] = await migrate_semantic(client, checkpoint, args.batch_size, args.dry_run, args.limit)
        if "procedural" in tiers:
            results["procedural"] = await migrate_procedural(client, checkpoint, args.batch_size, args.dry_run, args.limit)

        health_after = (await client.get("/health")).json()

    logger.info("=" * 50)
    prefix = "[DRY RUN] " if args.dry_run else ""
    for tier, count in results.items():
        logger.info(f"  {prefix}{tier}: {count} entries")
    logger.info(f"  AOMS tiers after: {health_after['tiers']}")
    logger.info(f"  Checkpoint: {CHECKPOINT_FILE}")
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())

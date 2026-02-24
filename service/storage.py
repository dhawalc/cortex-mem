"""
JSONL storage engine for AOMS.

Handles append-only writes, keyword search with weighted scoring,
and reinforcement-based weight adjustment.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("aoms.storage")

TIER_FILE_MAP: Dict[str, Dict[str, str]] = {
    "episodic": {
        "experience": "modules/memory/episodic/experiences.jsonl",
        "decision": "modules/memory/episodic/decisions.jsonl",
        "failure": "modules/memory/episodic/failures.jsonl",
    },
    "semantic": {
        "fact": "modules/memory/semantic/facts.jsonl",
        "relation": "modules/memory/semantic/relations.jsonl",
    },
    "procedural": {
        "skill": "modules/memory/procedural/skills.jsonl",
        "pattern": "modules/memory/procedural/patterns.jsonl",
    },
}

ALL_TIERS = list(TIER_FILE_MAP.keys())

CATEGORY_INITIAL_WEIGHTS: Dict[str, float] = {
    "user_teaching": 2.0,
    "user_correction": 1.8,
    "self_correction": 1.5,
    "achievement": 1.3,
    "decision": 1.2,
    "failure": 1.0,
    "observation": 0.8,
    "fact": 1.0,
    "skill": 1.2,
    "pattern": 1.0,
}

WEIGHT_MIN = 0.1
WEIGHT_MAX = 5.0
DECAY_RATE = 0.995
BOOST_FACTOR = 1.1
DECAY_FACTOR = 0.9


def _clamp_weight(w: float) -> float:
    return max(WEIGHT_MIN, min(WEIGHT_MAX, w))


def _resolve_file(root: Path, tier: str, entry_type: str) -> Path:
    """Resolve the JSONL file path for a tier + type combination."""
    tier_map = TIER_FILE_MAP.get(tier)
    if not tier_map:
        raise ValueError(f"Unknown tier: {tier}")
    rel = tier_map.get(entry_type)
    if not rel:
        default_type = next(iter(tier_map))
        rel = tier_map[default_type]
        logger.debug(f"Type '{entry_type}' not mapped for tier '{tier}', using default: {default_type}")
    return root / rel


def _all_files_for_tier(root: Path, tier: str) -> List[Path]:
    """Return all JSONL files belonging to a tier."""
    tier_map = TIER_FILE_MAP.get(tier, {})
    return [root / rel for rel in tier_map.values()]


class MemoryStorage:
    """Append-only JSONL storage with weighted retrieval."""

    def __init__(self, root: Path):
        self.root = root

    async def append(
        self,
        tier: str,
        entry_type: str,
        payload: Dict[str, Any],
        tags: Optional[List[str]] = None,
        weight: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Append an entry to the appropriate JSONL file.

        Returns the stored entry (with generated id/ts/weight).
        """
        filepath = _resolve_file(self.root, tier, entry_type)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        if weight is None:
            weight = CATEGORY_INITIAL_WEIGHTS.get(entry_type, 1.0)
        weight = _clamp_weight(weight)

        record = {
            "id": entry_id,
            "ts": payload.get("ts", now),
            **payload,
            "tags": tags or payload.get("tags", []),
            "weight": weight,
            "_tier": tier,
            "_type": entry_type,
            "_written_at": now,
        }

        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line)

        logger.info(f"Wrote to {tier}/{entry_type}: {entry_id}")
        return record

    async def search(
        self,
        query: str,
        tiers: Optional[List[str]] = None,
        limit: int = 10,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        min_weight: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Keyword search across JSONL files with weighted scoring.

        Score = keyword_hits * weight * recency_decay
        """
        search_tiers = tiers or ALL_TIERS
        query_lower = query.lower()
        query_terms = query_lower.split()

        scored_results: List[Tuple[float, Dict[str, Any], int]] = []

        for tier in search_tiers:
            if tier not in TIER_FILE_MAP:
                continue
            for filepath in _all_files_for_tier(self.root, tier):
                if not filepath.exists():
                    continue
                results = _search_file(
                    filepath, tier, query_terms, date_from, date_to, min_weight
                )
                scored_results.extend(results)

        scored_results.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "tier": r[1].get("_tier", ""),
                "type": r[1].get("_type", ""),
                "entry": r[1],
                "score": round(r[0], 4),
                "line_number": r[2],
            }
            for r in scored_results[:limit]
        ]

    async def browse(self, path: str) -> Dict[str, Any]:
        """List modules and files at a given path."""
        dir_path = self.root / "modules" / path if path else self.root / "modules"
        if not dir_path.exists() or not dir_path.is_dir():
            return {"path": path, "exists": False, "subdirs": [], "files": []}

        subdirs = sorted(d.name for d in dir_path.iterdir() if d.is_dir())
        files = sorted(f.name for f in dir_path.iterdir() if f.is_file())
        return {"path": path or "/", "exists": True, "subdirs": subdirs, "files": files}

    async def count_entries(self) -> Dict[str, int]:
        """Count entries per tier (excluding schema headers)."""
        counts: Dict[str, int] = {}
        for tier in ALL_TIERS:
            total = 0
            for filepath in _all_files_for_tier(self.root, tier):
                if filepath.exists():
                    total += _count_data_lines(filepath)
            counts[tier] = total
        return counts

    async def adjust_weight(
        self,
        entry_id: str,
        tier: str,
        task_score: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Adjust weight of a specific entry based on task outcome.

        Uses reinforcement learning pattern from weighted-memory-poc:
        - task_score > 0.7 → boost (memory was helpful)
        - task_score < 0.3 → decay (memory wasn't helpful)
        - else → neutral time decay
        """
        for filepath in _all_files_for_tier(self.root, tier):
            if not filepath.exists():
                continue
            result = _update_entry_weight(filepath, entry_id, task_score)
            if result is not None:
                return result
        return None


def _search_file(
    filepath: Path,
    tier: str,
    query_terms: List[str],
    date_from: Optional[str],
    date_to: Optional[str],
    min_weight: Optional[float],
) -> List[Tuple[float, Dict[str, Any], int]]:
    """Search a single JSONL file, returning (score, entry, line_number) tuples."""
    results = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if "schema" in entry:
                continue

            if date_from and entry.get("ts", "") < date_from:
                continue
            if date_to and entry.get("ts", "") > date_to:
                continue

            weight = entry.get("weight", 1.0)
            if min_weight is not None and weight < min_weight:
                continue

            text_blob = json.dumps(entry, ensure_ascii=False).lower()
            hits = sum(1 for term in query_terms if term in text_blob)
            if hits == 0:
                continue

            keyword_score = hits / max(len(query_terms), 1)
            recency = _recency_score(entry.get("ts"))
            score = keyword_score * weight * recency

            results.append((score, entry, line_num))

    return results


def _recency_score(ts: Optional[str]) -> float:
    """Calculate time-decay recency score. DECAY_RATE^days_old."""
    if not ts:
        return 1.0
    try:
        created = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days_old = max(0, (now - created).days)
        return DECAY_RATE ** days_old
    except (ValueError, TypeError):
        return 1.0


def _count_data_lines(filepath: Path) -> int:
    """Count non-schema, non-empty lines in a JSONL file."""
    count = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "schema" not in obj:
                    count += 1
            except json.JSONDecodeError:
                continue
    return count


def _update_entry_weight(
    filepath: Path, entry_id: str, task_score: float
) -> Optional[Dict[str, Any]]:
    """
    Rewrite a JSONL file, adjusting the weight of the entry with the given ID.

    Since JSONL is append-only by design, weight updates rewrite the file.
    This is acceptable because weight adjustments are infrequent batch operations.
    """
    lines = filepath.read_text(encoding="utf-8").splitlines(keepends=True)
    found = None
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue

        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue

        if entry.get("id") == entry_id:
            old_weight = entry.get("weight", 1.0)
            if task_score > 0.7:
                new_weight = old_weight * BOOST_FACTOR
            elif task_score < 0.3:
                new_weight = old_weight * DECAY_FACTOR
            else:
                new_weight = old_weight * DECAY_RATE

            entry["weight"] = round(_clamp_weight(new_weight), 4)
            entry["_weight_updated_at"] = datetime.now(timezone.utc).isoformat()
            found = entry
            new_lines.append(json.dumps(entry, ensure_ascii=False) + "\n")
        else:
            new_lines.append(line)

    if found is not None:
        filepath.write_text("".join(new_lines), encoding="utf-8")
        logger.info(f"Weight updated for {entry_id}: {found.get('weight')}")

    return found

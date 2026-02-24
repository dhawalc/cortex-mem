"""
SQLite metadata store for Cortex tiered documents.
Thread-safe, async-compatible via aiosqlite.
"""
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent.parent / "index" / "cortex_tiers.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = _get_conn(db_path)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def insert_document(conn: sqlite3.Connection, doc: Dict[str, Any]) -> str:
    doc_id = doc.get("doc_id") or str(uuid.uuid4())
    tags = json.dumps(doc.get("tags", []))
    conn.execute(
        """
        INSERT OR REPLACE INTO documents (
            doc_id, hierarchy_path, title, doc_type,
            l0_abstract, l0_token_count,
            l1_overview, l1_token_count,
            l2_file_path, l2_token_count, l2_checksum,
            chromadb_l0_id, chromadb_l1_id,
            parent_path, depth, tags,
            l0_generated_at, l1_generated_at,
            source_type, cortex_tier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc_id,
            doc["hierarchy_path"],
            doc["title"],
            doc["doc_type"],
            doc["l0_abstract"],
            doc["l0_token_count"],
            doc.get("l1_overview"),
            doc.get("l1_token_count", 0),
            doc["l2_file_path"],
            doc.get("l2_token_count", 0),
            doc["l2_checksum"],
            doc.get("chromadb_l0_id"),
            doc.get("chromadb_l1_id"),
            doc.get("parent_path"),
            doc.get("depth", 0),
            tags,
            doc.get("l0_generated_at"),
            doc.get("l1_generated_at"),
            doc.get("source_type", "manual"),
            doc.get("cortex_tier"),
        ),
    )
    conn.commit()
    return doc_id


def get_document(conn: sqlite3.Connection, doc_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def get_all_documents(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM documents ORDER BY updated_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def search_by_hierarchy(
    conn: sqlite3.Connection, prefix: str
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM documents WHERE hierarchy_path LIKE ? ORDER BY hierarchy_path",
        (prefix + "%",),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def mark_stale(conn: sqlite3.Connection, doc_id: str, reason: str):
    conn.execute(
        "UPDATE documents SET is_stale = 1, stale_reason = ? WHERE doc_id = ?",
        (reason, doc_id),
    )
    conn.commit()


def log_query(
    conn: sqlite3.Connection,
    query_text: str,
    l0_results: int,
    l1_expansions: int,
    l2_loads: int,
    total_tokens: int,
    latency_ms: int,
    agent_id: Optional[str] = None,
):
    conn.execute(
        """
        INSERT INTO query_log (query_id, query_text, agent_id,
            l0_results, l1_expansions, l2_loads, total_tokens, latency_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), query_text, agent_id,
         l0_results, l1_expansions, l2_loads, total_tokens, latency_ms),
    )
    conn.commit()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    if isinstance(d.get("tags"), str):
        try:
            d["tags"] = json.loads(d["tags"])
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
    d["is_stale"] = bool(d.get("is_stale"))
    return d

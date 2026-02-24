-- Cortex Tiered Retrieval — SQLite schema
-- Equivalent to cortex_tiers PostgreSQL schema from master plan.
-- Stores document metadata + L0/L1 content; L2 lives on filesystem.

CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,
    hierarchy_path  TEXT NOT NULL,
    title           TEXT NOT NULL,
    doc_type        TEXT NOT NULL CHECK (doc_type IN (
        'strategy', 'backtest', 'research', 'episode',
        'skill', 'pattern', 'session_learning', 'reference'
    )),

    -- Tier content
    l0_abstract     TEXT NOT NULL,
    l0_token_count  INTEGER NOT NULL,
    l1_overview     TEXT,
    l1_token_count  INTEGER DEFAULT 0,
    l2_file_path    TEXT NOT NULL,
    l2_token_count  INTEGER DEFAULT 0,
    l2_checksum     TEXT NOT NULL,

    -- ChromaDB references
    chromadb_l0_id  TEXT,
    chromadb_l1_id  TEXT,

    -- Hierarchy
    parent_path     TEXT,
    depth           INTEGER DEFAULT 0,
    tags            TEXT DEFAULT '[]',

    -- Timestamps
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    l0_generated_at TEXT,
    l1_generated_at TEXT,

    -- Invalidation
    is_stale        INTEGER DEFAULT 0,
    stale_reason    TEXT,

    -- Source tracking
    source_type     TEXT DEFAULT 'manual',
    cortex_tier     TEXT CHECK (cortex_tier IN ('episodic', 'semantic', 'procedural') OR cortex_tier IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_docs_hierarchy ON documents (hierarchy_path);
CREATE INDEX IF NOT EXISTS idx_docs_parent ON documents (parent_path);
CREATE INDEX IF NOT EXISTS idx_docs_type ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_docs_stale ON documents (is_stale) WHERE is_stale = 1;

CREATE TABLE IF NOT EXISTS directories (
    dir_id      TEXT PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,
    parent_path TEXT,
    name        TEXT NOT NULL,
    description TEXT,
    doc_count   INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_dirs_parent ON directories (parent_path);

CREATE TABLE IF NOT EXISTS query_log (
    query_id    TEXT PRIMARY KEY,
    query_text  TEXT NOT NULL,
    agent_id    TEXT,
    l0_results  INTEGER DEFAULT 0,
    l1_expansions INTEGER DEFAULT 0,
    l2_loads    INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    latency_ms  INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

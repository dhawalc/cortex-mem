CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
INSERT INTO schema_version(version, applied_at) VALUES
    (1, '2026-08-23T00:00:00+00:00'),
    (2, '2026-08-23T00:00:00+00:00'),
    (3, '2026-08-23T00:00:00+00:00');

CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE INDEX idx_memories_kind ON memories(kind);
CREATE INDEX idx_memories_scope ON memories(scope);
CREATE INDEX idx_memories_created_at ON memories(created_at DESC);
CREATE VIRTUAL TABLE memories_fts USING fts5(
    id UNINDEXED,
    content,
    tags,
    kind,
    tokenize = 'unicode61'
);

CREATE TABLE recall_receipts (
    receipt_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    receipt_json TEXT NOT NULL
);
CREATE INDEX idx_recall_receipts_created_at
    ON recall_receipts(created_at DESC, receipt_id DESC);

CREATE TABLE vector_profiles (
    profile_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
    created_at TEXT NOT NULL
);
CREATE TABLE embedding_pending (
    profile_key TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_updated_at TEXT NOT NULL,
    enqueued_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    claim_token TEXT,
    claimed_at TEXT,
    PRIMARY KEY(profile_key, record_id),
    FOREIGN KEY(profile_key) REFERENCES vector_profiles(profile_key),
    FOREIGN KEY(record_id) REFERENCES memories(id) ON DELETE CASCADE
);
CREATE INDEX idx_embedding_pending_claim
    ON embedding_pending(profile_key, claimed_at, enqueued_at, record_id);

INSERT INTO memories(
    id, kind, scope, created_at, updated_at, record_json
) VALUES (
    'v3-fixture-record',
    'fact',
    'workspace',
    '2026-08-23T00:00:00+00:00',
    '2026-08-23T00:00:00+00:00',
    '{"id":"v3-fixture-record","kind":"fact","content":"preserved v3 fixture","tags":[],"scope":"workspace","provenance":{"source":"v3-fixture","tier":null,"record_type":null,"details":{}},"created_at":"2026-08-23T00:00:00Z","updated_at":"2026-08-23T00:00:00Z","supersedes":null,"metadata":{}}'
);
INSERT INTO memories_fts(id, content, tags, kind)
VALUES ('v3-fixture-record', 'preserved v3 fixture', '', 'fact');

CREATE TABLE schema_versions (
    id INTEGER PRIMARY KEY,
    version INTEGER UNIQUE NOT NULL,
    applied_at TEXT NOT NULL
);
INSERT INTO schema_versions(version, applied_at)
VALUES (4, '2026-01-01T00:00:00Z'), (49, '2026-08-20T01:20:50Z');

CREATE TABLE sdk_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_session_id TEXT NOT NULL,
    memory_session_id TEXT UNIQUE,
    project TEXT NOT NULL,
    platform_source TEXT NOT NULL DEFAULT 'claude',
    user_prompt TEXT,
    started_at TEXT NOT NULL,
    started_at_epoch INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed'
);

CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    text TEXT,
    type TEXT NOT NULL,
    title TEXT,
    subtitle TEXT,
    facts TEXT,
    narrative TEXT,
    concepts TEXT,
    files_read TEXT,
    files_modified TEXT,
    prompt_number INTEGER,
    discovery_tokens INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL,
    metadata TEXT,
    content_hash TEXT,
    synced_at INTEGER,
    origin_device_id TEXT,
    origin_local_id TEXT,
    sync_rev TEXT NOT NULL DEFAULT '1'
);

CREATE TABLE session_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    request TEXT,
    investigated TEXT,
    learned TEXT,
    completed TEXT,
    next_steps TEXT,
    files_read TEXT,
    files_edited TEXT,
    notes TEXT,
    prompt_number INTEGER,
    discovery_tokens INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL,
    synced_at INTEGER,
    origin_device_id TEXT,
    origin_local_id TEXT,
    sync_rev TEXT NOT NULL DEFAULT '1'
);

INSERT INTO sdk_sessions(
    content_session_id, memory_session_id, project, started_at,
    started_at_epoch, status
) VALUES
    ('content-alpha', 'memory-alpha', '/work/client-alpha',
     '2026-08-18T10:00:00Z', 1787047200000, 'completed'),
    ('content-tools', 'memory-tools', '/archive/client-alpha',
     '2026-08-19T10:00:00Z', 1787133600000, 'completed');

INSERT INTO observations(
    memory_session_id, project, text, type, title, subtitle, facts,
    narrative, concepts, files_read, files_modified, prompt_number,
    created_at, created_at_epoch
) VALUES
    ('memory-alpha', '/work/client-alpha', 'Use SQLite WAL for one backup boundary.',
     'decision', 'Storage decision', 'Keep the system local',
     '["WAL supports concurrent readers", "One file is portable"]',
     'Compared several storage engines.', '["sqlite", "local-first"]',
     '["src/store.ts"]', '["src/store.ts"]', 2,
     '2026-08-18T10:30:00Z', 1787049000000),
    ('memory-tools', '/archive/client-alpha', 'The parser normalizes project paths.',
     'discovery', 'Project path discovery', NULL,
     '["Project basenames can collide"]', 'Inspected imported sessions.',
     '["migration"]', '["src/import.ts"]', '[]', 1,
     '2026-08-19T10:30:00Z', 1787135400000);

INSERT INTO session_summaries(
    memory_session_id, project, request, investigated, learned, completed,
    next_steps, files_read, files_edited, notes, prompt_number, created_at,
    created_at_epoch
) VALUES
    ('memory-alpha', '/work/client-alpha', 'Choose a durable local store.',
     'SQLite and document stores.', 'WAL provides the required concurrency.',
     'Recorded the architecture decision.', 'Add import fixtures.',
     '["src/store.ts"]', '["src/store.ts"]', 'No model calls required.', 2,
     '2026-08-18T11:00:00Z', 1787050800000);

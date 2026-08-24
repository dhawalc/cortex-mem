# Source importers

`cortex-mem import-from` is preview-first. It reads only the selected source,
creates a complete proposal in memory, and does not initialize or modify the AOMS
target unless `--execute` is present. Source files are never changed.

Every adapter implements `SourceAdapter.detect(path)`, `preview(path)`, and
`convert(path)`. The common preview reports source-item and proposed-memory counts,
normalized duplicate groups, possible credential patterns (never their values), the
required scope choice, and workspace mappings. Execution stores the exact preview by
deterministic, content-derived ID, so reruns upsert rather than duplicate records.

Every record carries source file path, source format, import timestamp, and adapter
version in provenance. `workspace` and `user-global` are the only import scopes;
agent-private imports are intentionally unsupported.

## Markdown / Obsidian v1

The adapter accepts one explicitly selected Markdown file or directory. Selecting the
home directory itself is refused. Directories are scanned only for `.md` and
`.markdown` files beneath that selected root.

YAML frontmatter supplies tags, title, kind, and created/updated dates when present.
Obsidian wikilinks and embeds are retained as metadata. Notes over 4,000 characters are
split on headings toward 2,500-character chunks; every chunk records the same
deterministic `parent_note_id`. Decision/ADR headings infer `decision`, learning/lesson
headings infer `pattern`, and ordinary notes infer `fact`.

## claude-mem SQLite v49

This adapter is deliberately narrow. It is pinned to:

- claude-mem `13.15.3`;
- maximum row in `schema_versions` equal to `49`;
- upstream commit `e2d1df569a8f04075d40e92461128ece7cf04c82`
  (2026-08-20); and
- the documented database location `~/.claude-mem/claude-mem.db`.

Research references:

- <https://github.com/thedotmack/claude-mem/blob/e2d1df569a8f04075d40e92461128ece7cf04c82/docs/public/architecture/database.mdx>
- <https://github.com/thedotmack/claude-mem/blob/e2d1df569a8f04075d40e92461128ece7cf04c82/src/services/sqlite/SessionStore.ts>

Only `observations` and `session_summaries` are converted. User prompts are excluded
because they are raw conversation input rather than claude-mem's compressed memory
artifacts. The fixture in `tests/v2/fixtures/importers/claude_mem/schema_v49.sql`
captures the exact columns this adapter reads plus representative v49 sync-era columns.

The upstream database uses `schema_versions`, not SQLite `user_version`. An absent
table, missing required column, or maximum version other than 49 is a hard error with
“Refusing to guess”; no best-effort query is attempted. The database is opened with
SQLite `mode=ro` and `PRAGMA query_only=ON` so WAL-backed source stores remain readable
without importer writes.

Each distinct claude-mem `project` path is shown in the preview. Unless `--workspace`
is supplied, the proposed AOMS ID is `<project-basename>-<path-hash>`, preserving
separation while avoiding collisions between projects with the same basename. Supplying
`--workspace` maps every source project to one confirmed workspace, which provides an
explicit way to repair project fragmentation. `user-global` previews still list each
source project and show that it will cross into the global scope.

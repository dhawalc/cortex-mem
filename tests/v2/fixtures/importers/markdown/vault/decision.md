---
title: Local storage decision
tags: [architecture, local-first]
created: 2026-08-18T10:30:00Z
updated: 2026-08-19T09:00:00Z
---
# Decision

Use SQLite WAL so [[Import Framework|the importer]] and recall share one backup boundary.

The reviewed placeholder is `api_key = "fixture-token-value-123456"` and must be flagged.

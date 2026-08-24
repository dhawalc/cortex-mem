# Relay implementation plan

Use the recalled runtime constraints. Persist first acceptance in SQLite,
order by ingestion sequence, and recursively redact token fields before
serialization. Do not use an in-memory seen-ID set or replacement writes.

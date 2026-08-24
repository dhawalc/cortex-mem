# Independent review

Confirmed INSERT OR IGNORE preserves the original event, sequence ordering is
ingestion-stable, and recursive redaction happens before SQLite persistence.

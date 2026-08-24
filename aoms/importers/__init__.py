"""Versioned source adapters for safe, preview-first brain imports."""

from .base import (
    DuplicateGroup,
    ImportContext,
    ImportPreview,
    ImportResult,
    SecretWarning,
    SourceAdapter,
    run_import,
)
from .claude_mem import (
    CLAUDE_MEM_SCHEMA_VERSION,
    ClaudeMemAdapter,
    ClaudeMemSchemaError,
)
from .markdown import MarkdownObsidianAdapter

__all__ = [
    "CLAUDE_MEM_SCHEMA_VERSION",
    "ClaudeMemAdapter",
    "ClaudeMemSchemaError",
    "DuplicateGroup",
    "ImportContext",
    "ImportPreview",
    "ImportResult",
    "MarkdownObsidianAdapter",
    "SecretWarning",
    "SourceAdapter",
    "run_import",
]

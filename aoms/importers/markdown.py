"""Selected-path Markdown and Obsidian vault importer."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

import yaml

from aoms.contracts import MemoryKind, MemoryRecord, Provenance, Scope

from .base import ImportContext, ImportPreview, analyze_records, content_id

_MARKDOWN_SUFFIXES = {".md", ".markdown"}
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_WIKILINK = re.compile(r"(!)?\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
_DECISION_HEADING = re.compile(
    r"\b(?:decision|decisions|adr|architecture decision|chosen approach)\b", re.I
)
_LEARNING_HEADING = re.compile(
    r"\b(?:learning|learnings|learned|lesson|lessons|takeaway|retrospective)\b",
    re.I,
)


class MarkdownObsidianAdapter:
    """Convert only explicitly selected Markdown files or directories."""

    name = "markdown-obsidian"
    version = "markdown-obsidian-v1"

    def __init__(
        self,
        context: ImportContext,
        *,
        chunk_threshold: int = 4_000,
        chunk_target: int = 2_500,
    ):
        if chunk_threshold < 1 or chunk_target < 1:
            raise ValueError("chunk sizes must be positive")
        self.context = context
        self.chunk_threshold = chunk_threshold
        self.chunk_target = chunk_target

    def detect(self, path: str | Path) -> bool:
        selected = Path(path).expanduser().resolve()
        if selected == Path.home().resolve():
            return False
        if selected.is_file():
            return selected.suffix.casefold() in _MARKDOWN_SUFFIXES
        return selected.is_dir() and any(self._markdown_files(selected))

    def preview(self, path: str | Path) -> ImportPreview:
        selected = self._selected_path(path)
        files = tuple(self._markdown_files(selected))
        if not files:
            raise ValueError(f"no Markdown files found in selected path: {selected}")
        records = tuple(self.convert(selected))
        duplicates, warnings = analyze_records(records)
        workspace = self._workspace_for(selected)
        mapping_target = (
            workspace
            if self.context.scope is Scope.WORKSPACE
            else Scope.USER_GLOBAL.value
        )
        return ImportPreview(
            adapter=self.name,
            adapter_version=self.version,
            source_path=selected,
            source_items=len(files),
            records=records,
            duplicate_groups=duplicates,
            secret_warnings=warnings,
            scope=self.context.scope,
            workspace_mapping={selected.as_posix(): mapping_target},
        )

    def convert(self, path: str | Path) -> Iterator[MemoryRecord]:
        selected = self._selected_path(path)
        workspace_id = self._workspace_for(selected)
        for file_path in self._markdown_files(selected):
            yield from self._convert_file(selected, file_path, workspace_id)

    def _selected_path(self, path: str | Path) -> Path:
        selected = Path(path).expanduser().resolve()
        if selected == Path.home().resolve():
            raise ValueError(
                "refusing to scan the home directory; select a Markdown file or vault "
                "directory explicitly"
            )
        if not selected.exists():
            raise ValueError(f"selected path does not exist: {selected}")
        if selected.is_file() and selected.suffix.casefold() not in _MARKDOWN_SUFFIXES:
            raise ValueError(f"selected file is not Markdown: {selected}")
        if not selected.is_file() and not selected.is_dir():
            raise ValueError(
                f"selected path is not a regular file or directory: {selected}"
            )
        return selected

    @staticmethod
    def _markdown_files(selected: Path) -> Iterator[Path]:
        if selected.is_file():
            if selected.suffix.casefold() in _MARKDOWN_SUFFIXES:
                yield selected
            return
        for candidate in sorted(selected.rglob("*")):
            if (
                candidate.is_file()
                and candidate.suffix.casefold() in _MARKDOWN_SUFFIXES
            ):
                yield candidate

    def _workspace_for(self, selected: Path) -> str | None:
        if self.context.scope is Scope.USER_GLOBAL:
            return None
        if self.context.workspace_id:
            return self.context.workspace_id
        base = selected.stem if selected.is_file() else selected.name
        clean = re.sub(r"[^a-z0-9._-]+", "-", base.casefold()).strip("-.")
        return clean or "imported-markdown"

    def _convert_file(
        self, selected: Path, file_path: Path, workspace_id: str | None
    ) -> Iterator[MemoryRecord]:
        raw = file_path.read_text(encoding="utf-8")
        frontmatter, body = self._parse_frontmatter(raw, file_path)
        body = body.strip()
        if not body:
            return
        source_key = file_path.as_posix()
        title = self._title(frontmatter, body, file_path)
        tags = self._tags(frontmatter)
        created_at = self._frontmatter_time(
            frontmatter, ("created", "created_at", "date")
        ) or datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
        updated_at = (
            self._frontmatter_time(
                frontmatter, ("updated", "updated_at", "modified", "lastmod")
            )
            or created_at
        )
        if updated_at < created_at:
            updated_at = created_at
        wikilink_details = self._wikilinks(body)
        wikilinks = list(dict.fromkeys(item["target"] for item in wikilink_details))
        parent_note_id = content_id(self.version, source_key, body)

        chunks = [body]
        if len(body) > self.chunk_threshold:
            chunks = self._chunks(body)

        for index, chunk in enumerate(chunks, 1):
            heading = self._first_heading(chunk) or title
            kind = self._kind(frontmatter, heading)
            record_id = (
                parent_note_id
                if len(chunks) == 1
                else content_id(self.version, f"{source_key}#chunk-{index}", chunk)
            )
            details: dict[str, Any] = {
                "file_path": file_path.as_posix(),
                "format": "markdown",
                "imported_at": self.context.imported_at.isoformat(),
                "adapter_version": self.version,
                "parent_note_id": parent_note_id,
                "note_title": title,
            }
            metadata: dict[str, Any] = {
                "source_format": "markdown",
                "note_title": title,
                "parent_note_id": parent_note_id,
                "wikilinks": wikilinks,
                "wikilink_details": wikilink_details,
            }
            if len(chunks) > 1:
                details.update(
                    {
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                        "heading": heading,
                    }
                )
                metadata.update(
                    {
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                        "heading": heading,
                    }
                )
            if frontmatter:
                metadata["frontmatter"] = self._json_safe(frontmatter)
            yield MemoryRecord(
                id=record_id,
                kind=kind,
                content=chunk,
                tags=tags,
                scope=self.context.scope,
                scope_workspace_id=workspace_id,
                created_by_agent_id=self.context.actor_id,
                provenance=Provenance(
                    source=file_path.as_posix(),
                    record_type="markdown-note"
                    if len(chunks) == 1
                    else "markdown-chunk",
                    details=details,
                ),
                created_at=created_at,
                updated_at=updated_at,
                metadata=metadata,
            )

    @staticmethod
    def _parse_frontmatter(raw: str, path: Path) -> tuple[dict[str, Any], str]:
        if not raw.startswith("---"):
            return {}, raw
        lines = raw.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            return {}, raw
        closing = next(
            (index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"),
            None,
        )
        if closing is None:
            return {}, raw
        try:
            parsed = yaml.safe_load("".join(lines[1:closing])) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML frontmatter in {path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"frontmatter in {path} must be a mapping")
        return {str(key): value for key, value in parsed.items()}, "".join(
            lines[closing + 1 :]
        )

    @staticmethod
    def _title(frontmatter: dict[str, Any], body: str, path: Path) -> str:
        explicit = frontmatter.get("title")
        if explicit and str(explicit).strip():
            return str(explicit).strip()
        heading = MarkdownObsidianAdapter._first_heading(body)
        return heading or path.stem

    @staticmethod
    def _tags(frontmatter: dict[str, Any]) -> list[str]:
        value = frontmatter.get("tags", [])
        if isinstance(value, str):
            if value.startswith("[") and value.endswith("]"):
                value = value[1:-1]
            return [
                item.strip().lstrip("#") for item in value.split(",") if item.strip()
            ]
        if isinstance(value, (list, tuple, set)):
            return [
                str(item).strip().lstrip("#") for item in value if str(item).strip()
            ]
        return [str(value).strip().lstrip("#")] if value else []

    @staticmethod
    def _frontmatter_time(
        frontmatter: dict[str, Any], keys: tuple[str, ...]
    ) -> datetime | None:
        value = next((frontmatter[key] for key in keys if frontmatter.get(key)), None)
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime.combine(value, time.min)
        else:
            try:
                parsed = datetime.fromisoformat(
                    str(value).strip().replace("Z", "+00:00")
                )
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _wikilinks(body: str) -> list[dict[str, Any]]:
        return [
            {
                "target": match.group(2).strip(),
                "alias": match.group(3).strip() if match.group(3) else None,
                "embedded": bool(match.group(1)),
            }
            for match in _WIKILINK.finditer(body)
        ]

    @staticmethod
    def _kind(frontmatter: dict[str, Any], heading: str) -> MemoryKind:
        explicit = str(frontmatter.get("kind", "")).strip().casefold()
        if explicit:
            try:
                return MemoryKind(explicit)
            except ValueError:
                pass
        if _DECISION_HEADING.search(heading):
            return MemoryKind.DECISION
        if _LEARNING_HEADING.search(heading):
            return MemoryKind.PATTERN
        return MemoryKind.FACT

    @staticmethod
    def _first_heading(body: str) -> str | None:
        match = _HEADING.search(body)
        return match.group(2).strip() if match else None

    def _chunks(self, body: str) -> list[str]:
        matches = list(_HEADING.finditer(body))
        sections: list[str] = []
        if not matches:
            return self._split_oversize(body)
        if body[: matches[0].start()].strip():
            sections.append(body[: matches[0].start()].strip())
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            sections.append(body[match.start() : end].strip())

        chunks: list[str] = []
        pending = ""
        for section in sections:
            if len(section) > self.chunk_target:
                if pending:
                    chunks.append(pending)
                    pending = ""
                chunks.extend(self._split_oversize(section))
            elif not pending:
                pending = section
            elif len(pending) + len(section) + 2 <= self.chunk_target:
                pending += "\n\n" + section
            else:
                chunks.append(pending)
                pending = section
        if pending:
            chunks.append(pending)
        return [chunk for chunk in chunks if chunk.strip()]

    def _split_oversize(self, text: str) -> list[str]:
        paragraphs = [
            part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()
        ]
        chunks: list[str] = []
        pending = ""
        for paragraph in paragraphs:
            pieces = (
                [
                    paragraph[index : index + self.chunk_target]
                    for index in range(0, len(paragraph), self.chunk_target)
                ]
                if len(paragraph) > self.chunk_target
                else [paragraph]
            )
            for piece in pieces:
                if pending and len(pending) + len(piece) + 2 > self.chunk_target:
                    chunks.append(pending)
                    pending = ""
                pending = f"{pending}\n\n{piece}".strip() if pending else piece
        if pending:
            chunks.append(pending)
        return chunks

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): MarkdownObsidianAdapter._json_safe(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [MarkdownObsidianAdapter._json_safe(item) for item in value]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

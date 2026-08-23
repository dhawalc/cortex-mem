"""Write-once relay bundle manifests and independent tamper validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
FORMAT = "aoms-relay-bundle"
FORMAT_VERSION = 1


class BundleValidationError(ValueError):
    """A relay artifact is missing, unexpected, malformed, or modified."""


@dataclass(frozen=True, slots=True)
class BundleValidation:
    valid: bool
    checked_files: int
    failures: tuple[str, ...]

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Hash relative names, file sizes, and bytes for a deterministic tree ID."""

    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def write_manifest(root: Path, *, metadata: dict[str, Any]) -> Path:
    """Seal every existing regular file; the manifest itself is never self-hashed."""

    manifest_path = root / MANIFEST_NAME
    if manifest_path.exists():
        raise FileExistsError(f"relay bundle is already sealed: {manifest_path}")
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise BundleValidationError(f"bundle cannot contain symlink: {path}")
        relative = path.relative_to(root).as_posix()
        files[relative] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
        "files": files,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def validate_bundle(root: str | Path) -> BundleValidation:
    """Validate the manifest, exact file inventory, byte counts, and SHA-256 hashes."""

    bundle = Path(root)
    failures: list[str] = []
    manifest_path = bundle / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return BundleValidation(False, 0, (f"manifest invalid: {exc}",))
    if manifest.get("format") != FORMAT:
        failures.append("manifest format is not an AOMS relay bundle")
    if manifest.get("format_version") != FORMAT_VERSION:
        failures.append(
            f"unsupported manifest version: {manifest.get('format_version')!r}"
        )
    expected = manifest.get("files")
    if not isinstance(expected, dict):
        return BundleValidation(False, 0, tuple(failures + ["manifest files is invalid"]))

    actual_names = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path != manifest_path
    }
    expected_names = set(expected)
    for missing in sorted(expected_names - actual_names):
        failures.append(f"missing bundled file: {missing}")
    for unexpected in sorted(actual_names - expected_names):
        failures.append(f"unexpected bundled file: {unexpected}")
    checked = 0
    for name in sorted(expected_names & actual_names):
        path = bundle / name
        entry = expected[name]
        if path.is_symlink():
            failures.append(f"bundled file became a symlink: {name}")
            continue
        if not isinstance(entry, dict):
            failures.append(f"invalid manifest entry: {name}")
            continue
        checked += 1
        actual_bytes = path.stat().st_size
        if actual_bytes != entry.get("bytes"):
            failures.append(
                f"byte count mismatch for {name}: expected {entry.get('bytes')}, "
                f"got {actual_bytes}"
            )
        actual_hash = sha256_file(path)
        if actual_hash != entry.get("sha256"):
            failures.append(
                f"hash mismatch for {name}: expected {entry.get('sha256')}, "
                f"got {actual_hash}"
            )
    return BundleValidation(not failures, checked, tuple(failures))


__all__ = [
    "BundleValidation",
    "BundleValidationError",
    "validate_bundle",
    "sha256_file",
    "sha256_tree",
    "write_manifest",
]

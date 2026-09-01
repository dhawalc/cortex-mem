"""Environment preflight for the v2 suite (issue #13).

Outside the project virtualenv this suite used to die with a bare
``ModuleNotFoundError`` three imports deep, and an under-pinned ``mcp``
silently discarded token claims instead of failing. Fail here instead,
once, with a message that names the actual environment problem.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys

import pytest

_REQUIRED_MODULES = ("tiktoken", "fastembed", "sqlite_vec", "mcp")
_MCP_MINIMUM = (1, 29)


def _preflight() -> list[str]:
    problems: list[str] = []
    for name in _REQUIRED_MODULES:
        if importlib.util.find_spec(name) is None:
            problems.append(f"missing dependency: {name}")
    if importlib.util.find_spec("mcp") is not None:
        version = importlib.metadata.version("mcp")
        try:
            parts = tuple(int(piece) for piece in version.split(".")[:2])
        except ValueError:
            parts = None
        if parts is not None and parts < _MCP_MINIMUM:
            problems.append(
                f"mcp {version} is below the pyproject pin (>=1.29,<2): "
                "AccessToken has no `claims` field there, so token claims "
                "would be silently dropped"
            )
    return problems


_problems = _preflight()
if _problems:
    pytest.exit(
        "tests/v2 preflight: this interpreter is not provisioned for the "
        "suite\n"
        f"  interpreter: {sys.executable}\n  " + "\n  ".join(_problems) + "\n"
        "  fix: run under the project virtualenv (the environment pyproject "
        "pins), not the ambient interpreter",
        returncode=4,
    )

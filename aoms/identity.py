"""The one place a host's agent identity is decided.

Agent identity is not a label. It selects which ``agent-private`` records a
process can see, so two code paths on the same machine that disagree about the
identity do not raise — they silently read different halves of the store and
the scope-isolation claim quietly stops being true.

Before this module the same host could bind up to four identities depending on
which path the user took: ``setup`` bound the host name, the packaged Claude
Code hook hardcoded ``claude-code``, an unbound CLI fell back to ``cli`` and an
unbound MCP server fell back to ``mcp``. Nothing failed; agent-private scope
just fragmented.

So every transport and every packaged recipe derives its ``AOMS_AGENT_ID`` from
the constants here, and ``tests/v2/test_identity.py`` fails if a recipe, the
``setup`` command or a transport fallback ever drifts from them again.

This module is a leaf on purpose: it imports nothing from ``aoms``, so the CLI,
the MCP adapter and the activation helpers can all depend on it without a
cycle.
"""

from __future__ import annotations

# The hosts ``cortex-mem setup`` supports. The host name *is* the canonical
# agent identity for that host — see ``agent_id_for_host`` — and the packaged
# recipe for each lives in ``HOST_RECIPE_DIRECTORIES`` (aoms/activation.py),
# which is keyed by these same names.
SUPPORTED_HOSTS: tuple[str, ...] = ("claude", "codex", "openclaw")

# The identity a process uses when nothing bound one. Shared by every
# transport so that an unbound CLI and an unbound MCP server on one machine at
# least agree with each other. It is deliberately not a host name: seeing
# ``default`` in a receipt means "no identity was bound", which is a thing an
# operator should be able to notice.
DEFAULT_AGENT_ID = "default"

# OpenClaw's recall hook distinguishes its sub-agents, so it binds
# ``openclaw-<subagent>`` rather than the bare host identity. That is a
# deliberate refinement of the host identity, not a competing one, and the
# prefix is derived from it.
OPENCLAW_SUBAGENT_PREFIX = f"{SUPPORTED_HOSTS[2]}-"


def agent_id_for_host(host: str) -> str:
    """The canonical agent identity for a supported host."""

    normalized = host.casefold()
    if normalized not in SUPPORTED_HOSTS:
        raise ValueError(f"unsupported host: {host}")
    return normalized


def resolved_agent_id(configured: str | None) -> str:
    """Resolve ``AOMS_AGENT_ID`` the same way on every transport."""

    return (configured or "").strip() or DEFAULT_AGENT_ID


__all__ = [
    "DEFAULT_AGENT_ID",
    "OPENCLAW_SUBAGENT_PREFIX",
    "SUPPORTED_HOSTS",
    "agent_id_for_host",
    "resolved_agent_id",
]

"""MCB-1.0 adapter for Letta Code (@letta-ai/letta-code) on the local backend.

The adapter performs only the four framework-neutral MCB operations, driving the
shipped ``letta`` CLI as a subprocess. It contains no case inspection, no
expectation awareness, no prose classification, and no write decision of its
own: every add / replace / delete / no-op decision is made by the Letta Code
agent itself when it processes the observation message.

Durable-state definition (declared before the first case; see README.md)
-----------------------------------------------------------------------
Letta Code's memory is MemFS: a git-backed filesystem projection of the agent's
memory, one repository per agent. This adapter defines the system's durable
state as **the working tree of that repository**, restricted to the single
allowlisted path ``system/mcb-state.md``. ``system/persona.md`` and
``system/human.md`` are excluded: they are the harness's own identity files, not
state under test.

The working tree is the current state and the commit log is its history, so an
obsolete line that is edited away has genuinely ceased to be current -- which is
what SPEC.md requires. ``memory_history`` / ``memory_file_at_ref`` style history
surfaces are never read for scoring. The adapter records, but does not score,
the repository's commit log and dirty flag after each turn, so a reader who
prefers "committed only" semantics can re-derive that reading from the
transcript.

MCB exchanges state as ``{"topic": ..., "text": ...}`` pairs. The file carries
one line per statement::

    TOPIC :: STATEMENT

below a YAML frontmatter fence that MemFS's pre-commit hook requires. The fence
is adapter-owned scaffolding and is never returned as state.

``establish_durable_state`` writes that file and commits it directly. Letta
Code's own system prompt sanctions this path ("Direct file edits (full
control)"); it is an application-layer setup operation under SPEC.md line 124,
not a write decision.

Deserialisation: drop the frontmatter fence; drop blank lines; strip surrounding
whitespace and at most one leading list marker (``-``, ``*``, ``+`` or ``.``);
split on the first occurrence of the separator; left side is the topic, right
side is the text, each stripped. A line without the separator cannot be
expressed as a topic/text pair, so it is surfaced verbatim under a unique
``<unparsed-N>`` topic rather than discarded. Exactly identical pairs are
collapsed; two different texts under one topic are both returned, because that
is the durable state the system actually holds.

If the agent renames or deletes the allowlisted file there is no recovery
branch: the adapter returns an empty state and lets the scorer classify it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable

ADAPTER_INFO = {
    "name": "Letta Code local-backend adapter",
    "system": "@letta-ai/letta-code 0.30.31 (MemFS), --backend local, Ollama models",
    "translation_policy": (
        "durable state is the MemFS working tree at system/mcb-state.md; each "
        "statement is one 'TOPIC :: STATEMENT' line; the Letta Code agent makes "
        "every write decision through its own memory tools"
    ),
    "version": "MCB-1.0-letta-code-1",
}

_LIST_MARKERS = ("- ", "* ", "+ ", ". ")
_FENCE = "---"


def _strip_marker(line: str) -> str:
    stripped = line.strip()
    for marker in _LIST_MARKERS:
        if stripped.startswith(marker):
            return stripped[len(marker) :].strip()
    return stripped


def _strip_frontmatter(text: str) -> list[str]:
    lines = text.splitlines()
    if lines and lines[0].strip() == _FENCE:
        for index in range(1, len(lines)):
            if lines[index].strip() == _FENCE:
                return lines[index + 1 :]
        return []
    return lines


class LettaCodeAdapter:
    def __init__(self, config: dict[str, Any], run_dir: Path):
        self.config = config
        self.run_dir = run_dir.resolve()
        self.case_id = config["case_id"]
        self.separator = config["separator"]
        self.state_path = config["state_file"]
        if self.state_path != "system/mcb-state.md":
            raise ValueError("the allowlisted durable-state path is fixed")
        self.cli = Path(config["cli_path"]).resolve()
        if not self.cli.exists():
            raise RuntimeError(f"letta CLI not found: {self.cli}")
        self.model = config["model_handle"]
        self.turn_timeout = int(config["turn_timeout_seconds"])
        self.cli_timeout = int(config["cli_timeout_seconds"])
        self.settle_seconds = int(config["settle_timeout_seconds"])
        self._events: list[dict[str, Any]] = []
        self._calls = 0

        # Per-case isolation: a private HOME and a private local backend dir, so
        # no case can observe another case's agents, settings or memory.
        self.home = self.run_dir / "home"
        self.state_dir = self.run_dir / "state"
        self.project = self.run_dir / "project"
        for path in (self.home, self.state_dir / "providers", self.project):
            path.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "providers" / "auth.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "providers": {
                        "ollama": {
                            "id": "local-provider-ollama",
                            "name": "ollama",
                            "provider_type": "ollama",
                            "provider_category": "byok",
                            "auth": {"type": "api", "key": "not-needed"},
                        }
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        self.env = self._build_env()
        created = self._cli_json(
            [
                "--backend",
                "local",
                "agents",
                "create",
                "--personality",
                str(config["personality_preset"]),
                "--name",
                f"{config['agent_name_prefix']}-{self.case_id}",
                "--model",
                self.model,
            ],
            timeout=self.cli_timeout,
        )
        self.agent_id = created["id"]
        self.memory_dir = self.state_dir / "memfs" / self.agent_id / "memory"
        if not self.memory_dir.is_dir():
            raise RuntimeError(f"MemFS not projected at {self.memory_dir}")
        self._record("agent_created", agent_id=self.agent_id, system=created.get("system"))
        self._write_persona()
        self.observation: dict[str, Any] | None = None

    # -- environment -----------------------------------------------------

    def _build_env(self) -> dict[str, str]:
        """A scrubbed environment: no inherited credential may reach the CLI."""
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.endswith("_API_KEY")
            and not key.endswith("_TOKEN")
            and key
            not in {
                "ANTHROPIC_AUTH_TOKEN",
                "LETTA_API_KEY",
                "OPENAI_API_KEY",
                "LETTA_AGENT_ID",
                "MEMORY_DIR",
            }
        }
        env.update(
            {
                "HOME": str(self.home),
                "DISABLE_AUTOUPDATER": "1",
                "LETTA_LOCAL_BACKEND_DIR": str(self.state_dir),
                "LETTA_LOCAL_BACKEND_EXPERIMENTAL": "1",
                "OLLAMA_BASE_URL": str(self.config["ollama_base_url"]),
                "CI": "1",
                "NO_COLOR": "1",
            }
        )
        return env

    # -- helpers ---------------------------------------------------------

    def _record(self, event: str, **payload: Any) -> None:
        self._events.append({"event": event, "at": time.time(), **payload})
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "letta-code-transcript.json").write_text(
            json.dumps(self._events, default=str, indent=2) + "\n", encoding="utf-8"
        )

    def _cli(self, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        # The CLI's stdout is truncated at one pipe buffer (8192 bytes) when it
        # is a pipe, because Node exits before the pipe drains. Redirecting to a
        # regular file makes the write synchronous and complete. Measured: the
        # same `agents create` yields 8192 bytes on a pipe and 19114 to a file.
        self._calls += 1
        out_path = self.run_dir / f"cli-{self._calls:03d}.out"
        err_path = self.run_dir / f"cli-{self._calls:03d}.err"
        with out_path.open("wb") as out, err_path.open("wb") as err:
            completed = subprocess.run(
                [str(self.cli), *args],
                cwd=str(self.project),
                env=self.env,
                stdout=out,
                stderr=err,
                stdin=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        return subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            out_path.read_text(encoding="utf-8", errors="replace"),
            err_path.read_text(encoding="utf-8", errors="replace"),
        )

    def _cli_json(self, args: list[str], timeout: int) -> dict[str, Any]:
        completed = self._cli(args, timeout)
        text = completed.stdout.strip()
        start = text.find("{")
        if completed.returncode != 0 and start < 0:
            raise RuntimeError(
                f"letta {' '.join(args)} failed ({completed.returncode}): "
                f"{completed.stderr.strip()[:400]}"
            )
        if start < 0:
            raise RuntimeError(f"letta {' '.join(args)} produced no JSON: {text[:400]}")
        return json.loads(text[start:])

    def _git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.memory_dir), *args],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def _commit(self, message: str) -> None:
        self._git(["add", "-A"])
        self._git(
            [
                "-c",
                "user.name=mcb-harness",
                "-c",
                "user.email=mcb-harness@localhost",
                "commit",
                "-q",
                "-m",
                message,
            ]
        )

    def _serialize(self, unit: dict[str, str]) -> str:
        return f"{unit['topic']}{self.separator}{unit['text']}"

    def _parse(self, lines: Iterable[str]) -> list[dict[str, str]]:
        pairs: list[tuple[str, str]] = []
        unparsed = 0
        for raw in lines:
            line = _strip_marker(raw)
            if not line:
                continue
            if self.separator in line:
                topic, text = line.split(self.separator, 1)
                pairs.append((topic.strip(), text.strip()))
            else:
                unparsed += 1
                pairs.append((f"<unparsed-{unparsed}>", line))
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, str]] = []
        for topic, text in pairs:
            if (topic, text) in seen:
                continue
            seen.add((topic, text))
            unique.append({"topic": topic, "text": text})
        return unique

    def _write_persona(self) -> None:
        persona = self.memory_dir / "system" / "persona.md"
        persona.write_text(
            f"---\ndescription: {json.dumps(self.config['persona_description'])}\n"
            f"---\n{self.config['persona']}\n",
            encoding="utf-8",
        )
        self._commit("setup: install MCB persona")
        self._record("persona_installed", value=persona.read_text(encoding="utf-8"))

    def _memory_status(self) -> dict[str, Any]:
        return self._cli_json(
            ["memory", "status", "--agent", self.agent_id], timeout=self.cli_timeout
        )

    def _git_log(self) -> list[str]:
        completed = self._git(["log", "--oneline"])
        return completed.stdout.strip().splitlines()

    # -- MCB operations --------------------------------------------------

    def establish_durable_state(self, initial_state: list[dict[str, str]]) -> None:
        lines = [self._serialize(unit) for unit in initial_state]
        body = "\n".join(lines)
        document = (
            f"---\ndescription: {json.dumps(self.config['state_description'])}\n---\n"
            f"{body}\n"
            if body
            else f"---\ndescription: {json.dumps(self.config['state_description'])}\n---\n"
        )
        target = self.memory_dir / self.state_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
        self._commit("setup: establish durable state")
        readback = self._parse(_strip_frontmatter(target.read_text(encoding="utf-8")))
        expected = self._parse(lines)
        if readback != expected:
            raise RuntimeError(
                f"durable state read-back mismatch: wrote {expected}, read {readback}"
            )
        self._record("durable_state_established", lines=lines, log=self._git_log())

    def provide_observation(self, observation: dict[str, Any]) -> None:
        self.observation = observation
        self._record("observation_provided", observation=observation)

    def process(self) -> None:
        if self.observation is None:
            raise RuntimeError("no observation was provided")
        lines = [self._serialize(unit) for unit in self.observation["statements"]]
        message = (
            f"{self.observation['text']}\n\n"
            f"{self.config['statement_preamble']}\n" + "\n".join(lines)
        )
        self._record("message_sent", message=message)
        completed = self._cli(
            [
                "--backend",
                "local",
                "-p",
                message,
                "--agent",
                self.agent_id,
                "-m",
                self.model,
                "--yolo",
                "--output-format",
                "json",
            ],
            timeout=self.turn_timeout,
        )
        payload: Any
        try:
            payload = json.loads(completed.stdout[completed.stdout.find("{") :])
        except Exception:
            payload = {"raw_stdout": completed.stdout[-4000:]}
        self._record(
            "agent_processed",
            returncode=completed.returncode,
            response=payload,
            stderr=completed.stderr[-2000:],
        )
        deadline = time.time() + self.settle_seconds
        status = self._memory_status()
        while status.get("dirty") and time.time() < deadline:
            time.sleep(2)
            status = self._memory_status()
        self._record("memory_settled", status=status, log=self._git_log())

    def retrieve_durable_state(self) -> list[dict[str, str]]:
        export_dir = self.run_dir / f"export-{int(time.time() * 1000)}"
        if export_dir.exists():
            shutil.rmtree(export_dir)
        self._cli_json(
            ["memory", "export", "--agent", self.agent_id, "--out", str(export_dir)],
            timeout=self.cli_timeout,
        )
        exported = export_dir / self.state_path
        if not exported.is_file():
            self._record(
                "durable_state_read",
                present=False,
                files=sorted(
                    str(path.relative_to(export_dir))
                    for path in export_dir.rglob("*.md")
                    if ".git" not in path.parts
                ),
            )
            self._record("durable_state_returned", state=[])
            return []
        raw = exported.read_text(encoding="utf-8")
        self._record("durable_state_read", present=True, file_value=raw)
        state = self._parse(_strip_frontmatter(raw))
        self._record("durable_state_returned", state=state)
        return state

    def close(self) -> None:
        self._record("closed", agent_id=self.agent_id, log=self._git_log())


def create(config: dict[str, Any], run_dir: Path) -> LettaCodeAdapter:
    return LettaCodeAdapter(config, run_dir)

"""MCB-1.0 adapter for a locally hosted Letta server.

The adapter performs only the four framework-neutral MCB operations against
Letta's public REST API through the generated ``letta_client`` SDK. It contains
no case inspection, no expectation awareness, no prose classification, and no
write decision of its own: every add / replace / delete / no-op decision is made
by the Letta agent itself when it processes the observation message.

Translation policy (declared before the first run; see README.md)
----------------------------------------------------------------
MCB exchanges state as ``{"topic": ..., "text": ...}`` pairs. Letta has no
native topic key, so each statement is serialised as one line of the form::

    TOPIC :: STATEMENT

Serialisation is used in both directions and is the adapter's entire
representation logic.

* ``durable_state_target = "core_memory_block"`` (primary): the lines live in a
  single core memory block whose label comes from config. The agent edits it
  with the stock ``memory_insert`` / ``memory_replace`` tools.
* ``durable_state_target = "archival_passages"`` (secondary): each line is one
  archival passage. The agent may add passages with ``archival_memory_insert``.

Deserialisation of a block value: split on newlines; drop blank lines; strip
surrounding whitespace and at most one leading list marker (``-``, ``*``, ``+``
or ``•``); split on the first occurrence of the separator; the left side is
the topic and the right side is the text, each stripped. A line that does not
contain the separator cannot be expressed as a topic/text pair, so it is
surfaced verbatim under a unique ``<unparsed-N>`` topic rather than discarded.
Exactly identical pairs are collapsed; two different texts under one topic are
both returned, because that is the durable state the system actually holds.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from letta_client import Letta

ADAPTER_INFO = {
    "name": "Letta local-server adapter",
    "system": "Letta 0.16.8 (letta-client 1.12.1), local Ollama models",
    "translation_policy": (
        "each durable statement is one 'TOPIC :: STATEMENT' line; the Letta "
        "agent makes every write decision through its stock memory tools"
    ),
    "version": "MCB-1.0-letta-1",
}

_LIST_MARKERS = ("- ", "* ", "+ ", "• ")


def _strip_marker(line: str) -> str:
    stripped = line.strip()
    for marker in _LIST_MARKERS:
        if stripped.startswith(marker):
            return stripped[len(marker) :].strip()
    return stripped


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    return value


class LettaAdapter:
    def __init__(self, config: dict[str, Any], run_dir: Path):
        self.config = config
        self.run_dir = run_dir.resolve()
        self.case_id = config["case_id"]
        self.separator = config["separator"]
        self.target = config["durable_state_target"]
        if self.target not in ("core_memory_block", "archival_passages"):
            raise ValueError(f"unknown durable_state_target: {self.target}")
        self.block_label = config["block_label"]
        base_url = config["base_url"]
        if not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("Letta MCB adapter requires a loopback Letta server")
        self.base_url = base_url
        self._events: list[dict[str, Any]] = []
        with urllib.request.urlopen(f"{base_url}/v1/health/", timeout=10) as response:
            health = json.loads(response.read().decode())
        self._record("server_health", health=health)
        self.client = Letta(
            base_url=base_url,
            timeout=float(config["request_timeout_seconds"]),
            max_retries=0,
        )
        memory_blocks = [
            {
                "label": "persona",
                "value": config["persona"],
                "limit": int(config["block_limit"]),
            }
        ]
        if self.target == "core_memory_block":
            memory_blocks.append(
                {
                    "label": self.block_label,
                    "value": "",
                    "limit": int(config["block_limit"]),
                }
            )
        create_kwargs: dict[str, Any] = {
            "name": f"{config['agent_name_prefix']}-{self.case_id}-{int(time.time() * 1000)}",
            "description": f"MCB-1.0 {self.case_id} ({self.target})",
            "model": config["model_handle"],
            "embedding": config["embedding_handle"],
            "include_base_tools": True,
            "enable_sleeptime": bool(config["enable_sleeptime"]),
            "memory_blocks": memory_blocks,
        }
        extra_tools = config.get("extra_tools") or []
        if extra_tools:
            create_kwargs["tools"] = list(extra_tools)
        agent = self.client.agents.create(**create_kwargs)
        self.agent_id = agent.id
        override = config.get("embedding_config_override")
        if override:
            # The stock ollama embedding handle posts to /embeddings, which this
            # Ollama build answers with 404; the probe established that the
            # OpenAI-compatible /v1 route works. Config-supplied, never inferred.
            agent = self.client.agents.update(
                self.agent_id, embedding_config=dict(override)
            )
            self._record(
                "embedding_endpoint_override",
                endpoint=agent.embedding_config.embedding_endpoint,
            )
        self._record(
            "agent_created",
            agent_id=agent.id,
            tools=sorted(tool.name for tool in (agent.tools or [])),
            target=self.target,
        )
        self.observation: dict[str, Any] | None = None

    # -- helpers ---------------------------------------------------------

    def _record(self, event: str, **payload: Any) -> None:
        self._events.append({"event": event, "at": time.time(), **payload})
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "letta-transcript.json").write_text(
            json.dumps(self._events, default=str, indent=2) + "\n", encoding="utf-8"
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

    def _block_value(self) -> str:
        block = self.client.agents.blocks.retrieve(
            self.block_label, agent_id=self.agent_id
        )
        return block.value or ""

    def _passage_texts(self) -> list[str]:
        result = self.client.agents.passages.list(self.agent_id, limit=200)
        items = result.data if hasattr(result, "data") else result
        return [item.text or "" for item in items]

    # -- MCB operations --------------------------------------------------

    def establish_durable_state(self, initial_state: list[dict[str, str]]) -> None:
        lines = [self._serialize(unit) for unit in initial_state]
        if self.target == "core_memory_block":
            self.client.agents.blocks.update(
                self.block_label, agent_id=self.agent_id, value="\n".join(lines)
            )
        else:
            for line in lines:
                self.client.agents.passages.create(self.agent_id, text=line)
        self._record("durable_state_established", lines=lines)

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
        response = self.client.agents.messages.create(
            self.agent_id,
            input=message,
            max_steps=int(self.config["max_steps"]),
        )
        self._record("agent_processed", response=_dump(response))

    def retrieve_durable_state(self) -> list[dict[str, str]]:
        if self.target == "core_memory_block":
            value = self._block_value()
            self._record("durable_state_read", block_value=value)
            state = self._parse(value.splitlines())
        else:
            texts = self._passage_texts()
            self._record("durable_state_read", passages=texts)
            state = self._parse(texts)
        self._record("durable_state_returned", state=state)
        return state

    def close(self) -> None:
        self._record("closed", agent_id=self.agent_id)


def create(config: dict[str, Any], run_dir: Path) -> LettaAdapter:
    return LettaAdapter(config, run_dir)

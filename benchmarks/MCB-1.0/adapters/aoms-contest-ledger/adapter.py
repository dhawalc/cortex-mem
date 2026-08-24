"""MCB-1.0 adapter for the real AOMS application layer, contest-ledger build.

Byte-identical to ``adapters/aoms/adapter.py`` except for one functional
line -- ``claim_key=unit["topic"]`` -- plus the two ADAPTER_INFO strings
that label the artifact. SPEC.md:36-38 sanctions exactly this: "``topic``
is a neutral identity key for the proposition being updated... An adapter
may translate it into a native representation, but must translate it back
losslessly on retrieval." Retrieval is unchanged and still returns the
topic from record content, so the translation is lossless.

No prose is read. ``instruction_markers`` and ``config.json`` are unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aoms.application import AOMSApplication
from aoms.contracts import (
    MemoryKind,
    RememberRequest,
    Scope,
    ScopeContext,
    SupersedeRequest,
)
from aoms.embeddings import NullProvider
from aoms.repositories import SQLiteMemoryRepository

ADAPTER_INFO = {
    "name": "AOMS application-layer reference adapter",
    "system": "AOMS",
    "translation_policy": "explicit instructions declare replacement; otherwise observations append; interchange topic is declared as the native claim slot",
    "version": "MCB-1.0-reference-1-contest-ledger",
}


class AOMSAdapter:
    def __init__(self, config: dict[str, Any], run_dir: Path):
        resolved = run_dir.resolve()
        tmp_root = Path("/tmp").resolve()
        if not resolved.is_relative_to(tmp_root):
            raise ValueError("AOMS MCB adapter requires its scratch store under /tmp")
        self.config = config
        self.run_dir = resolved
        self.repository = SQLiteMemoryRepository(resolved / "aoms.sqlite3")
        self.application = AOMSApplication(
            self.repository,
            scope_context=ScopeContext(
                agent_id=config["agent_id"],
                workspace_id=f"{config['workspace_id_prefix']}-{config['case_id']}",
            ),
            embedding_provider=NullProvider(),
            background_embeddings=False,
        )
        self.observation: dict[str, Any] | None = None
        self._sequence = 0

    def _next_id(self, phase: str) -> str:
        self._sequence += 1
        return f"{self.config['case_id']}-{phase}-{self._sequence:03d}"

    @staticmethod
    def _content(unit: dict[str, str]) -> dict[str, str]:
        return {"topic": unit["topic"], "text": unit["text"]}

    async def _remember(self, unit: dict[str, str], phase: str) -> None:
        await self.application.remember(
            RememberRequest(
                id=self._next_id(phase),
                kind=MemoryKind.FACT,
                content=self._content(unit),
                tags=["mcb-1.0", self.config["case_id"]],
                scope=Scope.WORKSPACE,
                claim_key=unit["topic"],
            )
        )

    async def establish_durable_state(
        self, initial_state: list[dict[str, str]]
    ) -> None:
        for unit in initial_state:
            await self._remember(unit, "initial")

    def provide_observation(self, observation: dict[str, Any]) -> None:
        self.observation = observation

    def _is_explicit_instruction(self, text: str) -> bool:
        folded = text.casefold()
        return any(marker in folded for marker in self.config["instruction_markers"])

    async def _current_records(self) -> list[Any]:
        records = await self.repository.list(
            limit=100, scope_context=self.application.scope_context
        )
        predecessor_ids = {record.supersedes for record in records if record.supersedes}
        return [record for record in records if record.id not in predecessor_ids]

    async def process(self) -> None:
        if self.observation is None:
            raise RuntimeError("no observation was provided")
        explicit = self._is_explicit_instruction(self.observation["text"])
        for unit in self.observation["statements"]:
            current = await self._current_records()
            same_topic = [
                record
                for record in current
                if isinstance(record.content, dict)
                and record.content.get("topic") == unit["topic"]
            ]
            if any(record.content.get("text") == unit["text"] for record in same_topic):
                continue
            if explicit and len(same_topic) == 1:
                await self.application.supersede(
                    same_topic[0].id,
                    SupersedeRequest(
                        id=self._next_id("observation"),
                        content=self._content(unit),
                    ),
                )
            else:
                await self._remember(unit, "observation")

    async def retrieve_durable_state(self) -> list[dict[str, str]]:
        current = await self._current_records()
        units = {
            (record.content["topic"], record.content["text"])
            for record in current
            if isinstance(record.content, dict)
            and set(record.content) == {"topic", "text"}
        }
        return [
            {"topic": topic, "text": text}
            for topic, text in sorted(units, key=lambda item: (item[0], item[1]))
        ]

    def close(self) -> None:
        return None


def create(config: dict[str, Any], run_dir: Path) -> AOMSAdapter:
    return AOMSAdapter(config, run_dir)

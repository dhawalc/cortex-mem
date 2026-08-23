"""Embedding provider boundary for AOMS v2.

The zero-configuration default is FastEmbed with ``BAAI/bge-small-en-v1.5``
(384 dimensions). FastEmbed runs an ONNX model locally and avoids PyTorch;
the model is small enough for a first-run download of roughly 67 MB while
providing real sentence-level semantic retrieval. ``sentence-transformers``
was rejected as the default because its PyTorch runtime is several times
heavier. A hashing/BM25 fallback is cheap but duplicates FTS rather than adding
semantic evidence, so unavailable embeddings degrade to FTS instead of
pretending lexical hashes are semantic vectors.

The optional Ollama provider defaults to the legacy ``nomic-embed-text`` model
and its 768 dimensions. Those vectors are dimension-compatible with the old
Chroma collection only when the exact Ollama model build and preprocessing are
the same. The FastEmbed default is 384-dimensional and therefore cannot reuse
legacy vectors. Chroma vectors are not read in place by v2 in either case;
they must be explicitly migrated, and re-embedding is preferred when recovered
records have different IDs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from aoms.contracts import MemoryRecord

DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_FASTEMBED_DIMENSIONS = 384
DEFAULT_OLLAMA_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA_DIMENSIONS = 768
DEFAULT_OLLAMA_URL = "http://localhost:11434"

EmbeddingVector = list[float]


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    """Identity required to keep vectors from incompatible models separate."""

    provider: str
    model: str
    dimensions: int

    def __post_init__(self) -> None:
        if not self.provider or not self.model:
            raise ValueError("embedding provider and model must not be empty")
        if self.dimensions < 1:
            raise ValueError("embedding dimensions must be positive")

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}@{self.dimensions}"


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Batch-oriented provider used by write workers and query recall."""

    profile: EmbeddingProfile | None

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> list[EmbeddingVector | None]: ...

    async def embed_query(self, text: str) -> EmbeddingVector | None: ...


class NullProvider:
    """Network-free disabled provider for tests and explicitly lexical setups."""

    profile: EmbeddingProfile | None = None

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> list[EmbeddingVector | None]:
        return [None for _ in texts]

    async def embed_query(self, text: str) -> EmbeddingVector | None:
        return None


class FastEmbedProvider:
    """Lazy, local ONNX embeddings; model loading never happens at import time."""

    def __init__(
        self,
        model: str = DEFAULT_FASTEMBED_MODEL,
        *,
        dimensions: int = DEFAULT_FASTEMBED_DIMENSIONS,
        cache_dir: str | None = None,
        batch_size: int = 64,
    ):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.profile = EmbeddingProfile("fastembed", model, dimensions)
        self.cache_dir = cache_dir
        self.batch_size = batch_size
        self._model: object | None = None
        self._model_lock = asyncio.Lock()

    async def _get_model(self) -> object:
        if self._model is None:
            async with self._model_lock:
                if self._model is None:
                    self._model = await asyncio.to_thread(self._load_model)
        return self._model

    def _load_model(self) -> object:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - dependency failure path
            raise RuntimeError(
                "FastEmbed is unavailable; install the fastembed dependency or "
                "select AOMS_EMBEDDING_PROVIDER=none"
            ) from exc
        options = {"model_name": self.profile.model}
        if self.cache_dir is not None:
            options["cache_dir"] = self.cache_dir
        return TextEmbedding(**options)

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> list[EmbeddingVector | None]:
        materialized = list(texts)
        if not materialized:
            return []
        model = await self._get_model()
        vectors = await asyncio.to_thread(
            lambda: list(model.passage_embed(materialized, batch_size=self.batch_size))
        )
        return [self._validate(vector.tolist()) for vector in vectors]

    async def embed_query(self, text: str) -> EmbeddingVector | None:
        model = await self._get_model()
        vectors = await asyncio.to_thread(lambda: list(model.query_embed([text])))
        if not vectors:
            return None
        return self._validate(vectors[0].tolist())

    def _validate(self, vector: Sequence[float]) -> EmbeddingVector:
        result = [float(value) for value in vector]
        if len(result) != self.profile.dimensions:
            raise ValueError(
                f"{self.profile.model} returned {len(result)} dimensions; "
                f"configured profile expects {self.profile.dimensions}"
            )
        return result


class OllamaProvider:
    """Optional local Ollama provider using the current batch embed endpoint."""

    def __init__(
        self,
        model: str = DEFAULT_OLLAMA_MODEL,
        *,
        dimensions: int = DEFAULT_OLLAMA_DIMENSIONS,
        base_url: str = DEFAULT_OLLAMA_URL,
        timeout_seconds: float = 30.0,
    ):
        self.profile = EmbeddingProfile("ollama", model, dimensions)
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> list[EmbeddingVector | None]:
        materialized = list(texts)
        if not materialized:
            return []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.profile.model, "input": materialized},
            )
            if response.status_code in {404, 405}:
                return await self._embed_with_legacy_endpoint(client, materialized)
            response.raise_for_status()
        payload = response.json()
        vectors = payload.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(materialized):
            raise RuntimeError("Ollama returned an invalid embedding batch")
        return [self._validate(vector) for vector in vectors]

    async def _embed_with_legacy_endpoint(
        self, client: httpx.AsyncClient, texts: Sequence[str]
    ) -> list[EmbeddingVector | None]:
        """Support Ollama releases exposing the endpoint used by legacy AOMS."""

        responses = await asyncio.gather(
            *[
                client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.profile.model, "prompt": text},
                )
                for text in texts
            ]
        )
        vectors: list[EmbeddingVector | None] = []
        for response in responses:
            response.raise_for_status()
            vector = response.json().get("embedding")
            if not isinstance(vector, list):
                raise TypeError("Ollama returned an invalid legacy embedding")
            vectors.append(self._validate(vector))
        return vectors

    async def embed_query(self, text: str) -> EmbeddingVector | None:
        return (await self.embed_documents([text]))[0]

    def _validate(self, vector: Sequence[float]) -> EmbeddingVector:
        result = [float(value) for value in vector]
        if len(result) != self.profile.dimensions:
            raise ValueError(
                f"Ollama {self.profile.model} returned {len(result)} dimensions; "
                f"configured profile expects {self.profile.dimensions}"
            )
        return result


def provider_from_config(config: Mapping[str, str]) -> EmbeddingProvider:
    """Resolve the provider from portable AOMS environment-style settings."""

    provider = config.get("AOMS_EMBEDDING_PROVIDER", "fastembed").strip().casefold()
    if provider in {"none", "null", "disabled"}:
        return NullProvider()
    if provider == "fastembed":
        return FastEmbedProvider(
            config.get("AOMS_EMBEDDING_MODEL", DEFAULT_FASTEMBED_MODEL),
            dimensions=int(
                config.get("AOMS_EMBEDDING_DIMENSIONS", DEFAULT_FASTEMBED_DIMENSIONS)
            ),
            cache_dir=config.get("AOMS_EMBEDDING_CACHE_DIR"),
        )
    if provider == "ollama":
        return OllamaProvider(
            config.get("AOMS_EMBEDDING_MODEL", DEFAULT_OLLAMA_MODEL),
            dimensions=int(
                config.get("AOMS_EMBEDDING_DIMENSIONS", DEFAULT_OLLAMA_DIMENSIONS)
            ),
            base_url=config.get("AOMS_OLLAMA_URL", DEFAULT_OLLAMA_URL),
        )
    raise ValueError("AOMS_EMBEDDING_PROVIDER must be one of: fastembed, ollama, none")


def text_for_embedding(record: MemoryRecord, *, max_characters: int = 12_000) -> str:
    """Render stable semantic content while bounding provider input memory."""

    content = (
        record.content
        if isinstance(record.content, str)
        else json.dumps(record.content, ensure_ascii=False, sort_keys=True)
    )
    parts = [record.kind.value, content]
    if record.tags:
        parts.append("tags: " + " ".join(record.tags))
    return "\n".join(parts)[:max_characters]


__all__ = [
    "DEFAULT_FASTEMBED_DIMENSIONS",
    "DEFAULT_FASTEMBED_MODEL",
    "DEFAULT_OLLAMA_DIMENSIONS",
    "DEFAULT_OLLAMA_MODEL",
    "EmbeddingProfile",
    "EmbeddingProvider",
    "EmbeddingVector",
    "FastEmbedProvider",
    "NullProvider",
    "OllamaProvider",
    "provider_from_config",
    "text_for_embedding",
]

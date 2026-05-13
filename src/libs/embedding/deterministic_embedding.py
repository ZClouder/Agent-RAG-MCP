"""Deterministic local embedding provider for tests and offline demos."""

from __future__ import annotations

import hashlib
from typing import Any, List, Optional

from src.libs.embedding.base_embedding import BaseEmbedding


class DeterministicEmbedding(BaseEmbedding):
    """Generate stable pseudo-embeddings without network access.

    This provider is selected explicitly with ``embedding.provider:
    deterministic``. It is intended for CI, local tests, and offline demo flows
    where repeatability matters more than semantic quality.
    """

    def __init__(self, settings: Any, **_: Any) -> None:
        self.settings = settings
        self.dimensions = int(getattr(settings.embedding, "dimensions", 1536))

    def embed(
        self,
        texts: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        self.validate_texts(texts)
        dimensions = int(kwargs.get("dimensions", self.dimensions))
        vectors = [self._embed_one(text, dimensions) for text in texts]

        if trace is not None:
            trace.record_stage(
                "embedding",
                {
                    "provider": "deterministic",
                    "text_count": len(texts),
                    "dimensions": dimensions,
                },
            )

        return vectors

    def get_dimension(self) -> int:
        return self.dimensions

    @staticmethod
    def _embed_one(text: str, dimensions: int) -> List[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        counter = 0

        while len(values) < dimensions:
            block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            values.extend((byte / 127.5) - 1.0 for byte in block)
            counter += 1

        return values[:dimensions]

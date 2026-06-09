"""Deterministic local semantic embeddings and repository search."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Dict, List, Tuple

from shared.repository_schema import RepositoryState


class EmbeddingEngine:
    """Hashing-vector embeddings with no network or model dependency."""

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def build(self, state: RepositoryState) -> RepositoryState:
        for path, file_info in state.files.items():
            text = self._file_text(state, path)
            state.embeddings[f"file:{path}"] = self.embed_text(text)
        for fn in state.functions.values():
            state.embeddings[fn.id] = self.embed_text(self._symbol_text(fn.name, fn.source, fn.calls))
        state.metadata["embedding_dimensions"] = self.dimensions
        state.metadata["embedding_strategy"] = "deterministic_hashing_vector"
        return state

    def search(self, state: RepositoryState, query: str, limit: int = 8) -> List[Tuple[str, float]]:
        query_vector = self.embed_text(query)
        scored = []
        for node_id, vector in state.embeddings.items():
            score = self.cosine(query_vector, vector)
            if score > 0:
                scored.append((node_id, score))
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:limit]

    def embed_text(self, text: str) -> List[float]:
        vector = [0.0] * self.dimensions
        tokens = self._tokenize(text)
        counts = Counter(tokens)
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def cosine(self, left: List[float], right: List[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return sum(a * b for a, b in zip(left, right))

    def _file_text(self, state: RepositoryState, path: str) -> str:
        file_info = state.files[path]
        imports = " ".join(imp.module for imp in file_info.imports)
        functions = " ".join(state.functions[fn].name for fn in file_info.functions if fn in state.functions)
        classes = " ".join(state.classes[cls].name for cls in file_info.classes if cls in state.classes)
        calls = " ".join(file_info.calls)
        return f"{path} {file_info.language} {imports} {functions} {classes} {calls}"

    def _symbol_text(self, name: str, source: str, calls: List[str]) -> str:
        return f"{name} {' '.join(calls)} {source}"

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", text.lower())

"""テスト専用の決定論的 Embedder。ネットワーク・モデルダウンロードを一切使わない。

既知の文字列には明示的なベクトルを割り当てられるようにし（意図した順位を検証するため）、
未知の文字列にはハッシュから決定論的に生成したベクトルをフォールバックとして与える。
"""

from __future__ import annotations

import hashlib

import numpy as np


class FakeEmbedder:
    model_name = "fake-embedder"
    dim = 8

    def __init__(self, known: dict[str, list[float]] | None = None) -> None:
        self.known = known or {}

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.array([self._vec(t) for t in texts], dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)

    def _vec(self, text: str) -> np.ndarray:
        if text in self.known:
            vec = np.array(self.known[text], dtype=np.float32)
        else:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vec = np.frombuffer(digest[: self.dim * 4], dtype=np.uint32).astype(np.float32)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

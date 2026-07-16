"""RecallService: Store と Embedder を束ね、MCP/CLI から呼ばれるユースケースを提供する。

server.py と cli.py は本モジュールを呼ぶだけの薄いラッパに留める。
テストでは Store(:memory:) + FakeEmbedder を注入することで、
SQLite・ONNX という2つの揮発的依存を排してドメインロジックだけを検証できる。
"""
from __future__ import annotations

from dataclasses import dataclass

from recall.embedder import Embedder
from recall.search import cosine_topk
from recall.store import Store

SNIPPET_LEN = 200


@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    project: str
    source_file: str
    timestamp: str
    snippet: str


class RecallService:
    def __init__(self, store: Store, embedder: Embedder) -> None:
        self._store = store
        self._embedder = embedder

    def search(self, query: str, project: str | None = None, limit: int = 5) -> list[SearchHit]:
        """本文全体を含まない軽量な SearchHit を返す（受動トークンコストを抑えるため）。"""
        query_vec = self._embedder.embed_query(query)
        ids, matrix = self._store.load_all_vectors(project=project)
        scored = cosine_topk(matrix, ids, query_vec, limit)

        hits = []
        for s in scored:
            chunk = self._store.get_chunk(s.id)
            if chunk is None:  # 検索後に削除された等のレースは無視して結果から除く
                continue
            hits.append(
                SearchHit(
                    id=chunk["id"],
                    score=s.score,
                    project=chunk["project"],
                    source_file=chunk["source_file"],
                    timestamp=chunk["timestamp"],
                    snippet=chunk["text"][:SNIPPET_LEN],
                )
            )
        return hits

    def get(self, chunk_id: str) -> dict | None:
        """本文全体+メタデータを返す。Claude が memory_search の結果から明示的に呼ぶ想定。"""
        return self._store.get_chunk(chunk_id)

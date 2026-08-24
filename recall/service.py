"""RecallService: Store と Embedder を束ね、MCP/CLI から呼ばれるユースケースを提供する。

server.py と cli.py は本モジュールを呼ぶだけの薄いラッパに留める。
テストでは Store(:memory:) + FakeEmbedder を注入することで、
SQLite・ONNX という2つの揮発的依存を排してドメインロジックだけを検証できる。
"""

from __future__ import annotations

from dataclasses import dataclass

from recall.embedder import Embedder
from recall.search import build_fts_query, cosine_topk, rrf_merge
from recall.store import Store

SNIPPET_LEN = 200


@dataclass(frozen=True)
class SearchHit:
    """score は cosine 類似度（ハイブリッド時も同様。統合順位のみ RRF が決める）。

    ベクトル候補プール外のヒットは cosine スコアが無く score が既定の 0.0 になる
    （低関連度の意味ではない。結果の関連度は順位で判断すること）。
    """

    id: str
    score: float
    project: str
    source_file: str
    timestamp: str
    snippet: str


class RecallService:
    def __init__(self, store: Store, embedder: Embedder, hybrid_search: bool = True) -> None:
        self._store = store
        self._embedder = embedder
        self._hybrid_search = hybrid_search

    def search(self, query: str, project: str | None = None, limit: int = 5) -> list[SearchHit]:
        """本文全体を含まない軽量な SearchHit を返す（受動トークンコストを抑えるため）。

        hybrid_search=True の場合、cosine ベクトル検索と FTS5 キーワード検索
        (store.keyword_topk) の順位を RRF (rrf_merge) で統合する。キーワード側が
        空（fts_enabled=False への劣化・空クエリ・不一致のいずれか）の場合は
        従来どおり cosine 順そのままになる（hybrid_search=False と完全に同一の
        結果になることをテストで固定している）。
        """
        query_vec = self._embedder.embed_query(query)
        ids, matrix = self._store.load_all_vectors(project=project)
        # ハイブリッド時は統合後に上位 limit 件を選び直す余地を残すため、
        # limit の2倍を候補プールとして確保する（非ハイブリッド時は limit そのもの
        # にすることで、cosine_topk(matrix, ids, query_vec, limit) 直呼びと
        # 完全に同一の結果になる）。
        pool_size = limit * 2 if self._hybrid_search else limit
        vector_scored = cosine_topk(matrix, ids, query_vec, pool_size)
        vector_ranking = [s.id for s in vector_scored]
        cosine_by_id = {s.id: s.score for s in vector_scored}

        keyword_ranking: list[str] = []
        if self._hybrid_search:
            fts_query = build_fts_query(query)
            keyword_ranking = [
                chunk_id
                for chunk_id, _score in self._store.keyword_topk(
                    fts_query, pool_size, project=project
                )
            ]

        if keyword_ranking:
            merged_ids = rrf_merge([vector_ranking, keyword_ranking], limit=limit)
        else:
            merged_ids = vector_ranking[:limit]

        hits = []
        for chunk_id in merged_ids:
            chunk = self._store.get_chunk(chunk_id)
            if chunk is None:  # 検索後に削除された等のレースは無視して結果から除く
                continue
            hits.append(
                SearchHit(
                    id=chunk["id"],
                    score=cosine_by_id.get(chunk_id, 0.0),
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

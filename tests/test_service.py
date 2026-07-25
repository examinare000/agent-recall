"""RecallService: Store+Embedder を束ねた search()/get() の単体テスト。FakeEmbedder使用。"""
from __future__ import annotations

import pytest

from recall.chunker import Chunk
from recall.service import RecallService
from recall.store import Store
from tests.fakes import FakeEmbedder


def _chunk(id_, source_file, project, text):
    return Chunk(
        id=id_, source_file=source_file, project=project,
        branch="main", timestamp="2026-01-01T00:00:00Z", text=text,
    )


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


class TestSearch:
    def test_ranks_semantically_closest_chunk_first(self, store):
        embedder = FakeEmbedder(known={
            "テストの書き方": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "ペットの飼い方": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        })
        chunks = [
            _chunk("a#0", "a.jsonl", "proj", "テストの書き方"),
            _chunk("b#0", "b.jsonl", "proj", "ペットの飼い方"),
        ]
        store.upsert_chunks(chunks, embedder.embed_documents([c.text for c in chunks]))
        service = RecallService(store, embedder)

        hits = service.search("テストの書き方")

        assert hits[0].id == "a#0"
        assert hits[0].score > hits[1].score

    def test_filters_by_project(self, store):
        embedder = FakeEmbedder()
        chunks = [
            _chunk("a#0", "a.jsonl", "proj-a", "本文A"),
            _chunk("b#0", "b.jsonl", "proj-b", "本文B"),
        ]
        store.upsert_chunks(chunks, embedder.embed_documents([c.text for c in chunks]))
        service = RecallService(store, embedder)

        hits = service.search("本文", project="proj-b")

        assert [h.id for h in hits] == ["b#0"]

    def test_respects_limit(self, store):
        embedder = FakeEmbedder()
        chunks = [_chunk(f"c{i}#0", f"c{i}.jsonl", "proj", f"本文{i}") for i in range(5)]
        store.upsert_chunks(chunks, embedder.embed_documents([c.text for c in chunks]))
        service = RecallService(store, embedder)

        hits = service.search("本文", limit=2)

        assert len(hits) == 2

    def test_snippet_is_truncated_and_full_text_is_not_returned(self, store):
        embedder = FakeEmbedder()
        long_text = "あ" * 500
        chunks = [_chunk("a#0", "a.jsonl", "proj", long_text)]
        store.upsert_chunks(chunks, embedder.embed_documents([c.text for c in chunks]))
        service = RecallService(store, embedder)

        hits = service.search("あ")

        assert len(hits[0].snippet) == 200
        assert not hasattr(hits[0], "text")


class TestHybridSearch:
    """search() のハイブリッド検索(ベクトル+FTS5キーワードのRRF併用)を検証する。

    このテストクラスの store fixture は Store(":memory:") であり、
    test_store.py の test_fts_enabled_is_true_on_this_sqlite_build が示すとおり
    この実行環境では fts5+trigram が有効なため、実際の chunks_fts を使って検証できる。
    """

    def test_keyword_match_promotes_vocabulary_mismatched_chunk_to_top(self, store):
        # ベクトル類似度だけで見ると "b#0" が1位になるよう既知ベクトルを仕込みつつ、
        # クエリ語 "E1234" を本文に含む "a#0" だけがキーワード側でも一致することで、
        # RRF統合後は両方のランキングに顔を出す a#0 が単独1位の b#0 を上回ることを検証する。
        embedder = FakeEmbedder(known={
            "E1234": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "汎用的な内容の文章です": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "E1234 エラーコードの対処法": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        })
        chunks = [
            _chunk("b#0", "b.jsonl", "proj", "汎用的な内容の文章です"),
            _chunk("a#0", "a.jsonl", "proj", "E1234 エラーコードの対処法"),
        ]
        store.upsert_chunks(chunks, embedder.embed_documents([c.text for c in chunks]))
        # hybrid_search 引数を明示しないことで既定値 True も併せて検証する。
        service = RecallService(store, embedder)

        hits = service.search("E1234", limit=1)

        assert [h.id for h in hits] == ["a#0"]

    def test_falls_back_to_vector_only_ranking_when_fts_disabled(self, store):
        embedder = FakeEmbedder(known={
            "E1234": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "汎用的な内容の文章です": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "E1234 エラーコードの対処法": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        })
        chunks = [
            _chunk("b#0", "b.jsonl", "proj", "汎用的な内容の文章です"),
            _chunk("a#0", "a.jsonl", "proj", "E1234 エラーコードの対処法"),
        ]
        store.upsert_chunks(chunks, embedder.embed_documents([c.text for c in chunks]))
        store.fts_enabled = False  # fts5/trigram 非対応環境の劣化パスを強制する
        hybrid_service = RecallService(store, embedder, hybrid_search=True)
        vector_only_service = RecallService(store, embedder, hybrid_search=False)

        hybrid_hits = hybrid_service.search("E1234", limit=1)
        vector_only_hits = vector_only_service.search("E1234", limit=1)

        assert [h.id for h in hybrid_hits] == [h.id for h in vector_only_hits] == ["b#0"]
        assert hybrid_hits[0].score == vector_only_hits[0].score

    def test_hybrid_search_false_matches_traditional_vector_only_ranking(self, store):
        embedder = FakeEmbedder(known={
            "E1234": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "汎用的な内容の文章です": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "E1234 エラーコードの対処法": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        })
        chunks = [
            _chunk("b#0", "b.jsonl", "proj", "汎用的な内容の文章です"),
            _chunk("a#0", "a.jsonl", "proj", "E1234 エラーコードの対処法"),
        ]
        store.upsert_chunks(chunks, embedder.embed_documents([c.text for c in chunks]))
        service = RecallService(store, embedder, hybrid_search=False)

        # fts は有効(store.fts_enabled のまま)だが hybrid_search=False なので
        # キーワード一致の a#0 は昇格せず、cosine 順そのまま b#0 が1位のまま。
        hits = service.search("E1234", limit=1)

        assert [h.id for h in hits] == ["b#0"]

    def test_project_filter_applies_to_both_vector_and_keyword_candidates(self, store):
        embedder = FakeEmbedder()
        chunks = [
            _chunk("a1", "a.jsonl", "proj-a", "ZZZKW に関する文書A"),
            _chunk("b1", "b.jsonl", "proj-b", "ZZZKW に関する文書B"),
        ]
        store.upsert_chunks(chunks, embedder.embed_documents([c.text for c in chunks]))
        service = RecallService(store, embedder, hybrid_search=True)

        hits = service.search("ZZZKW", project="proj-a", limit=5)

        assert [h.id for h in hits] == ["a1"]

    def test_keyword_only_hit_outside_vector_pool_gets_zero_score(self, store):
        # pool_size = limit*2 = 4 の外側(5件中コサイン最下位)に締め出された
        # チャンクが、キーワード一致のみで結果に混ざり込むケース。ベクトル候補に
        # 一度も現れないため、score には cosine 由来の値が無く 0.0 になることを検証する。
        embedder = FakeEmbedder(known={
            "KEYWORDXYZ": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "vec1文書": [8.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "vec2文書": [4.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "vec3文書": [2.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "vec4文書": [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "KEYWORDXYZ に関する文書": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        })
        chunks = [
            _chunk("a1", "a.jsonl", "proj", "vec1文書"),
            _chunk("a2", "a.jsonl", "proj", "vec2文書"),
            _chunk("a3", "a.jsonl", "proj", "vec3文書"),
            _chunk("a4", "a.jsonl", "proj", "vec4文書"),
            _chunk("a5", "a.jsonl", "proj", "KEYWORDXYZ に関する文書"),
        ]
        store.upsert_chunks(chunks, embedder.embed_documents([c.text for c in chunks]))
        service = RecallService(store, embedder, hybrid_search=True)

        hits = service.search("KEYWORDXYZ", limit=2)

        assert [h.id for h in hits] == ["a1", "a5"]
        assert hits[0].score > 0.0
        assert hits[1].score == 0.0


class TestGet:
    def test_returns_full_chunk_with_metadata(self, store):
        embedder = FakeEmbedder()
        chunk = _chunk("a#0", "a.jsonl", "proj", "本文全体")
        store.upsert_chunks([chunk], embedder.embed_documents([chunk.text]))
        service = RecallService(store, embedder)

        got = service.get("a#0")

        assert got["id"] == "a#0"
        assert got["text"] == "本文全体"

    def test_returns_none_for_unknown_id(self, store):
        service = RecallService(store, FakeEmbedder())
        assert service.get("nope") is None

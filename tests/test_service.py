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

"""Store の往復（insert/read/delete）と file_state/meta の単体テスト。:memory: SQLite のみ使用。"""
from __future__ import annotations

import numpy as np
import pytest

from recall.chunker import Chunk
from recall.store import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _chunk(id_="a.jsonl#0", source_file="a.jsonl", project="proj", text="本文"):
    return Chunk(
        id=id_,
        source_file=source_file,
        project=project,
        branch="main",
        timestamp="2026-01-01T00:00:00Z",
        text=text,
    )


class TestChunkRoundTrip:
    def test_insert_then_read_restores_float32_vector_with_matching_dim(self, store):
        chunk = _chunk()
        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        store.upsert_chunks([chunk], np.array([vec]))

        ids, matrix = store.load_all_vectors()

        assert ids == ["a.jsonl#0"]
        assert matrix.dtype == np.float32
        assert matrix.shape == (1, 4)
        np.testing.assert_allclose(matrix[0], vec)

    def test_get_chunk_returns_text_and_metadata(self, store):
        chunk = _chunk(text="質問\n\n---\n\n応答")
        store.upsert_chunks([chunk], np.array([[0.1, 0.2]], dtype=np.float32))

        got = store.get_chunk("a.jsonl#0")

        assert got["id"] == "a.jsonl#0"
        assert got["source_file"] == "a.jsonl"
        assert got["project"] == "proj"
        assert got["branch"] == "main"
        assert got["timestamp"] == "2026-01-01T00:00:00Z"
        assert got["text"] == "質問\n\n---\n\n応答"

    def test_get_chunk_returns_none_for_unknown_id(self, store):
        assert store.get_chunk("does-not-exist") is None

    def test_upsert_replaces_existing_row_with_same_id(self, store):
        store.upsert_chunks([_chunk(text="旧")], np.array([[0.1, 0.2]], dtype=np.float32))
        store.upsert_chunks([_chunk(text="新")], np.array([[0.9, 0.9]], dtype=np.float32))

        ids, matrix = store.load_all_vectors()

        assert ids == ["a.jsonl#0"]
        assert store.get_chunk("a.jsonl#0")["text"] == "新"
        np.testing.assert_allclose(matrix[0], [0.9, 0.9])

    def test_load_all_vectors_filters_by_project_when_given(self, store):
        store.upsert_chunks(
            [_chunk(id_="a.jsonl#0", source_file="a.jsonl", project="proj-a"),
             _chunk(id_="b.jsonl#0", source_file="b.jsonl", project="proj-b")],
            np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
        )

        ids, matrix = store.load_all_vectors(project="proj-b")

        assert ids == ["b.jsonl#0"]
        assert matrix.shape == (1, 2)

    def test_delete_by_source_file_removes_its_chunks_only(self, store):
        store.upsert_chunks(
            [_chunk(id_="a.jsonl#0", source_file="a.jsonl"),
             _chunk(id_="b.jsonl#0", source_file="b.jsonl")],
            np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
        )

        store.delete_by_source_file("a.jsonl")

        ids, _ = store.load_all_vectors()
        assert ids == ["b.jsonl#0"]


class TestFileState:
    def test_get_file_state_returns_none_when_absent(self, store):
        assert store.get_file_state("a.jsonl") is None

    def test_set_then_get_file_state_round_trips(self, store):
        store.set_file_state("a.jsonl", mtime=123.456, size=789, model="fake-model")

        state = store.get_file_state("a.jsonl")

        assert state == {"mtime": 123.456, "size": 789, "model": "fake-model"}

    def test_set_file_state_upserts_existing_entry(self, store):
        store.set_file_state("a.jsonl", mtime=1.0, size=10, model="fake-model")
        store.set_file_state("a.jsonl", mtime=2.0, size=20, model="fake-model")

        assert store.get_file_state("a.jsonl") == {"mtime": 2.0, "size": 20, "model": "fake-model"}


class TestPrune:
    def test_prune_missing_removes_chunks_and_file_state_not_in_set(self, store):
        store.upsert_chunks(
            [_chunk(id_="a.jsonl#0", source_file="a.jsonl"),
             _chunk(id_="b.jsonl#0", source_file="b.jsonl")],
            np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
        )
        store.set_file_state("a.jsonl", mtime=1.0, size=1, model="m")
        store.set_file_state("b.jsonl", mtime=1.0, size=1, model="m")

        pruned = store.prune_missing({"b.jsonl"})

        assert pruned == 1
        ids, _ = store.load_all_vectors()
        assert ids == ["b.jsonl#0"]
        assert store.get_file_state("a.jsonl") is None
        assert store.get_file_state("b.jsonl") is not None

    def test_prune_missing_returns_zero_when_nothing_stale(self, store):
        store.set_file_state("a.jsonl", mtime=1.0, size=1, model="m")
        assert store.prune_missing({"a.jsonl"}) == 0


class TestClearAll:
    def test_clear_all_removes_chunks_and_file_state(self, store):
        store.upsert_chunks([_chunk()], np.array([[0.1, 0.2]], dtype=np.float32))
        store.set_file_state("a.jsonl", mtime=1.0, size=1, model="m")

        store.clear_all()

        ids, _ = store.load_all_vectors()
        assert ids == []
        assert store.get_file_state("a.jsonl") is None


class TestMeta:
    def test_get_meta_returns_none_when_absent(self, store):
        assert store.get_meta("model") is None

    def test_set_then_get_meta_round_trips(self, store):
        store.set_meta("model", "fake-model")
        assert store.get_meta("model") == "fake-model"

    def test_set_meta_overwrites_existing_value(self, store):
        store.set_meta("model", "old")
        store.set_meta("model", "new")
        assert store.get_meta("model") == "new"

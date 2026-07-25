"""Store の往復（insert/read/delete）と file_state/meta の単体テスト。:memory: SQLite のみ使用。"""
from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from recall.chunker import Chunk
from recall.search import build_fts_query
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


def _embeddings(n, dim=2):
    return np.array([[0.1, 0.2]] * n, dtype=np.float32)[:, :dim]


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

    def test_clear_all_survives_broken_fts_and_clears_chunks(self, store):
        # 壊れた chunks_fts（削除済み等）に対する clear_all がクラッシュせず
        # chunks を消すことを検証する（recall index --all の唯一の回復手段）。
        store.upsert_chunks([_chunk()], np.array([[0.1, 0.2]], dtype=np.float32))
        store._conn.execute("DROP TABLE chunks_fts")  # FTS を壊す
        store._conn.commit()

        # クラッシュせず chunks が消えることを確認
        store.clear_all()

        ids, _ = store.load_all_vectors()
        assert ids == []


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


class TestKeywordTopK:
    """FTS5（trigram tokenizer）によるキーワード検索索引 chunks_fts。

    上流 agent-shelf/shelf/store.py の keyword_topk 系テストを、notebook 必須引数を
    project 任意フィルタへ読み替えて移植する。
    """

    def test_fts_enabled_is_true_on_this_sqlite_build(self, store):
        # このプロジェクトの動作環境は fts5+trigram が有効な SQLite にリンクされて
        # いる前提（実装ノート参照）。無効ならフェイルソフトパス（別テストで検証）
        # が働くはずなのでここでは有効を確認する。
        assert store.fts_enabled is True

    def test_keyword_topk_hits_japanese_natural_sentence_via_build_fts_query(self, store):
        # build_fts_query が空白なし日本語自然文をtrigramへ展開することで、
        # CJK 自然文がヒットすることを検証する（ハイブリッド検索の要）。
        store.upsert_chunks(
            [_chunk(text="量子力学の基礎について解説する資料です。")],
            _embeddings(1),
        )

        hits = store.keyword_topk(
            build_fts_query("量子力学の基礎について教えてください"), limit=10
        )

        assert [chunk_id for chunk_id, _score in hits] == ["a.jsonl#0"]

    def test_keyword_topk_reflects_updated_chunk_text(self, store):
        # 外部コンテンツ FTS の rowid 据え置き delete→insert が正しく機能し、
        # 上書き前の旧テキストの索引が残らないことを検証する。
        store.upsert_chunks([_chunk(text="classical mechanics")], _embeddings(1))
        assert store.keyword_topk("quantum", limit=10) == []

        store.upsert_chunks([_chunk(text="quantum entanglement")], _embeddings(1))

        hits = store.keyword_topk("quantum", limit=10)
        assert [chunk_id for chunk_id, _score in hits] == ["a.jsonl#0"]
        assert store.keyword_topk("classical", limit=10) == []

    def test_keyword_topk_excludes_chunks_removed_by_delete_by_source_file(self, store):
        store.upsert_chunks([_chunk(text="quantum entanglement")], _embeddings(1))
        assert len(store.keyword_topk("quantum", limit=10)) == 1

        store.delete_by_source_file("a.jsonl")

        assert store.keyword_topk("quantum", limit=10) == []

    def test_keyword_topk_excludes_chunks_removed_by_clear_all(self, store):
        store.upsert_chunks([_chunk(text="quantum entanglement")], _embeddings(1))
        assert len(store.keyword_topk("quantum", limit=10)) == 1

        store.clear_all()

        assert store.keyword_topk("quantum", limit=10) == []

    def test_keyword_topk_filters_by_project(self, store):
        store.upsert_chunks(
            [
                _chunk(id_="a.jsonl#0", project="proj-a", text="quantum entanglement"),
                _chunk(
                    id_="b.jsonl#0",
                    source_file="b.jsonl",
                    project="proj-b",
                    text="quantum computing basics",
                ),
            ],
            _embeddings(2),
        )

        hits = store.keyword_topk("quantum", limit=10, project="proj-a")

        assert [chunk_id for chunk_id, _score in hits] == ["a.jsonl#0"]

    def test_keyword_topk_returns_empty_list_for_blank_query(self, store):
        store.upsert_chunks([_chunk(text="quantum entanglement")], _embeddings(1))

        assert store.keyword_topk("   ", limit=10) == []
        assert store.keyword_topk("", limit=10) == []

    def test_keyword_topk_returns_empty_and_other_ops_survive_when_fts_disabled(self, store):
        store.upsert_chunks([_chunk(text="quantum entanglement")], _embeddings(1))
        store.fts_enabled = False  # fts5/trigram が使えない環境の劣化パスを強制検証

        assert store.keyword_topk("quantum", limit=10) == []
        # fts が無効でも通常の書き込み経路（upsert/delete）が壊れないことを検証する。
        store.upsert_chunks(
            [_chunk(id_="a.jsonl#1", text="classical mechanics")], _embeddings(1)
        )
        store.delete_by_source_file("a.jsonl")
        ids, _ = store.load_all_vectors()
        assert ids == []

    def test_keyword_topk_returns_empty_list_for_invalid_match_syntax(self, store):
        # 上流指摘: 未閉じ引用符のような不正な MATCH 構文もユーザー由来なので
        # 例外にせず [] に劣化する（呼び出し側がキーワード検索を諦めてベクタ検索のみに
        # フォールバック可能にするため）。
        store.upsert_chunks([_chunk(text="quantum entanglement")], _embeddings(1))

        assert store.keyword_topk('"unterminated', limit=10) == []

    def test_keyword_topk_degrades_and_disables_fts_on_broken_read_state(
        self, store, monkeypatch, caplog
    ):
        # 上流指摘: 読み取り(MATCH SELECT)自体が壊れている(read-only DB・
        # fts5 モジュール消失等)場合も keyword_topk の docstring 契約どおり例外にせず
        # [] に劣化させ、以後の呼び出しでは fts_enabled を落として静かにスキップし
        # 続けることを検証する(壊れたクエリを毎回再実行して警告ログを連発しない)。
        store.upsert_chunks([_chunk(text="quantum entanglement")], _embeddings(1))
        store._conn.execute("DROP TABLE chunks_fts")  # 読み取りが壊れた状態を人工的に作る

        with caplog.at_level("WARNING"):
            assert store.keyword_topk("quantum", limit=10) == []

        assert store.fts_enabled is False
        assert len(caplog.records) == 1  # 警告は初回失敗時に1回だけ

        # フラグが立った後、壊れた接続へ再クエリしないことを保証する。
        # sqlite3.Connection は C 拡張型でメソッドの直接差し替えができないため、
        # Store._conn 自体を MagicMock に差し替えて execute 未呼び出しを検証する。
        from unittest.mock import MagicMock

        fake_conn = MagicMock()
        monkeypatch.setattr(store, "_conn", fake_conn)

        with caplog.at_level("WARNING"):
            assert store.keyword_topk("quantum", limit=10) == []
        fake_conn.execute.assert_not_called()
        assert len(caplog.records) == 1  # 2回目の呼び出しで警告が増えない(黙ってスキップ)

    def test_fts_capture_rows_by_ids_splits_into_batch_sized_calls(self, store, monkeypatch):
        # 上流のバインドパラメータ上限超過バグ（IN句バッチ分割欠如）の回帰テスト。
        # 各バッチが _GET_CHUNKS_BATCH_SIZE 件以下に収まることを直接検証する。
        batch_size = Store._GET_CHUNKS_BATCH_SIZE
        ids = [f"a.jsonl#{i}" for i in range(batch_size + 1)]
        call_sizes: list[int] = []
        original = store._fts_capture_rows

        def spy(where_clause, params):
            call_sizes.append(len(params))
            return original(where_clause, params)

        monkeypatch.setattr(store, "_fts_capture_rows", spy)

        store._fts_capture_rows_by_ids(ids)

        assert call_sizes == [batch_size, 1]


class TestFtsInitProbe:
    """CREATE VIRTUAL TABLE IF NOT EXISTS はテーブル既存時にモジュール検証を行わない
    ため、_init_fts は実際に MATCH を実行するプローブクエリで fts5/trigram の
    動作を検証する（上流コミット 1e39c86 の移植）。
    """

    def test_pre_existing_fts_table_disables_when_probe_fails(
        self, tmp_path, monkeypatch, caplog
    ):
        db_path = tmp_path / "recall.db"
        store1 = Store(str(db_path))  # 通常起動で chunks_fts を作成しておく(テーブル既存化)
        store1.close()

        def failing_probe(self):
            raise sqlite3.OperationalError("simulated: trigram tokenizer unavailable")

        monkeypatch.setattr(Store, "_probe_fts", failing_probe)

        with caplog.at_level("WARNING"):
            store2 = Store(str(db_path))
        try:
            assert store2.fts_enabled is False
            # DB オープン時に FTS が無効化された事実は運用上observableであるべき
            # なので、_fts_disable_after_failure 経由で警告が1回出る。
            assert len(caplog.records) == 1
        finally:
            store2.close()

    def test_probe_failure_drops_fts_table_for_retry_on_next_open(
        self, tmp_path, monkeypatch
    ):
        # プローブ失敗時に chunks_fts を DROP して、次回オープンで再作成・バックフィルを
        # 実行できるようにする（SQLITE_BUSY 等の一過性失敗から回復する手段）。
        # バックフィルが必要な移行前 DB シナリオ: chunks は生存・chunks_fts は不在。
        db_path = tmp_path / "recall.db"

        # step 0: 移行前 DB を作成（chunks あり・chunks_fts なし）
        store0 = Store(str(db_path))
        store0.upsert_chunks([_chunk(text="quantum entanglement")], _embeddings(1))
        store0._conn.execute("DROP TABLE chunks_fts")  # FTS 未導入を模す
        store0._conn.commit()
        store0.close()

        # step 1: プローブ失敗を強制（CREATE 直後・バックフィル前に失敗）
        call_count = [0]

        def failing_probe_once(self):
            call_count[0] += 1
            if call_count[0] == 1:
                raise sqlite3.OperationalError("simulated: SQLITE_BUSY")
            # 2 回目以降は成功

        monkeypatch.setattr(Store, "_probe_fts", failing_probe_once)

        store1 = Store(str(db_path))
        store1.close()
        # fts_enabled は False（プローブ失敗により disable）。
        # 修正がある場合: chunks_fts は DROP されているため already_existed=False
        # 修正がない場合: chunks_fts は空テーブルのまま残り already_existed=True → バックフィルが実行されない

        # step 2: 2 回目オープン
        store2 = Store(str(db_path))
        try:
            # 修正あり: chunks_fts が再作成されバックフィルされているため keyword_topk が結果を返す
            # 修正なし: chunks_fts は空のまま（バックフィル未実行）のため keyword_topk は []
            hits = store2.keyword_topk("quantum", limit=10)
            assert [chunk_id for chunk_id, _score in hits] == ["a.jsonl#0"]
        finally:
            store2.close()


class TestFtsMigration:
    """旧スキーマ（chunks_fts なし）DB を再オープンした際の一度きりのバックフィル。"""

    def test_reopening_db_with_pre_existing_chunks_but_no_fts_table_backfills_once(
        self, tmp_path
    ):
        db_path = tmp_path / "recall.db"
        store1 = Store(str(db_path))
        store1.upsert_chunks([_chunk(text="quantum entanglement")], _embeddings(1))
        store1._conn.execute("DROP TABLE chunks_fts")  # FTS 未導入の旧 DB を模す
        store1._conn.commit()
        store1.close()

        store2 = Store(str(db_path))
        try:
            hits = store2.keyword_topk("quantum", limit=10)
        finally:
            store2.close()

        assert [chunk_id for chunk_id, _score in hits] == ["a.jsonl#0"]

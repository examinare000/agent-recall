"""indexer.index_corpus の増分索引化テスト。tmp_path + Store(:memory:) + FakeEmbedder のみ使用。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from recall.chunker import Chunk
from recall.indexer import index_corpus
from recall.store import Store
from tests.fakes import FakeEmbedder


def _write_jsonl(path: Path, human_texts: list[str]) -> None:
    lines = []
    for i, text in enumerate(human_texts):
        lines.append(json.dumps({
            "type": "user",
            "timestamp": f"2026-01-01T00:0{i}:00Z",
            "gitBranch": "main",
            "message": {"role": "user", "content": text},
        }, ensure_ascii=False))
        lines.append(json.dumps({
            "type": "assistant",
            "isSidechain": False,
            "message": {"role": "assistant", "content": [{"type": "text", "text": f"回答{i}"}]},
        }, ensure_ascii=False))
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


class TestIncremental:
    def test_indexes_new_file_and_creates_chunk(self, tmp_path, store):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        _write_jsonl(proj_dir / "a.jsonl", ["質問1"])
        embedder = FakeEmbedder()

        stats = index_corpus(tmp_path, store, embedder)

        assert stats.indexed_files == 1
        assert stats.skipped_files == 0
        ids, _ = store.load_all_vectors()
        assert ids == ["proj/a.jsonl#0"]

    def test_skips_unchanged_file_on_second_run(self, tmp_path, store):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        _write_jsonl(proj_dir / "a.jsonl", ["質問1"])
        embedder = FakeEmbedder()
        index_corpus(tmp_path, store, embedder)

        stats = index_corpus(tmp_path, store, embedder)

        assert stats.indexed_files == 0
        assert stats.skipped_files == 1

    def test_reindexes_when_file_content_and_mtime_change(self, tmp_path, store):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        f = proj_dir / "a.jsonl"
        _write_jsonl(f, ["質問1"])
        embedder = FakeEmbedder()
        index_corpus(tmp_path, store, embedder)

        _write_jsonl(f, ["質問1やや変更を加えた発話"])
        # mtime 分解能によるテストのフレークを避けるため明示的に時刻を進める
        stat = f.stat()
        os.utime(f, (stat.st_atime + 10, stat.st_mtime + 10))

        stats = index_corpus(tmp_path, store, embedder)

        assert stats.indexed_files == 1
        assert stats.skipped_files == 0
        chunk = store.get_chunk("proj/a.jsonl#0")
        assert "やや変更を加えた" in chunk["text"]

    def test_all_flag_reprocesses_even_unchanged_files(self, tmp_path, store):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        _write_jsonl(proj_dir / "a.jsonl", ["質問1"])
        embedder = FakeEmbedder()
        index_corpus(tmp_path, store, embedder)
        # 本来ならスキップされる状態であることを、DBの中身を直接壊して確認できるようにする
        store.upsert_chunks(
            [Chunk(id="proj/a.jsonl#0", source_file="proj/a.jsonl", project="proj",
                   branch="x", timestamp="x", text="改ざんされた本文")],
            embedder.embed_documents(["改ざんされた本文"]),
        )

        stats = index_corpus(tmp_path, store, embedder, full=True)

        assert stats.indexed_files == 1
        chunk = store.get_chunk("proj/a.jsonl#0")
        assert chunk["text"] != "改ざんされた本文"

    def test_rebuilds_automatically_when_stored_model_differs(self, tmp_path, store):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        _write_jsonl(proj_dir / "a.jsonl", ["質問1"])
        old_embedder = FakeEmbedder()
        old_embedder.model_name = "old-model"
        index_corpus(tmp_path, store, old_embedder)

        new_embedder = FakeEmbedder()
        new_embedder.model_name = "new-model"
        stats = index_corpus(tmp_path, store, new_embedder)

        assert stats.indexed_files == 1
        assert stats.skipped_files == 0
        assert store.get_meta("model") == "new-model"

    def test_isolates_unreadable_file_and_still_indexes_the_rest(
        self, tmp_path, store, monkeypatch
    ):
        """distill/extract.py と同様、1ファイルの OSError(権限エラー等)で
        索引全体が止まらないことを確認する。読めなかった件数は errors に集計する。
        chmod(0o000) は Windows では機能しないため、read_text の差し替えで再現する。
        """
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        _write_jsonl(proj_dir / "a.jsonl", ["質問1"])
        unreadable = proj_dir / "unreadable.jsonl"
        _write_jsonl(unreadable, ["質問2"])
        original_read_text = Path.read_text

        def failing_read_text(path: Path, *args, **kwargs):
            if path.name == unreadable.name:
                raise PermissionError(f"simulated unreadable file: {path}")
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", failing_read_text)
        embedder = FakeEmbedder()

        stats = index_corpus(tmp_path, store, embedder)

        assert stats.indexed_files == 1
        assert stats.errors == 1
        ids, _ = store.load_all_vectors()
        assert ids == ["proj/a.jsonl#0"]

    def test_source_file_uses_posix_separator_for_nested_files(self, tmp_path, store):
        """source_file（chunk の source_file 列 / file_state のキー）が POSIX "/" 区切りで
        保存されることを固定する。

        背景: shelf での既知バグでは Windows の "\\" 区切りが DB に永続化され、
        prune 誤動作と citation の source 不一致を引き起こした。本プロジェクトでは
        as_posix() による正規化で予防的に対応している。
        """
        proj_dir = tmp_path / "proj"
        sub_dir = proj_dir / "sub"
        sub_dir.mkdir(parents=True)
        _write_jsonl(sub_dir / "a.jsonl", ["質問1"])
        embedder = FakeEmbedder()

        index_corpus(tmp_path, store, embedder)

        chunk = store.get_chunk("proj/sub/a.jsonl#0")
        assert chunk is not None
        assert chunk["source_file"] == "proj/sub/a.jsonl"
        assert store.get_file_state("proj/sub/a.jsonl") is not None

    def test_prunes_chunks_for_files_removed_from_disk(self, tmp_path, store):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        _write_jsonl(proj_dir / "a.jsonl", ["質問1"])
        _write_jsonl(proj_dir / "b.jsonl", ["質問2"])
        embedder = FakeEmbedder()
        index_corpus(tmp_path, store, embedder)

        (proj_dir / "b.jsonl").unlink()
        stats = index_corpus(tmp_path, store, embedder)

        assert stats.pruned_files == 1
        ids, _ = store.load_all_vectors()
        assert ids == ["proj/a.jsonl#0"]
        assert store.get_file_state("proj/b.jsonl") is None


class TestMissingCorpusDir:
    def test_warns_to_stderr_when_corpus_dir_does_not_exist(self, tmp_path, store, capsys) -> None:
        """初回セットアップ等で CORPUS_DIR (~/.claude/corpus/claude-code) がまだ
        存在しない場合でも `recall index` は異常終了させず(exit 0)、原因に気づける
        よう stderr に警告を出す。索引対象0件として正常に完了することも合わせて確認する。
        """
        missing_dir = tmp_path / "not-yet-created"
        embedder = FakeEmbedder()

        stats = index_corpus(missing_dir, store, embedder)

        captured = capsys.readouterr()
        assert str(missing_dir) in captured.err
        assert stats.indexed_files == 0
        assert stats.errors == 0


class TestRawTextNonLeak:
    def test_no_raw_secret_reaches_store_text_column(self, tmp_path, store):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        secret = "sk-abcdefghijklmnopqrstuvwx"
        _write_jsonl(proj_dir / "a.jsonl", [f"このキーを使って: {secret}"])
        embedder = FakeEmbedder()

        index_corpus(tmp_path, store, embedder)

        ids, _ = store.load_all_vectors()
        assert ids  # チャンクが実際に作られていることを前提として確認する
        for chunk_id in ids:
            text = store.get_chunk(chunk_id)["text"]
            assert secret not in text
        chunk = store.get_chunk("proj/a.jsonl#0")
        assert "<REDACTED-KEY>" in chunk["text"]

    def test_no_raw_secret_survives_when_it_spans_the_truncation_boundary(self, tmp_path, store):
        """chunker の truncate/mask 順序バグ(1500字境界をまたぐ秘密が未マスクで
        残る)がインデックス経路全体で再発しないことを確認する統合テスト。
        """
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        secret_suffix = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        secret = "sk-" + secret_suffix
        human_text = "あ" * 1490 + secret
        _write_jsonl(proj_dir / "a.jsonl", [human_text])
        embedder = FakeEmbedder()

        index_corpus(tmp_path, store, embedder)

        chunk = store.get_chunk("proj/a.jsonl#0")
        assert secret_suffix[:10] not in chunk["text"]
        assert "sk-" not in chunk["text"]

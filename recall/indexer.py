"""corpus 走査 → 増分判定 → chunk → embed → store のオーケストレーション層。

chunker(純粋)・store(境界)・embedder(境界) はそれぞれ単体テスト済みなので、
ここでは「いつ再チャンク/再埋め込みするか」という増分判定の分岐だけに責務を絞る。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from recall.chunker import chunk_session
from recall.embedder import Embedder
from recall.store import Store


@dataclass(frozen=True)
class IndexStats:
    indexed_files: int
    skipped_files: int
    pruned_files: int
    chunks_written: int
    errors: int


def index_corpus(
    corpus_dir: Path, store: Store, embedder: Embedder, full: bool = False
) -> IndexStats:
    """corpus_dir 以下の *.jsonl を増分索引化する。

    - meta.model が embedder.model_name と異なる場合は自動で全再構築する
      （モデルを跨いでベクトル空間が混在するのを防ぐため）。
    - full=True (--all) は状態を無視して全ファイルを再チャンク・再埋め込みする。
    """
    if not corpus_dir.exists():
        # 初回セットアップ等、~/.claude/corpus/claude-code がまだ作成されていない場合の
        # 正常系。索引対象0件として完了させつつ(exit 0)、原因に気づけるよう警告のみ出す。
        print(
            f"[recall] 警告: CORPUS_DIR が存在しません: {corpus_dir}"
            " (初回セットアップ時はセッションが記録されるまで正常です)",
            file=sys.stderr,
        )

    stored_model = store.get_meta("model")
    if stored_model is not None and stored_model != embedder.model_name:
        full = True

    if full:
        store.clear_all()

    indexed_files = 0
    skipped_files = 0
    chunks_written = 0
    errors = 0
    existing_source_files: set[str] = set()

    for path in sorted(corpus_dir.rglob("*.jsonl")):
        # relative_to().as_posix(): Windows では relative_to() の結果が "\\" 区切りに
        # なり、DB に OS 依存の source_file が永続化されて prune 誤動作や citation の
        # source 不一致を招く（shelf の同一バグを踏襲しないための正規化）。
        source_file = path.relative_to(corpus_dir).as_posix()

        try:
            stat = path.stat()

            if not full:
                state = store.get_file_state(source_file)
                unchanged = (
                    state is not None
                    and state["mtime"] == stat.st_mtime
                    and state["size"] == stat.st_size
                )
                if unchanged:
                    existing_source_files.add(source_file)
                    skipped_files += 1
                    continue

            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            # distill/extract.py と同じ方針: 1ファイルの権限エラー等で索引全体を
            # 止めない。既存の chunk/file_state を誤って prune しないよう
            # existing として扱い、次回再試行できるようにする。
            existing_source_files.add(source_file)
            errors += 1
            continue

        existing_source_files.add(source_file)
        store.delete_by_source_file(source_file)
        chunks = chunk_session(lines, source_file)
        if chunks:
            embeddings = embedder.embed_documents([c.text for c in chunks])
            store.upsert_chunks(chunks, embeddings)
        store.set_file_state(
            source_file, mtime=stat.st_mtime, size=stat.st_size, model=embedder.model_name
        )
        indexed_files += 1
        chunks_written += len(chunks)

    pruned_files = store.prune_missing(existing_source_files)
    store.set_meta("model", embedder.model_name)
    store.set_meta("dim", str(embedder.dim))

    return IndexStats(
        indexed_files=indexed_files,
        skipped_files=skipped_files,
        pruned_files=pruned_files,
        chunks_written=chunks_written,
        errors=errors,
    )

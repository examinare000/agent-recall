"""SQLite への chunk / file_state / meta の永続化を担う境界層。

なぜ Store を独立させるか: SQLite・BLOB シリアライズという揮発的な詳細を
ここに閉じ込めることで、RecallService や search.py は「ベクトルと ID の配列」
という単純な形だけを扱えばよくなる（ドメインを SQLite から隔離するポート）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from recall.chunker import Chunk

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
  id          TEXT PRIMARY KEY,
  source_file TEXT NOT NULL,
  project     TEXT NOT NULL,
  branch      TEXT,
  timestamp   TEXT,
  text        TEXT NOT NULL,
  embedding   BLOB NOT NULL,
  dim         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_source  ON chunks(source_file);
CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project);

CREATE TABLE IF NOT EXISTS file_state (
  source_file TEXT PRIMARY KEY,
  mtime       REAL NOT NULL,
  size        INTEGER NOT NULL,
  model       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, db_path: str | Path) -> None:
        # DB_PATH の親ディレクトリを必要時に作成する（":memory:" はファイルではないのでスキップ）。
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def upsert_chunks(self, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        """chunks[i] と embeddings[i] を対応付けて insert or replace する。"""
        rows = [
            (
                chunk.id,
                chunk.source_file,
                chunk.project,
                chunk.branch,
                chunk.timestamp,
                chunk.text,
                np.asarray(vec, dtype=np.float32).tobytes(),
                len(vec),
            )
            for chunk, vec in zip(chunks, embeddings)
        ]
        self._conn.executemany(
            """
            INSERT INTO chunks (id, source_file, project, branch, timestamp, text, embedding, dim)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_file=excluded.source_file,
                project=excluded.project,
                branch=excluded.branch,
                timestamp=excluded.timestamp,
                text=excluded.text,
                embedding=excluded.embedding,
                dim=excluded.dim
            """,
            rows,
        )
        self._conn.commit()

    def delete_by_source_file(self, source_file: str) -> None:
        self._conn.execute("DELETE FROM chunks WHERE source_file = ?", (source_file,))
        self._conn.commit()

    def get_chunk(self, chunk_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT id, source_file, project, branch, timestamp, text FROM chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def load_all_vectors(self, project: str | None = None) -> tuple[list[str], np.ndarray]:
        """cosine 検索用に全ベクトルを1つの行列としてロードする。

        project 絞り込みは WHERE 句1本で完結する SQLite の仕事なので、
        ここで担う（search.py 側を project を知らない純粋なランキング関数に保てる）。
        """
        if project is None:
            rows = self._conn.execute(
                "SELECT id, embedding, dim FROM chunks ORDER BY id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, embedding, dim FROM chunks WHERE project = ? ORDER BY id",
                (project,),
            ).fetchall()
        if not rows:
            return [], np.zeros((0, 0), dtype=np.float32)
        ids = [row["id"] for row in rows]
        dim = rows[0]["dim"]
        matrix = np.zeros((len(rows), dim), dtype=np.float32)
        for i, row in enumerate(rows):
            matrix[i] = np.frombuffer(row["embedding"], dtype=np.float32)
        return ids, matrix

    def get_file_state(self, source_file: str) -> dict | None:
        row = self._conn.execute(
            "SELECT mtime, size, model FROM file_state WHERE source_file = ?",
            (source_file,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def set_file_state(self, source_file: str, mtime: float, size: int, model: str) -> None:
        self._conn.execute(
            """
            INSERT INTO file_state (source_file, mtime, size, model) VALUES (?, ?, ?, ?)
            ON CONFLICT(source_file) DO UPDATE SET mtime=excluded.mtime,
                size=excluded.size, model=excluded.model
            """,
            (source_file, mtime, size, model),
        )
        self._conn.commit()

    def list_source_files(self) -> list[str]:
        rows = self._conn.execute("SELECT source_file FROM file_state").fetchall()
        return [row["source_file"] for row in rows]

    def prune_missing(self, existing_source_files: set[str]) -> int:
        """corpus 上に存在しなくなったファイルの chunks/file_state を削除する。削除件数を返す。"""
        tracked = self.list_source_files()
        stale = [f for f in tracked if f not in existing_source_files]
        for source_file in stale:
            self.delete_by_source_file(source_file)
            self._conn.execute("DELETE FROM file_state WHERE source_file = ?", (source_file,))
        self._conn.commit()
        return len(stale)

    def clear_all(self) -> None:
        """全 chunks/file_state を削除する（--all 全再構築・モデル変更時の強制再構築用）。"""
        self._conn.execute("DELETE FROM chunks")
        self._conn.execute("DELETE FROM file_state")
        self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

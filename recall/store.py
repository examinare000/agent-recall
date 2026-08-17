"""SQLite への chunk / file_state / meta の永続化を担う境界層。

なぜ Store を独立させるか: SQLite・BLOB シリアライズという揮発的な詳細を
ここに閉じ込めることで、RecallService や search.py は「ベクトルと ID の配列」
という単純な形だけを扱えばよくなる（ドメインを SQLite から隔離するポート）。
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import numpy as np

from recall.chunker import Chunk

_logger = logging.getLogger(__name__)

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
    # SQLite の busy_timeout(ms)。recall は長命 MCP サーバ(server.py が Store を
    # プロセス生存中保持)と別プロセスの `recall index` CLI(cli.py が別 Store)が
    # 同一 DB ファイルへ同時アクセスする構成のため、単発の database is locked を
    # 即座に例外化させず SQLite 自身に自動リトライさせる猶予。これを設定しない
    # と、単発ロックが sqlite3.Error として keyword_topk 等に伝播し、
    # _fts_disable_after_failure がそのプロセスの生存中ずっとハイブリッド検索を
    # 無効化してしまう(サーバ再起動まで回復しない)。
    _BUSY_TIMEOUT_MS = 5000

    def __init__(self, db_path: str | Path) -> None:
        # DB_PATH の親ディレクトリを必要時に作成する（":memory:" はファイルではないのでスキップ）。
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # mcp 2.0.0 の MCPServer はツール呼び出しを Store 生成スレッドとは別の
        # ワーカースレッドから同期実行するため、デフォルトの同一スレッド制約では
        # "SQLite objects created in a thread can only be used in that same
        # thread" で落ちる。呼び出しは逐次（非並行）なので check_same_thread=False
        # による安全性の低下はない。
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 同時アクセスによる一時的なロック競合の頻度を下げる（上の _BUSY_TIMEOUT_MS
        # コメント参照）。foreign_keys より前に設定しても問題ない（両方とも
        # 接続スコープの PRAGMA）。
        self._conn.execute(f"PRAGMA busy_timeout = {self._BUSY_TIMEOUT_MS}")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self.fts_enabled = False
        self._init_fts()

    def close(self) -> None:
        self._conn.close()

    # -- FTS5（trigram tokenizer によるキーワード検索索引） ---------------------
    #
    # 上流 agent-shelf/shelf/store.py からの忠実移植（コミット 28fb073/1e39c86）。
    # recall の chunks は notebook を持たず project 列を持つため、keyword_topk の
    # 絞り込みは notebook 必須引数ではなく project 任意引数に読み替えている。
    # generation によるベクタキャッシュ無効化機構は recall に存在しないため移植しない。

    def _init_fts(self) -> None:
        # fts5 の trigram tokenizer は SQLite のビルドオプション次第で使えない
        # 環境があるため、作成に失敗したら fts_enabled=False にフェイルソフトする
        # （キーワード検索は諦めるが、他の永続化機能はブロックしない）。
        # sqlite_master を CREATE 前に見ておくことで「今回新規作成したか」を判定し、
        # 新規作成時かつ chunks に既存データがある場合のみ一括バックフィルする
        # （移行専用。毎起動 rebuild や空テーブルへの rebuild は無駄）。
        already_existed = (
            self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunks_fts'"
            ).fetchone()
            is not None
        )
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                "text, content='chunks', content_rowid='rowid', tokenize='trigram')"
            )
            # CREATE ... IF NOT EXISTS はテーブルが既存の場合モジュール検証を行わない
            # （USING no_such_module のような壊れた定義でも成功してしまう）ため、
            # MATCH を実際に実行するプローブクエリで fts5 モジュール + trigram
            # tokenizer の動作を検証する。
            self._probe_fts()
        except sqlite3.Error as exc:
            self._conn.rollback()
            # プローブ失敗時に chunks_fts を DROP しておくことで、次回オープン時に
            # already_existed=False に戻し CREATE+バックフィルを再試行できるようにする
            # （SQLITE_BUSY 等の一過性失敗から回復する手段）。
            try:
                self._conn.execute("DROP TABLE IF EXISTS chunks_fts")
            except sqlite3.Error:
                pass
            self._fts_disable_after_failure("初期化", exc)
            return
        self.fts_enabled = True
        if not already_existed:
            has_chunks = self._conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is not None
            if has_chunks:
                # 旧 DB（chunks_fts 導入前に作られた・chunks に既存データあり）を
                # 開いたときだけの一度きりの移行バックフィル。以後の同期は
                # upsert_chunks/delete_by_source_file/clear_all 側の行単位更新に委ねる。
                try:
                    self._rebuild_fts()
                except sqlite3.Error as exc:
                    # バックフィル失敗時に chunks_fts テーブル自体が CREATE 済みのまま
                    # 残ると、次回起動時 already_existed=True となり二度とバックフィルが
                    # 走らず、既存チャンクが恒久的にキーワード検索から漏れる（サイレント劣化）。
                    # テーブルごと消しておけば次回起動時 already_existed=False に戻り、
                    # CREATE+バックフィルを再試行できる（自己修復）。
                    try:
                        self._conn.execute("DROP TABLE IF EXISTS chunks_fts")
                    except sqlite3.Error:
                        pass
                    self._fts_disable_after_failure("初期化", exc)
        self._conn.commit()

    def _probe_fts(self) -> None:
        # 既存テーブルに対する CREATE ... IF NOT EXISTS はモジュール検証を行わない
        # ため、実際に MATCH を実行して fts5 モジュール + trigram tokenizer が
        # 使える環境かどうかを確認する。結果は使わず、例外の有無だけを見る。
        self._conn.execute(
            "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?", ("probe",)
        ).fetchone()

    def _rebuild_fts(self) -> None:
        # _init_fts の一度きりの移行バックフィル専用。content= 外部コンテンツ
        # テーブルなのでトリガーではなくこの明示 rebuild で追従させる（設計判断:
        # トリガーは使わない方針）。呼び出し元の commit に相乗りするため、
        # ここ自体ではコミットしない。
        if self.fts_enabled:
            self._conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")

    def _fts_disable_after_failure(self, context: str, exc: Exception) -> None:
        # fts5/trigram が壊れた環境（read-only DB・モジュール消失等）では例外にせず
        # 劣化させ、以後の呼び出しでは同じ壊れた経路を再実行しない。fts_enabled=False
        # にすることで、各メソッド冒頭の `if not self.fts_enabled: return` に自然に
        # 短絡し、警告ログもこの失敗時の1回だけで済む（毎回ログを連発しない）。
        _logger.warning("chunks_fts の%sに失敗したためキーワード検索を無効化します: %r", context, exc)
        self.fts_enabled = False

    _GET_CHUNKS_BATCH_SIZE = 500  # SQLite バインドパラメータ上限を踏まえた分割単位。

    def _fts_capture_rows(self, where_clause: str, params: tuple) -> list[tuple[int, str]]:
        """外部コンテンツ FTS の 'delete' コマンドに必要な (rowid, text) を、
        chunks の上書き/削除より前に退避する（delete コマンドは索引時と同じ
        テキストを渡す必要があるため、上書き後では取得できない）。where_clause は
        呼び出し元（Store 内部メソッド）が固定文字列で渡す内部専用引数であり、
        値は全て params 経由のバインドパラメータになるため f-string 直書きでも
        injection の懸念はない。
        """
        if not self.fts_enabled:
            return []
        try:
            rows = self._conn.execute(
                f"SELECT rowid, text FROM chunks WHERE {where_clause}", params
            ).fetchall()
        except sqlite3.Error as exc:
            self._fts_disable_after_failure("退避読み取り", exc)
            return []
        return [(row["rowid"], row["text"]) for row in rows]

    def _fts_capture_rows_by_ids(self, ids: list[str]) -> list[tuple[int, str]]:
        """id 群に対応する chunks_fts delete 用 (rowid, text) を退避する。
        _GET_CHUNKS_BATCH_SIZE と同じ分割単位で IN 句を分割する（無分割の
        IN (...) は1ファイルのチャンクが多い場合に SQLite のバインドパラメータ
        上限（環境依存）を超えて sqlite3.Error となり、_fts_disable_after_failure
        でキーワード検索全体が静かに停止してしまうため）。
        """
        if not ids:
            return []
        rows: list[tuple[int, str]] = []
        for start in range(0, len(ids), self._GET_CHUNKS_BATCH_SIZE):
            batch = ids[start : start + self._GET_CHUNKS_BATCH_SIZE]
            rows.extend(
                self._fts_capture_rows(f"id IN ({','.join('?' for _ in batch)})", tuple(batch))
            )
        return rows

    def _fts_delete_rows(self, rows: list[tuple[int, str]]) -> None:
        """_fts_capture_rows で退避した (rowid, text) を chunks_fts から削除する。"""
        if not self.fts_enabled or not rows:
            return
        try:
            self._conn.executemany(
                "INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', ?, ?)",
                rows,
            )
        except sqlite3.Error as exc:
            self._fts_disable_after_failure("削除同期", exc)

    def _fts_insert_rows(self, ids: list[str]) -> None:
        """id 群に対応する現在の (rowid, text) を chunks から読み直し、
        chunks_fts へ挿入する（upsert 直後に呼ぶことで、新規行・更新行の
        双方を一括で反映できる。更新行は ON CONFLICT DO UPDATE で rowid が
        据え置かれるため、_fts_delete_rows の削除対象と同じ rowid に
        insert し直すことになる）。_GET_CHUNKS_BATCH_SIZE 件ごとにバッチ分割する。
        """
        if not self.fts_enabled or not ids:
            return
        for start in range(0, len(ids), self._GET_CHUNKS_BATCH_SIZE):
            if not self.fts_enabled:
                # 前バッチの失敗で _fts_disable_after_failure により既に
                # 無効化されている場合、以降のバッチは実行しない。
                return
            batch = ids[start : start + self._GET_CHUNKS_BATCH_SIZE]
            self._fts_insert_rows_batch(batch)

    def _fts_insert_rows_batch(self, ids: list[str]) -> None:
        """_fts_insert_rows の1バッチ分（最大 _GET_CHUNKS_BATCH_SIZE 件）を処理する。"""
        # placeholders は "?" の個数分の定型文字列で、実データ(ids)は全て
        # 後続のバインドパラメータとして渡すため f-string 直書きでも
        # injection の懸念はない。
        placeholders = ",".join("?" for _ in ids)
        try:
            rows = self._conn.execute(
                f"SELECT rowid, text FROM chunks WHERE id IN ({placeholders})", ids
            ).fetchall()
            self._conn.executemany(
                "INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)",
                [(row["rowid"], row["text"]) for row in rows],
            )
        except sqlite3.Error as exc:
            self._fts_disable_after_failure("挿入同期", exc)

    def upsert_chunks(self, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        """chunks[i] と embeddings[i] を対応付けて insert or replace する。"""
        ids = [chunk.id for chunk in chunks]
        # 上書き対象（既存 id への ON CONFLICT DO UPDATE）は旧テキストの索引を
        # 残さないよう、上書きより前に (rowid, text) を退避しておく（新規 id は
        # 何もヒットせず、退避は空になる）。
        old_fts_rows = self._fts_capture_rows_by_ids(ids)
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
        # 上書き前の旧索引を消してから、上書き後の現在値で入れ直す。新規 id は
        # capture_rows が空なので delete/insert ともスキップされる。
        self._fts_delete_rows(old_fts_rows)
        self._fts_insert_rows(ids)
        self._conn.commit()

    def delete_by_source_file(self, source_file: str) -> None:
        # FTS 削除時は旧テキストの取得が必須なため、delete より前に capture する。
        fts_rows = self._fts_capture_rows("source_file = ?", (source_file,))
        self._conn.execute("DELETE FROM chunks WHERE source_file = ?", (source_file,))
        self._fts_delete_rows(fts_rows)
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
            # delete_by_source_file は各ファイルごとに commit を呼ぶため、
            # ここで追加の commit は不要（ただし file_state 削除はここで担当）。
            self.delete_by_source_file(source_file)
            self._conn.execute("DELETE FROM file_state WHERE source_file = ?", (source_file,))
        self._conn.commit()
        return len(stale)

    def clear_all(self) -> None:
        """全 chunks/file_state を削除する（--all 全再構築・モデル変更時の強制再構築用）。"""
        if self.fts_enabled:
            # 外部コンテンツ FTS の全消し専用コマンド。行単位の capture→delete では
            # 全件読み出しが無駄なため、'delete-all' で一括クリアする。
            try:
                self._conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('delete-all')")
            except sqlite3.Error as exc:
                # chunks_fts が壊れていても chunks/file_state の削除は続行する
                # （recall index --all の唯一の回復手段）。
                self._fts_disable_after_failure("全消し同期", exc)
        self._conn.execute("DELETE FROM chunks")
        self._conn.execute("DELETE FROM file_state")
        self._conn.commit()

    def keyword_topk(
        self, fts_query: str, limit: int, project: str | None = None
    ) -> list[tuple[str, float]]:
        """chunks_fts によるキーワード検索。`(chunk_id, bm25スコア)` のリストを
        bm25 昇順（値が小さいほど良い一致＝fts5 の仕様）で返す。

        fts_enabled=False（fts5/trigram 非対応環境）・空/空白のみのクエリ・
        不正な MATCH 構文（ユーザー由来の生クエリなので例外にせず劣化させる）・
        read-only DB やモジュール消失等の実行時エラーは全て `[]` を返す（呼び出し
        側=search.py がキーワード検索を諦めてベクタ検索のみにフォールバック
        できるように）。chunks_fts の同期は upsert_chunks 等の書き込み経路側で
        完了済みのため、ここでは読み取りのみを行う。
        """
        if not self.fts_enabled:
            return []
        if not fts_query.strip():
            return []
        params: tuple = (fts_query,)
        # where_project は固定文字列（project 引数の値そのものは含まない）で、
        # project の実値は params 経由のバインドパラメータになるため f-string
        # 直書きでも injection の懸念はない。
        where_project = ""
        if project is not None:
            where_project = " AND c.project = ?"
            params = (fts_query, project)
        try:
            rows = self._conn.execute(
                f"""
                SELECT c.id AS id, bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks c ON c.rowid = chunks_fts.rowid
                WHERE chunks_fts MATCH ?{where_project}
                ORDER BY score
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            # MATCH SELECT 自体の失敗（read-only DB・fts5 モジュール消失等）も
            # 例外にせず劣化させる。
            self._fts_disable_after_failure("読み取り", exc)
            return []
        return [(row["id"], row["score"]) for row in rows]

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

"""パス・モデル名の解決。

env で上書き可能にしているのは、テスト時に本物の corpus/DB/モデルへ
副作用を及ぼさないようにするため（FakeEmbedder と :memory: DB を使う単体テストから、
実データを使うスモークテストまでを同じコードパスで賄う）。
"""

from __future__ import annotations

import os
from pathlib import Path

# config.py はパッケージディレクトリ recall/recall/ の直下にあり、そこから2階層
# 上がスタンドアロンリポジトリのルート（pyproject.toml・distill/ が同居する層）。
REPO_ROOT = Path(__file__).resolve().parent.parent

CORPUS_DIR = Path(
    os.environ.get("RECALL_CORPUS_DIR", Path.home() / ".claude" / "corpus" / "claude-code")
)
# DB_PATH はコーパス本体と異なり、コーパスから毎回再構築できる派生インデックス
# （埋め込みベクトル・チャンクのキャッシュ）だが、Claude Code プラグインとして配布する場合、
# plugin install はファイルコピーのみで uv sync を行わず、plugin cache は更新のたびに
# 揮発する。REPO_ROOT 配下（cache 内）に置くと再索引のたびに利用者データが消えるため、
# cache の外である ~/.claude/agent-recall/ 配下を既定にする。
DB_PATH = Path(
    os.environ.get(
        "RECALL_DB_PATH", Path.home() / ".claude" / "agent-recall" / "index" / "recall.db"
    )
)
MODEL_NAME = os.environ.get(
    "RECALL_MODEL_NAME", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EXTRACT_PY_PATH = Path(
    os.environ.get("RECALL_EXTRACT_PY_PATH", REPO_ROOT / "distill" / "extract.py")
)


def _resolve_model_cache_dir() -> Path:
    """fastembed のモデルキャッシュ先を、起動時の CWD に依存しない絶対パスへ解決する。

    fastembed の既定キャッシュ先は tempfile.gettempdir()/fastembed_cache であり $TMPDIR に
    依存する。$TMPDIR は Claude Code のサンドボックス内外で別パスへ解決されるため、既定のままだと
    起動のたびにダウンロード済みモデルを見失い、ネットワーク遮断下では再ダウンロードに失敗して
    MCP サーバが起動できなくなる。~/.cache 配下は書き込みが許可され揮発もしないため、ここを既定にする。

    env で相対パスを渡された場合も、解決基点をホームディレクトリに固定して絶対パス化する。
    fastembed は相対 cache_dir をプロセスの CWD 基準で解決するが、MCP サーバは CWD 不定の状態で
    起動されるため、相対パスをそのまま渡すと起動元ごとに別ディレクトリを指し、上記と同じ壊れ方をする。
    """
    raw = os.environ.get("RECALL_MODEL_CACHE_DIR")
    if raw is None:
        return Path.home() / ".cache" / "fastembed"
    path = Path(raw).expanduser()
    return path if path.is_absolute() else Path.home() / path


MODEL_CACHE_DIR = _resolve_model_cache_dir()


def _bool_env(name: str, default: bool) -> bool:
    """真偽値の env 上書きを解決する（上流 agent-shelf/shelf/config.py の方式を移植）。

    "1"/"true"（大文字小文字不問）だけを真として認識し、それ以外の明示的な値
    （"false"/"0"/"no"/"off" は当然含む）は全て偽と扱う。設定ミスで意図せず
    真になる方が誤検知として気付きにくいため、許可リスト方式（真の側だけを
    明示列挙）を採用している。
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true")


# ask/search のチャンク検索を、cosine ベクトル検索単体ではなく FTS5 キーワード検索
# (BM25) との RRF（Reciprocal Rank Fusion）併用にするかどうか。既定 True: ベクトル
# 検索は意味的に近いが語彙が一致しない文を拾える一方、固有名詞・型番のような
# 表記ゆれの少ない語の完全一致取りこぼしに弱いため、キーワード検索を併用した方が
# 実運用の検索精度が高いと判断した。fts5/trigram tokenizer が使えない環境では
# store.fts_enabled=False により自動的にベクトル単体へ劣化する（このフラグは
# 「使う意図があるか」のみを表す。上流 agent-shelf/shelf/config.py の HYBRID_SEARCH
# と同じ設計）。
HYBRID_SEARCH = _bool_env("RECALL_HYBRID_SEARCH", True)

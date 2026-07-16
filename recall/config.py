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

CORPUS_DIR = Path(os.environ.get("RECALL_CORPUS_DIR", REPO_ROOT / "corpus" / "claude-code"))
DB_PATH = Path(os.environ.get("RECALL_DB_PATH", REPO_ROOT / "recall" / ".index" / "recall.db"))
MODEL_NAME = os.environ.get(
    "RECALL_MODEL_NAME", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EXTRACT_PY_PATH = Path(
    os.environ.get("RECALL_EXTRACT_PY_PATH", REPO_ROOT / "distill" / "extract.py")
)

"""秘密文字列マスクの単一ソース。

なぜ importlib で distill/extract.py を直接読み込むのか:
mask/is_human_prompt/extract_text のロジックを recall 側で再実装すると、
将来どちらかだけが更新されて基準が drift する（=マスク漏れ）リスクがある。
extract.py は改変禁止の既存資産なので、モジュールとして読み込んで
再エクスポートすることで「ロジックの出どころは常に1つ」を保証する。
"""
from __future__ import annotations

import importlib.util
import sys

from recall.config import EXTRACT_PY_PATH

# sys.modules にキャッシュするのは、テストコードが同一モジュールを
# 再取得して `mask is ...` の同一性検証（drift ガード）をできるようにするため。
_MODULE_NAME = "distill_extract"
if _MODULE_NAME in sys.modules:
    _ext = sys.modules[_MODULE_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, EXTRACT_PY_PATH)
    if _spec is None or _spec.loader is None:  # pragma: no cover - 設定ミス時のみ到達
        raise ImportError(f"extract.py を読み込めません: {EXTRACT_PY_PATH}")
    _ext = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = _ext
    _spec.loader.exec_module(_ext)

mask = _ext.mask
is_human_prompt = _ext.is_human_prompt
extract_text = _ext.extract_text
SKIP_PREFIXES = _ext.SKIP_PREFIXES

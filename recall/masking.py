"""秘密文字列マスク・切り詰め規約の単一ソース。

なぜ importlib で distill/extract.py を直接読み込むのか:
mask/is_human_prompt/extract_text/MAX_CHARS のロジックと定数を recall 側で
再実装すると、将来どちらかだけが更新されて基準が drift する（=マスク漏れや
切り詰め長のずれ）リスクがある。extract.py を単一ソースとし、モジュールとして
読み込んで再エクスポートすることで「ロジック・定数の出どころは常に1つ」を
保証する（extract.py 側の改変は本モジュール経由の全消費者に自動で波及する）。
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
MAX_CHARS = _ext.MAX_CHARS

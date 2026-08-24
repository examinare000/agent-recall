"""atomic_write_text (distill/extract.py) のアトミック書き込み回帰テスト。

なぜこのテストが必要か:
distill/extract.py はダイジェスト出力(digest-*.md)と増分カーソル(.extract-state.json)を
直接 write_text していたため、書き込み途中のクラッシュで破損ファイルが残り得た。
temp+rename 方式へ変更したことで「失敗時に既存ファイルが無傷で残る」ことを保証する。

recall/tests/test_masking.py と同じ流儀(importlib 動的ロード + sys.modules キャッシュ)で
distill/extract.py の実体を取得する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from recall import masking  # noqa: F401  (import 経由で distill_extract を sys.modules に登録する)

_extract_module = sys.modules["distill_extract"]
atomic_write_text = _extract_module.atomic_write_text


def _tmp_leftovers(directory: Path, target_name: str) -> list[Path]:
    return list(directory.glob(f".{target_name}.*"))


def test_atomic_write_overwrites_existing_file_with_matching_content(tmp_path):
    target = tmp_path / "digest-existing.md"
    target.write_text("old content", encoding="utf-8")

    atomic_write_text(target, "new content")

    assert target.read_text(encoding="utf-8") == "new content"
    assert _tmp_leftovers(tmp_path, target.name) == []


def test_atomic_write_creates_new_file(tmp_path):
    target = tmp_path / ".extract-state.json"
    assert not target.exists()

    atomic_write_text(target, '{"last_ts": "2026-07-18"}')

    assert target.read_text(encoding="utf-8") == '{"last_ts": "2026-07-18"}'
    assert _tmp_leftovers(tmp_path, target.name) == []


def test_atomic_write_preserves_existing_file_when_write_fails(tmp_path, monkeypatch):
    target = tmp_path / ".extract-state.json"
    target.write_text('{"last_ts": "2026-07-01"}', encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(Path, "write_text", boom)

    with pytest.raises(OSError):
        atomic_write_text(target, '{"last_ts": "2026-07-18"}')

    assert target.read_text(encoding="utf-8") == '{"last_ts": "2026-07-01"}'
    assert _tmp_leftovers(tmp_path, target.name) == []

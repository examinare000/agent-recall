"""masking.py: distill/extract.py を単一ソースとして再エクスポートしていることの回帰テスト。

意図: mask ロジックが recall 側で独自に再実装され、extract.py と drift するのを防ぐ。
そのため「同じ関数を指しているか(is)」まで確認する。
"""
from __future__ import annotations

import sys

from recall import masking


def test_mask_is_same_object_as_extract_py():
    """drift ガード: recall.masking.mask は distill/extract.py の mask そのものであること。

    recall.masking は importlib で extract.py を sys.modules["distill_extract"] に
    キャッシュして読み込むため、その実体と関数オブジェクトが同一(is)であることまで確認する。
    """
    extract_module = sys.modules["distill_extract"]
    assert masking.mask is extract_module.mask


def test_mask_redacts_openai_style_key():
    assert masking.mask("key=sk-abcdefghijklmnop") == "key=<REDACTED-KEY>"


def test_mask_redacts_github_token():
    text = "token ghp_abcdefghijklmnopqrst1234"
    assert "<REDACTED-TOKEN>" in masking.mask(text)


def test_mask_redacts_aws_access_key():
    text = "AKIAABCDEFGHIJKLMNOP"
    assert masking.mask(text) == "<REDACTED-AWS>"


def test_mask_redacts_password_assignment():
    assert masking.mask("password=hunter2") == "password=<REDACTED>"


def test_mask_redacts_jwt():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dGhpc2lzYXNpZ25hdHVyZQ"
    assert masking.mask(jwt) == "<REDACTED-JWT>"

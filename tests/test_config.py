"""config.py の REPO_ROOT 解決の回帰テスト。

なぜ必要か: REPO_ROOT はディレクトリ階層の深さに対する仮定（`parent` の回数）に
依存しており、リポジトリの物理配置（モノレポ内 vs スタンドアロン）が変わると
簡単に壊れる。EXTRACT_PY_PATH 等はこの値から導出されるため、実ファイルへ
正しく到達できることを固定して drift を検出する。
"""
from __future__ import annotations

from recall.config import EXTRACT_PY_PATH, REPO_ROOT


def test_repo_root_is_this_repository_root() -> None:
    # pyproject.toml はリポジトリルート直下にある前提（recall パッケージの配置規約）。
    assert (REPO_ROOT / "pyproject.toml").is_file()


def test_extract_py_path_points_to_existing_file() -> None:
    # distill/extract.py はこのリポジトリに同梱されている前提。
    assert EXTRACT_PY_PATH.is_file()

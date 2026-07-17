"""config.py の REPO_ROOT 解決の回帰テスト。

なぜ必要か: REPO_ROOT はディレクトリ階層の深さに対する仮定（`parent` の回数）に
依存しており、リポジトリの物理配置（モノレポ内 vs スタンドアロン）が変わると
簡単に壊れる。EXTRACT_PY_PATH 等はこの値から導出されるため、実ファイルへ
正しく到達できることを固定して drift を検出する。
"""
from __future__ import annotations

import importlib
from pathlib import Path

import recall.config as config
from recall.config import EXTRACT_PY_PATH, REPO_ROOT


def test_repo_root_is_this_repository_root() -> None:
    # pyproject.toml はリポジトリルート直下にある前提（recall パッケージの配置規約）。
    assert (REPO_ROOT / "pyproject.toml").is_file()


def test_extract_py_path_points_to_existing_file() -> None:
    # distill/extract.py はこのリポジトリに同梱されている前提。
    assert EXTRACT_PY_PATH.is_file()


class TestCorpusDirDefault:
    def test_defaults_to_dot_claude_corpus_claude_code(self, monkeypatch) -> None:
        # hooks/archive-session.sh・README の標準パス規約（~/.claude/corpus/claude-code/）と
        # 既定値を一致させる回帰テスト。クローン先直下(REPO_ROOT/corpus)には置かない。
        with monkeypatch.context() as m:
            m.delenv("RECALL_CORPUS_DIR", raising=False)
            importlib.reload(config)
            assert config.CORPUS_DIR == Path.home() / ".claude" / "corpus" / "claude-code"
        importlib.reload(config)  # env 復元後にモジュール状態も既定へ戻す

    def test_env_override_still_wins(self, monkeypatch, tmp_path) -> None:
        # 単体テストが実コーパスへ副作用を及ぼさないための上書き経路を維持する回帰テスト。
        with monkeypatch.context() as m:
            m.setenv("RECALL_CORPUS_DIR", str(tmp_path))
            importlib.reload(config)
            assert config.CORPUS_DIR == tmp_path
        importlib.reload(config)


class TestDbPathDefault:
    def test_defaults_to_dot_claude_agent_recall_index(self, monkeypatch) -> None:
        # plugin install はファイルコピーのみで uv sync を行わず、cache は更新のたびに
        # 揮発する。索引DBを REPO_ROOT 配下（cache 内）に置くと利用者データが消えるため、
        # cache の外である ~/.claude/agent-recall/ 配下を既定にする回帰テスト。
        with monkeypatch.context() as m:
            m.delenv("RECALL_DB_PATH", raising=False)
            importlib.reload(config)
            assert (
                config.DB_PATH
                == Path.home() / ".claude" / "agent-recall" / "index" / "recall.db"
            )
        importlib.reload(config)  # env 復元後にモジュール状態も既定へ戻す

    def test_env_override_still_wins(self, monkeypatch, tmp_path) -> None:
        # 単体テストが実DBへ副作用を及ぼさないための上書き経路を維持する回帰テスト。
        with monkeypatch.context() as m:
            m.setenv("RECALL_DB_PATH", str(tmp_path / "recall.db"))
            importlib.reload(config)
            assert config.DB_PATH == tmp_path / "recall.db"
        importlib.reload(config)

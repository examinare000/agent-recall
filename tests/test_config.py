"""config.py の REPO_ROOT 解決と _bool_env / HYBRID_SEARCH の env 上書き検証。

config.py はモジュール読み込み時に環境変数と相対パスを解決して module-level 定数へ
束ねるため、HYBRID_SEARCH の env 上書きテストは importlib.reload で再解決させて検証する
（monkeypatch.context() の with ブロック内で reload → with を抜けてからもう一度
reload して既定値へ戻すパターン。プレーンな monkeypatch フィクスチャ＋別フィクスチャの
teardown で reload する組み方は LIFO 順序が保証されず、env 未復元のまま reload される
事故があるため採らない）。

REPO_ROOT はディレクトリ階層の深さに対する仮定（`parent` の回数）に
依存しており、リポジトリの物理配置（モノレポ内 vs スタンドアロン）が変わると
簡単に壊れる。EXTRACT_PY_PATH 等はこの値から導出されるため、実ファイルへ
正しく到達できることを固定して drift を検出する。
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from recall import config
from recall.config import EXTRACT_PY_PATH, REPO_ROOT


class TestBoolEnvHelper:
    """_bool_env はモジュール定数と無関係な純粋関数なので reload 不要で直接検証できる。"""

    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("RECALL_TEST_FLAG", raising=False)
        assert config._bool_env("RECALL_TEST_FLAG", True) is True
        assert config._bool_env("RECALL_TEST_FLAG", False) is False

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "True"])
    def test_recognizes_truthy_values(self, monkeypatch, raw):
        monkeypatch.setenv("RECALL_TEST_FLAG", raw)
        assert config._bool_env("RECALL_TEST_FLAG", False) is True

    @pytest.mark.parametrize("raw", ["false", "0", "no", "off", "garbage"])
    def test_recognizes_falsy_and_unrecognized_values_as_false(self, monkeypatch, raw):
        monkeypatch.setenv("RECALL_TEST_FLAG", raw)
        assert config._bool_env("RECALL_TEST_FLAG", True) is False


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


class TestHybridSearchConfigConstant:
    def test_defaults_to_true_when_env_unset(self, monkeypatch):
        with monkeypatch.context() as m:
            m.delenv("RECALL_HYBRID_SEARCH", raising=False)
            importlib.reload(config)
            assert config.HYBRID_SEARCH is True
        importlib.reload(config)

    def test_can_be_disabled_via_env(self, monkeypatch):
        with monkeypatch.context() as m:
            m.setenv("RECALL_HYBRID_SEARCH", "0")
            importlib.reload(config)
            assert config.HYBRID_SEARCH is False
        importlib.reload(config)

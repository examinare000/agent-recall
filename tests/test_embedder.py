"""embedder.py の純粋部分（L2正規化）と、TextEmbedding へ渡す引数を単体テストする。

FastEmbedEmbedder の埋め込み計算自体は ONNX モデルの実ダウンロードを伴うため、
ここでは検証せず実データスモーク（README/報告）で確認する（設計書 §14）。
ただし cache_dir の受け渡しは TextEmbedding をスパイへ差し替えることで
ダウンロードなしに検証できるため、回帰テストとして固定する。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from recall import embedder as embedder_module
from recall.config import MODEL_CACHE_DIR
from recall.embedder import FastEmbedEmbedder, l2_normalize


def test_l2_normalize_single_vector_has_unit_norm():
    vec = np.array([3.0, 4.0], dtype=np.float32)
    normalized = l2_normalize(vec)
    assert np.isclose(np.linalg.norm(normalized), 1.0)


def test_l2_normalize_matrix_normalizes_each_row():
    matrix = np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32)
    normalized = l2_normalize(matrix)
    norms = np.linalg.norm(normalized, axis=1)
    np.testing.assert_allclose(norms, [1.0, 1.0])


def test_l2_normalize_zero_vector_stays_zero_without_division_error():
    vec = np.array([0.0, 0.0], dtype=np.float32)
    normalized = l2_normalize(vec)
    np.testing.assert_allclose(normalized, [0.0, 0.0])


class SpyTextEmbedding:
    """TextEmbedding の呼び出し kwargs だけを記録するスパイ（実ダウンロードを起こさない）。"""

    last_kwargs: dict | None = None

    def __init__(self, **kwargs) -> None:
        SpyTextEmbedding.last_kwargs = kwargs

    @staticmethod
    def get_embedding_size(model_name: str) -> int:
        return 384


class TestFastEmbedEmbedderCacheDir:
    """cache_dir を明示しないと fastembed が $TMPDIR 依存の既定パスへ落ちるため、
    MODEL_CACHE_DIR が必ず渡ることを固定する回帰テスト。
    """

    def test_passes_model_cache_dir_by_default(self, monkeypatch) -> None:
        monkeypatch.setattr(embedder_module, "TextEmbedding", SpyTextEmbedding)
        SpyTextEmbedding.last_kwargs = None

        FastEmbedEmbedder("dummy-model")

        assert SpyTextEmbedding.last_kwargs == {
            "model_name": "dummy-model",
            "cache_dir": str(MODEL_CACHE_DIR),
        }

    def test_explicit_cache_dir_takes_precedence(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(embedder_module, "TextEmbedding", SpyTextEmbedding)
        SpyTextEmbedding.last_kwargs = None

        FastEmbedEmbedder("dummy-model", tmp_path)

        assert SpyTextEmbedding.last_kwargs["cache_dir"] == str(tmp_path)

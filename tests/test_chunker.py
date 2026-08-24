"""chunker.chunk_session の純粋関数テスト（ファイル/DB 一切なし）。"""

from __future__ import annotations

import importlib
import json
import sys

from recall import chunker as chunker_module
from recall import masking as masking_module
from recall.chunker import Chunk, chunk_session


def _line(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)


def _human(text: str, ts: str, branch: str = "main", user_type=None, extra=None):
    d = {
        "type": "user",
        "timestamp": ts,
        "gitBranch": branch,
        "message": {"role": "user", "content": text},
    }
    if user_type is not None:
        d["userType"] = user_type
    if extra:
        d.update(extra)
    return d


def _assistant(text: str, sidechain: bool = False):
    return {
        "type": "assistant",
        "isSidechain": sidechain,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


class TestPairing:
    def test_pairs_human_utterance_with_following_assistant_reply(self):
        lines = [
            _line(_human("質問です", "2026-01-01T00:00:00Z")),
            _line(_assistant("回答です")),
        ]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert len(chunks) == 1
        assert chunks[0].text == "質問です\n\n---\n\n回答です"

    def test_concatenates_multiple_assistant_messages_before_next_human(self):
        lines = [
            _line(_human("質問1", "2026-01-01T00:00:00Z")),
            _line(_assistant("回答1a")),
            _line(_assistant("回答1b")),
        ]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert len(chunks) == 1
        assert chunks[0].text == "質問1\n\n---\n\n回答1a\n回答1b"

    def test_two_human_turns_become_two_chunks(self):
        lines = [
            _line(_human("質問1", "2026-01-01T00:00:00Z")),
            _line(_assistant("回答1")),
            _line(_human("質問2", "2026-01-01T00:01:00Z")),
            _line(_assistant("回答2")),
        ]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert [c.text for c in chunks] == [
            "質問1\n\n---\n\n回答1",
            "質問2\n\n---\n\n回答2",
        ]

    def test_keeps_chunk_when_assistant_reply_is_absent(self):
        lines = [_line(_human("質問のみ", "2026-01-01T00:00:00Z"))]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert len(chunks) == 1
        assert chunks[0].text == "質問のみ\n\n---\n\n"


class TestIgnoredLines:
    def test_ignores_sidechain_assistant_messages(self):
        lines = [
            _line(_human("質問", "2026-01-01T00:00:00Z")),
            _line(_assistant("サブエージェントの内部応答", sidechain=True)),
            _line(_assistant("本筋の応答")),
        ]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert chunks[0].text == "質問\n\n---\n\n本筋の応答"

    def test_ignores_tool_use_result_lines(self):
        lines = [
            _line(_human("質問", "2026-01-01T00:00:00Z")),
            _line(
                {
                    "type": "user",
                    "toolUseResult": {"foo": "bar"},
                    "message": {"role": "user", "content": "tool output"},
                }
            ),
            _line(_assistant("応答")),
        ]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert len(chunks) == 1
        assert chunks[0].text == "質問\n\n---\n\n応答"

    def test_skips_utterance_with_skip_prefix(self):
        lines = [_line(_human("<command-name>foo</command-name>", "2026-01-01T00:00:00Z"))]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert chunks == []

    def test_skips_utterance_shorter_than_two_chars(self):
        lines = [_line(_human("a", "2026-01-01T00:00:00Z"))]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert chunks == []

    def test_skips_malformed_json_line(self):
        lines = ["not valid json {", _line(_human("質問", "2026-01-01T00:00:00Z"))]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert len(chunks) == 1

    def test_skips_blank_lines(self):
        lines = ["", "   ", _line(_human("質問", "2026-01-01T00:00:00Z"))]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert len(chunks) == 1


class TestTruncation:
    def test_truncates_human_and_assistant_text_to_1500_chars(self):
        long_human = "あ" * 2000
        long_assistant = "い" * 2000
        lines = [
            _line(_human(long_human, "2026-01-01T00:00:00Z")),
            _line(_assistant(long_assistant)),
        ]
        chunks = chunk_session(lines, "proj/a.jsonl")
        human_part, _, assistant_part = chunks[0].text.partition("\n\n---\n\n")
        assert len(human_part) == 1500
        assert len(assistant_part) == 1500


class TestMasking:
    def test_applies_mask_to_full_body(self):
        lines = [
            _line(_human("秘密はsk-abcdefghijklmnopです", "2026-01-01T00:00:00Z")),
            _line(_assistant("了解")),
        ]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert "sk-abcdefghijklmnop" not in chunks[0].text
        assert "<REDACTED-KEY>" in chunks[0].text

    def test_masks_secret_key_spanning_the_1500_char_truncation_boundary(self):
        """mask を truncate の後に適用すると、1500字境界をまたぐ秘密鍵は正規表現の
        必要長(sk-以降12文字以上)を満たせず未マスクのまま残ってしまう回帰テスト。
        mask→truncate の順で実装されていれば、境界に関係なく必ずマスクされる。
        """
        secret_suffix = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # 36文字の英数字
        secret = "sk-" + secret_suffix
        human_text = "あ" * 1490 + secret  # 1490文字目以降で1500字境界をまたぐ
        lines = [
            _line(_human(human_text, "2026-01-01T00:00:00Z")),
            _line(_assistant("了解")),
        ]

        chunks = chunk_session(lines, "proj/a.jsonl")

        human_part, _, _ = chunks[0].text.partition("\n\n---\n\n")
        # 生の秘密鍵の断片(先頭10文字)すら残っていないことを確認する
        # (truncate→mask の順だと "sk-" + 先頭7文字だけ生で残ってしまう)
        assert secret_suffix[:10] not in human_part
        assert "sk-" not in human_part

    def test_masks_jwt_spanning_the_1500_char_truncation_boundary(self):
        """JWT は3セグメント(ヘッダ.ペイロード.署名)を丸ごと満たして初めて正規表現にマッチする。
        1文字目のヘッダ部分だけが1500字境界の直前に来るよう配置し、
        truncate→mask の順だと2つ目のドットに届かず未マッチのまま生で残ることを確認する。
        """
        jwt_header = "eyJhbGciOiJIUzI1NiJ9"  # 20文字。単体では正規表現にマッチしない
        jwt = jwt_header + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0.dGhpc2lzYXNpZ25hdHVyZQ"
        # ヘッダ+ドット+ペイロード数文字だけが境界内に収まり、2つ目のドットには届かない位置にする
        human_text = "あ" * 1475 + jwt
        lines = [
            _line(_human(human_text, "2026-01-01T00:00:00Z")),
            _line(_assistant("了解")),
        ]

        chunks = chunk_session(lines, "proj/a.jsonl")

        human_part, _, _ = chunks[0].text.partition("\n\n---\n\n")
        assert jwt_header not in human_part  # JWT ヘッダ部の生断片

    def test_masks_secret_key_spanning_boundary_on_assistant_side_too(self):
        secret_suffix = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        secret = "sk-" + secret_suffix
        assistant_text = "い" * 1490 + secret
        lines = [
            _line(_human("質問", "2026-01-01T00:00:00Z")),
            _line(_assistant(assistant_text)),
        ]

        chunks = chunk_session(lines, "proj/a.jsonl")

        _, _, assistant_part = chunks[0].text.partition("\n\n---\n\n")
        assert secret_suffix[:10] not in assistant_part
        assert "sk-" not in assistant_part


class TestMetadata:
    def test_chunk_fields_are_populated_correctly(self):
        lines = [
            _line(_human("質問", "2026-01-01T00:00:00Z", branch="feature/x")),
            _line(_assistant("応答")),
        ]
        chunks = chunk_session(lines, "-Users-rio-git-foo/session.jsonl")
        chunk = chunks[0]
        assert isinstance(chunk, Chunk)
        assert chunk.id == "-Users-rio-git-foo/session.jsonl#0"
        assert chunk.source_file == "-Users-rio-git-foo/session.jsonl"
        assert chunk.project == "-Users-rio-git-foo"
        assert chunk.branch == "feature/x"
        assert chunk.timestamp == "2026-01-01T00:00:00Z"

    def test_branch_defaults_to_dash_when_missing(self):
        d = _human("質問", "2026-01-01T00:00:00Z")
        del d["gitBranch"]
        chunks = chunk_session([_line(d)], "proj/a.jsonl")
        assert chunks[0].branch == "-"

    def test_ids_increment_per_kept_chunk_only(self):
        lines = [
            _line(_human("質問1", "2026-01-01T00:00:00Z")),
            _line(_human("a", "2026-01-01T00:00:01Z")),  # skipped: too short
            _line(_human("質問2", "2026-01-01T00:00:02Z")),
        ]
        chunks = chunk_session(lines, "proj/a.jsonl")
        assert [c.id for c in chunks] == ["proj/a.jsonl#0", "proj/a.jsonl#1"]


class TestMaxCharsSingleSource:
    def test_max_chars_default_is_sourced_from_extract_py(self, monkeypatch):
        """MAX_CHARS が distill/extract.py の値の単なる重複コピーでなく、実際に
        import 経由で伝播していることを固定する回帰テスト。

        値の一致(== 1500)だけを見るテストは chunker.py 側が独自の裸リテラルを
        持っていても偶然一致で通ってしまう。distill_extract 側の値を
        monkeypatch で差し替えてから masking→chunker の順に reload し、
        変更が実際に伝播することまで確認する。

        注意: reload は sys.modules 上の recall.chunker / recall.masking を
        新世代オブジェクトへ差し替える。reload によりモジュール内クラスの同一性が
        変わるため、Chunk の isinstance 比較をこのテスト以降に行うテストを
        追加する場合は注意が必要（reload 前の古い Chunk クラスと新しい世代の
        Chunk が異なるため、黙って False になる）。
        """
        extract_module = sys.modules["distill_extract"]
        try:
            with monkeypatch.context() as m:
                m.setattr(extract_module, "MAX_CHARS", 99)
                importlib.reload(masking_module)
                importlib.reload(chunker_module)
                assert chunker_module.MAX_CHARS == 99
        finally:
            # try/finally にするのは、assert 失敗時にも必ず復元処理を走らせるため
            # （with ブロックだけだと例外発生時にこの後続コードへ到達しない）。
            # with ブロックで monkeypatch は元の値に戻るが、reload 済みの
            # masking_module/chunker_module はモジュール状態として汚れたままなので、
            # 実体の値を使って再度 reload し、後続テストへの影響を残さないようにする。
            importlib.reload(masking_module)
            importlib.reload(chunker_module)
            # 値が正規状態へ戻ったことを確認
            assert chunker_module.MAX_CHARS == 1500
            # reload は Chunk クラス/chunk_session 関数を新しいオブジェクトとして
            # 再生成する。本ファイル冒頭の `from recall.chunker import Chunk,
            # chunk_session` で束縛した名前は reload 前の古い実体を指したままに
            # なり、後続テストの isinstance(chunk, Chunk) が意図せず偽になる
            # （本テストの reload に起因するクロスコンタミネーション）。
            # 再読込後の実体で束縛し直すことでこれを防ぐ。
            globals()["Chunk"] = chunker_module.Chunk
            globals()["chunk_session"] = chunker_module.chunk_session

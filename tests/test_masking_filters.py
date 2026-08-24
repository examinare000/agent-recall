"""is_human_prompt / extract_text の再エクスポート仕様テスト（extract.py 由来のロジックの確認）。"""

from __future__ import annotations

from recall import masking


class TestIsHumanPrompt:
    def test_true_for_plain_external_user_message(self):
        d = {"type": "user", "userType": "external"}
        assert masking.is_human_prompt(d) is True

    def test_true_when_user_type_missing(self):
        d = {"type": "user"}
        assert masking.is_human_prompt(d) is True

    def test_false_for_assistant_type(self):
        d = {"type": "assistant"}
        assert masking.is_human_prompt(d) is False

    def test_false_when_tool_use_result_present(self):
        d = {"type": "user", "toolUseResult": {"foo": "bar"}}
        assert masking.is_human_prompt(d) is False

    def test_false_when_sidechain(self):
        d = {"type": "user", "isSidechain": True}
        assert masking.is_human_prompt(d) is False

    def test_false_for_internal_user_type(self):
        d = {"type": "user", "userType": "internal"}
        assert masking.is_human_prompt(d) is False


class TestExtractText:
    def test_returns_str_content_as_is(self):
        assert masking.extract_text("こんにちは") == "こんにちは"

    def test_joins_text_blocks_from_list_content(self):
        content = [
            {"type": "text", "text": "1行目"},
            {"type": "tool_use", "text": "無視されるべき"},
            {"type": "text", "text": "2行目"},
        ]
        assert masking.extract_text(content) == "1行目\n2行目"

    def test_returns_empty_string_for_unsupported_type(self):
        assert masking.extract_text(None) == ""

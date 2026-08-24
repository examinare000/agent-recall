"""masking.py: distill/extract.py を単一ソースとして再エクスポートしていることの回帰テスト。

意図: mask ロジックが recall 側で独自に再実装され、extract.py と drift するのを防ぐ。
そのため「同じ関数を指しているか(is)」まで確認する。

また、値パターン修正後のクォート値マスキング（複数語のクォート文字列全体を捕捉）の
挙動を固定する。
"""

from __future__ import annotations

import sys

import pytest

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


class TestQuotedValueMasking:
    """クォート付き複数語 secret 値の修正後の挙動を固定する。

    値パターンは `"(?:\\\\.|[^"\\\\\\n])*"(?!\\\\S)` （ダブルクォート、内部エスケープ
    許容、改行は body から除外）/ `'(?:\\\\.|[^'\\\\\\n])*'(?!\\\\S)` （シングルクォート、
    同様）を `\\S+` より先に試し、どちらにもマッチしなければ従来どおり `\\S+` に
    フォールバックする。

    `\\n` を body から除外するのは、閉じクォートが別行にある入力（例:
    password 行の値がダブルクォートで開いたまま複数行下の別ラベル行で
    初めて閉じクォートに出会うケース）で無関係な複数行を丸ごと飲み込んで
    消してしまうのを防ぐため。閉じ直後に `(?!\\S)`（次が非空白なら不採用）を
    置くのは、値が空クォートや連続する複数個のクォート文字で始まるケースで
    「早期に閉じたと誤認して後続語を露出させる」短勝ちマッチを弾き、旧実装
    （`\\S+` のみ）と同等以上の安全側へ倒すため。両条件のいずれかで不採用になった
    場合は `\\S+` にフォールバックし、旧実装と同じ「先頭トークンのみマスク」に
    留まる。
    """

    def test_double_quoted_multiword_value_is_fully_masked(self) -> None:
        text = 'password: "hunter 2 with spaces"'

        result = masking.mask(text)

        assert result == "password=<REDACTED>"

    def test_quoted_value_with_trailing_punctuation_falls_back_to_first_token(
        self,
    ) -> None:
        # 閉じクォート直後が非空白（, ) } ; 等。JSON5/YAML flow/Python kwarg で頻出）の
        # 場合は (?!\S) によりクォート分岐を採らず、旧実装と同じ先頭トークンのみの
        # マスクに留まる。短勝ちマッチの再発防止と引き換えの既知の制限（CHANGELOG 開示）。
        result = masking.mask('password: "hunter 2 spaces",')

        assert result == 'password=<REDACTED> 2 spaces",'

    def test_single_quoted_multiword_value_is_fully_masked(self) -> None:
        text = "api_key: 'foo bar baz'"

        result = masking.mask(text)

        assert result == "api_key=<REDACTED>"

    def test_double_quoted_value_with_escaped_quote_is_fully_masked(self) -> None:
        # 値の中に \" を含むエスケープ済みクォートがあっても、そこで閉じたと
        # 誤認せず本当の閉じクォートまでをマスクする。
        text = r'secret: "say \"hi\" to bob"'

        result = masking.mask(text)

        assert result == "secret=<REDACTED>"
        assert "bob" not in result

    def test_single_quoted_value_with_escaped_quote_is_fully_masked(self) -> None:
        text = r"token: 'it\'s a secret'"

        result = masking.mask(text)

        assert result == "token=<REDACTED>"

    def test_double_quoted_value_starting_with_empty_quote_falls_back_to_full_token(
        self,
    ) -> None:
        # 値が空クォート ("") で始まり直後に非空白が続く場合、「早期に閉じた」と
        # 誤認して残りの語を露出させてはならない。(?!\S) が弾くことで \S+ に
        # フォールバックし、旧実装（\S+ のみ）と同じ「1トークン全体マスク」に
        # 落ち着く（このケースは内部に空白が無いため \S+ でも取りこぼしなく
        # 全体がマスクされる）。
        text = 'password: ""hunter2"'

        result = masking.mask(text)

        assert result == "password=<REDACTED>"
        assert "hunter2" not in result

    def test_double_quoted_empty_value_surrounding_variable_falls_back_to_full_token(
        self,
    ) -> None:
        # shell 変数展開に典型的な `""$VAR""` 形式。空クォートの早期閉じ誤認で
        # $REAL_KEY_VALUE が露出してはならない。
        text = 'export API_KEY=""$REAL_KEY_VALUE""'

        result = masking.mask(text)

        assert result == "export API_KEY=<REDACTED>"
        assert "REAL_KEY_VALUE" not in result

    def test_triple_quoted_value_falls_back_to_old_equivalent_first_token_masking(
        self,
    ) -> None:
        # 三重クォートは (?!\S) により空クォート早期閉じと同様に弾かれ \S+ へ
        # フォールバックする。旧実装（\S+ のみ）と全く同じ「先頭トークンのみ
        # マスク・残りは露出」という結果になる（新パターン導入前からの既知の
        # 限界であり、退行ではないことを固定する）。
        text = 'token: """triple secret"""'

        result = masking.mask(text)

        assert result == 'token=<REDACTED> secret"""'

    def test_quoted_value_leaves_trailing_text_after_close_quote_untouched(
        self,
    ) -> None:
        # 閉じクォート直後が空白であれば正常にクォート値全体をマスクし、
        # クォートの外側にある trailing テキストはマスク対象外として残ってよい。
        text = 'token:"a b" trailing'

        result = masking.mask(text)

        assert result == "token=<REDACTED> trailing"

    def test_crossline_unterminated_quote_only_masks_first_line_first_token(
        self,
    ) -> None:
        # \n を body から除外しているため、閉じクォートが数行下の別ラベル行に
        # あっても、そこまで貪欲に飲み込んで無関係な行を消してはならない。
        # 各行はそれぞれ独立して「クォート値かどうか」を判定され、閉じられない
        # 側は \S+ で先頭トークンのみマスクされ、他の行は無傷のまま残る。
        text = 'password: "start of secret\nmore stuff here\napi_key: "closed on another line'

        result = masking.mask(text)

        assert result == (
            "password=<REDACTED> of secret\nmore stuff here\napi_key=<REDACTED> on another line"
        )
        assert "start" not in result
        assert "closed" not in result
        assert "more stuff here" in result

    def test_unterminated_quote_falls_back_to_first_token_masking(self) -> None:
        # 閉じクォートが無い場合はクォート文字列として扱えないため、従来どおり
        # 先頭の空白区切りトークンのみをマスクする安全側の劣化にとどまる。
        text = 'password: "hunter2 unterminated'

        result = masking.mask(text)

        assert result == "password=<REDACTED> unterminated"

    def test_unquoted_single_word_value_still_masked_as_before(self) -> None:
        # クォート無しの単語値は従来どおり \S+ で1トークンだけマスクされる
        # （このケースはそもそも複数語ではないので回帰確認のみ）。
        text = "password: hunter2"

        result = masking.mask(text)

        assert result == "password=<REDACTED>"


class TestIdempotency:
    """mask(mask(x)) == mask(x)。二重適用しても追加の変換が発生しない。"""

    @pytest.mark.parametrize(
        ("text",),
        [
            pytest.param(
                'password: "hunter 2 with spaces"',
                id="double-quoted-multiword-value",
            ),
            pytest.param(
                "api_key: 'foo bar baz'",
                id="single-quoted-multiword-value",
            ),
            pytest.param(
                'password: """hunter 2 with spaces"""',
                id="triple-quoted-multiword-value-with-unbalanced-quotes",
            ),
            pytest.param(
                'export API_KEY=""$REAL_KEY_VALUE""',
                id="empty-quote-wrapped-shell-variable",
            ),
            pytest.param(
                'password: "start of secret\nmore stuff here\napi_key: "closed later',
                id="crossline-unterminated-double-quote",
            ),
            pytest.param(
                "token: 'it starts\nhere and it's\nnever closed",
                id="crossline-unterminated-single-quote-with-apostrophe",
            ),
        ],
    )
    def test_repeated_mask_is_stable(self, text: str) -> None:
        once = masking.mask(text)
        twice = masking.mask(once)
        assert twice == once

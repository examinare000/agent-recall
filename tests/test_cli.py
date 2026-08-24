"""cli.build_parser の引数解析テスト（実 Store/Embedder を構築しない純粋な部分のみ）。"""

from __future__ import annotations

from recall.cli import build_parser


class TestIndexCommand:
    def test_all_flag_defaults_to_false(self):
        args = build_parser().parse_args(["index"])
        assert args.command == "index"
        assert args.all is False

    def test_all_flag_can_be_set(self):
        args = build_parser().parse_args(["index", "--all"])
        assert args.all is True


class TestSearchCommand:
    def test_parses_query_project_and_limit(self):
        args = build_parser().parse_args(["search", "foo", "--project", "bar", "--limit", "3"])
        assert args.command == "search"
        assert args.query == "foo"
        assert args.project == "bar"
        assert args.limit == 3

    def test_project_and_limit_have_defaults(self):
        args = build_parser().parse_args(["search", "foo"])
        assert args.project is None
        assert args.limit == 5


class TestServeCommand:
    def test_parses(self):
        args = build_parser().parse_args(["serve"])
        assert args.command == "serve"

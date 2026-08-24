"""recall コマンドのエントリポイント。実 Store/FastEmbedEmbedder を組み立てて注入する。

引数解析(build_parser)はネットワーク非依存の純粋ロジックなので単体テスト対象。
各サブコマンドの実行(main)は実際の SQLite ファイル・ONNX モデルに触れるため、
単体テストでは検証せずスモークテスト（実データ）で確認する（設計書 §14 と同じ理由）。
"""

from __future__ import annotations

import argparse

from recall import config
from recall.config import CORPUS_DIR, DB_PATH
from recall.indexer import index_corpus
from recall.server import create_server
from recall.service import RecallService
from recall.store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recall", description="corpus/claude-code の意味検索")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("index", help="corpus を索引化する").add_argument(
        "--all", action="store_true", help="状態を無視して全ファイルを再構築する"
    )

    search_parser = sub.add_parser("search", help="意味検索する")
    search_parser.add_argument("query")
    search_parser.add_argument("--project", default=None, help="project 名で絞り込む")
    search_parser.add_argument("--limit", type=int, default=5, help="上位何件を返すか")

    sub.add_parser("serve", help="MCP サーバ(stdio)を起動する")

    return parser


def _build_service() -> RecallService:
    # FastEmbedEmbedder は import 時ではなくここで遅延生成する。
    # index/search/serve いずれかを実行する時点で初めて ONNX モデルに触れればよく、
    # build_parser 単体のテストが誤ってモデルへ依存しないようにするため。
    from recall.embedder import FastEmbedEmbedder

    store = Store(DB_PATH)
    embedder = FastEmbedEmbedder()
    return RecallService(store, embedder, hybrid_search=config.HYBRID_SEARCH)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "index":
        from recall.embedder import FastEmbedEmbedder

        store = Store(DB_PATH)
        embedder = FastEmbedEmbedder()
        stats = index_corpus(CORPUS_DIR, store, embedder, full=args.all)
        print(
            f"indexed={stats.indexed_files} skipped={stats.skipped_files} "
            f"pruned={stats.pruned_files} chunks_written={stats.chunks_written} "
            f"errors={stats.errors}"
        )
        store.close()
    elif args.command == "search":
        service = _build_service()
        hits = service.search(args.query, project=args.project, limit=args.limit)
        if not hits:
            print("該当なし")
        for i, hit in enumerate(hits, 1):
            print(f"{i}. [{hit.score:.3f}] {hit.id} ({hit.project})")
            print(f"  {hit.snippet}")
    elif args.command == "serve":
        service = _build_service()
        server = create_server(service)
        server.run()


if __name__ == "__main__":
    main()

"""recall コマンドのエントリポイント。実 Store/FastEmbedEmbedder を組み立てて注入する。

引数解析(build_parser)はネットワーク非依存の純粋ロジックなので単体テスト対象。
各サブコマンドの実行(main)は実際の SQLite ファイル・ONNX モデルに触れるため、
単体テストでは検証せずスモークテスト（実データ）で確認する（設計書 §14 と同じ理由）。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from recall import config
from recall.config import CORPUS_DIR, DB_PATH
from recall.indexer import index_corpus
from recall.server import build_transport_security, create_server
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

    serve_parser = sub.add_parser("serve", help="MCP サーバを起動する(既定 stdio)")
    # --http/--host/--port/--allowed-host は default=None のサンチネル（CLI 未指定）。
    # 既定値の解決（フラグ > env > 既定）は resolve_serve_settings が担う。
    serve_parser.add_argument(
        "--http",
        action="store_true",
        default=None,
        help="streamable-http で起動する(env RECALL_HTTP_ENABLED)",
    )
    serve_parser.add_argument(
        "--host",
        default=None,
        help="--http の bind ホスト。認証は無いので loopback か VPN 内 IP を指定する"
        "(env RECALL_HTTP_HOST、既定 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="--http の bind ポート(env RECALL_HTTP_PORT、既定 8768)",
    )
    serve_parser.add_argument(
        "--allowed-host",
        dest="allowed_host",
        action="append",
        default=None,
        help="DNS リバインディング保護の許可 Host を追加する(繰り返し可。"
        "host:port を指定。env RECALL_ALLOWED_HOSTS カンマ区切り)",
    )
    serve_parser.add_argument(
        "--stdio",
        action="store_true",
        help="env で HTTP が有効でも stdio を強制する(MCP クライアント登録の脱出口)",
    )

    return parser


def _build_service() -> RecallService:
    # FastEmbedEmbedder は import 時ではなくここで遅延生成する。
    # index/search/serve いずれかを実行する時点で初めて ONNX モデルに触れればよく、
    # build_parser 単体のテストが誤ってモデルへ依存しないようにするため。
    from recall.embedder import FastEmbedEmbedder

    store = Store(DB_PATH)
    embedder = FastEmbedEmbedder()
    return RecallService(store, embedder, hybrid_search=config.HYBRID_SEARCH)


_ALL_INTERFACES_HOSTS = frozenset({"0.0.0.0", "::"})


def _bind_warning(host: str) -> str | None:
    """--host が全インターフェース bind なら警告文を返す（意図しない公開への気付き）。"""
    if host not in _ALL_INTERFACES_HOSTS:
        return None
    return (
        "警告: 全インターフェースに bind します。VPN インターフェースの IP または "
        "127.0.0.1 (IPv6 の場合は ::1) を推奨します"
    )


@dataclass(frozen=True)
class ServeSettings:
    http: bool
    host: str
    port: int
    allowed_hosts: list[str]


def resolve_serve_settings(
    args: argparse.Namespace,
    *,
    env_http_enabled: bool,
    env_host: str,
    env_port: int,
    env_allowed_hosts: list[str],
) -> ServeSettings:
    """serve の起動設定を「--stdio > --http > env」の優先順位で解決する純関数。"""
    http = False if args.stdio else (args.http if args.http is not None else env_http_enabled)
    return ServeSettings(
        http=http,
        host=args.host if args.host is not None else env_host,
        port=args.port if args.port is not None else env_port,
        allowed_hosts=list(args.allowed_host) if args.allowed_host else list(env_allowed_hosts),
    )


def _run_server(server, settings: ServeSettings) -> None:
    if not settings.http:
        server.run()
        return
    # mcp SDK の DNS リバインディング保護は既定で localhost 系 Host しか許さないため、
    # bind 先自身（host:port と host）を許可し、別名でのアクセスは --allowed-host で足す。
    # IPv6 リテラルの Host ヘッダは `[::1]:8768` 形式なので、`:` を含む host はブラケットで包む。
    bind_host = f"[{settings.host}]" if ":" in settings.host else settings.host
    allowed_hosts = [f"{bind_host}:{settings.port}", bind_host, *settings.allowed_hosts]
    warning = _bind_warning(settings.host)
    if warning is not None:
        print(warning, file=sys.stderr)
    # mcp 2.x では host/port/transport_security は run() の引数。
    server.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        transport_security=build_transport_security(allowed_hosts),
    )


def _serve_settings(args: argparse.Namespace) -> ServeSettings:
    return resolve_serve_settings(
        args,
        env_http_enabled=config.HTTP_ENABLED,
        env_host=config.HTTP_HOST,
        env_port=config.HTTP_PORT,
        env_allowed_hosts=config.ALLOWED_HOSTS,
    )


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
        _run_server(create_server(service), _serve_settings(args))


if __name__ == "__main__":
    main()

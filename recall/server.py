"""MCP ツール memory_search / memory_get の薄いラッパ。

ロジックは一切持たず RecallService へ委譲する。Claude が明示的に呼んだ時だけ
実行されるため、フックによる自動注入と違って受動的なトークンコストがゼロになる
（設計書 §0 のスコープ方針）。
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Sequence

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from recall.service import RecallService


def build_transport_security(allowed_hosts: Sequence[str]) -> TransportSecuritySettings:
    """許可ホスト一覧から TransportSecuritySettings を組み立てる。

    cli.py は mcp を import しない方針のため、構築窓口をここに置く。allowed_origins は
    allowed_hosts から導出し、DNS リバインディング保護は VPN 境界内でも有効のままにする。
    """
    hosts = list(allowed_hosts)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{host}" for host in hosts],
    )


# クライアントへ MCP Server Instructions として届く使い分け。同名の memory_search /
# memory_get を持つ別 MCP が併用され得るため、別物だと短く伝える
# （全セッションに毎回載るため 1,500 字以内）。
INSTRUCTIONS = """\
Claude Code の過去セッション（corpus）の意味検索専用。読み取り専用。memory_search で候補を絞り、本文が必要な id だけ memory_get で読む。

同名の memory_search / memory_get を持つ別の MCP サーバーが併用されていても別物。ここで探せるのは「以前のセッションで何をしたか・どう直したか」だけで、対話由来の事実・決定・約束を残し読む用途には使わない。
"""


def create_server(service: RecallService) -> MCPServer:
    mcp = MCPServer("recall", instructions=INSTRUCTIONS)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        """systemd / 監視向けの死活確認。custom_route は Host 検査の外にあるため、
        返す情報はプロセス生存判定に要る status と version だけに絞る。
        """
        return JSONResponse({"status": "ok", "version": importlib.metadata.version("agent-recall")})

    @mcp.tool()
    def memory_search(query: str, project: str | None = None, limit: int = 5) -> list[dict]:
        """corpus/claude-code の過去セッションを意味検索する。

        本文全体は含まない軽量な結果(id/score/project/source_file/timestamp/snippet)を返す。
        本文が必要なら memory_get(id) を呼ぶこと。

        ハイブリッド検索の仕様: score は cosine 類似度で通常 0〜1 程度。結果の並び順は
        キーワード・セマンティック検索の RRF(Reciprocal Rank Fusion)統合順。
        ベクトル候補プール外のヒットは score が既定の 0.0 になる（低関連度の意味ではない）。
        関連度は並び順で判断すること。
        """
        hits = service.search(query, project=project, limit=limit)
        return [
            {
                "id": h.id,
                "score": h.score,
                "project": h.project,
                "source_file": h.source_file,
                "timestamp": h.timestamp,
                "snippet": h.snippet,
            }
            for h in hits
        ]

    @mcp.tool()
    def memory_get(id: str) -> dict | None:
        """memory_search で得た id を指定して、本文全体とメタデータを取得する。"""
        return service.get(id)

    return mcp

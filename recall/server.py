"""MCP ツール memory_search / memory_get の薄いラッパ。

ロジックは一切持たず RecallService へ委譲する。Claude が明示的に呼んだ時だけ
実行されるため、フックによる自動注入と違って受動的なトークンコストがゼロになる
（設計書 §0 のスコープ方針）。
"""

from __future__ import annotations

from mcp.server import MCPServer

from recall.service import RecallService


def create_server(service: RecallService) -> MCPServer:
    mcp = MCPServer("recall")

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

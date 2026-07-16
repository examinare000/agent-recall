"""MCP ツール memory_search / memory_get の単体テスト。

FastMCP.call_tool() は (content_blocks, {"result": <戻り値>}) を返すため、
"result" 側で戻り値の型・中身を検証する。ネットワーク・stdio 起動は行わない。
"""
from __future__ import annotations

import asyncio

import pytest

from recall.chunker import Chunk
from recall.server import create_server
from recall.service import RecallService
from recall.store import Store
from tests.fakes import FakeEmbedder


def _service_with_one_chunk(text: str = "本文" * 150) -> RecallService:
    store = Store(":memory:")
    embedder = FakeEmbedder()
    chunk = Chunk(
        id="a.jsonl#0", source_file="a.jsonl", project="proj",
        branch="main", timestamp="2026-01-01T00:00:00Z", text=text,
    )
    store.upsert_chunks([chunk], embedder.embed_documents([chunk.text]))
    return RecallService(store, embedder)


def _call(server, name: str, args: dict):
    return asyncio.run(server.call_tool(name, args))


class TestMemorySearch:
    def test_returns_lightweight_hits_without_full_text(self):
        service = _service_with_one_chunk()
        server = create_server(service)

        _, structured = _call(server, "memory_search", {"query": "本文"})
        hits = structured["result"]

        assert len(hits) == 1
        hit = hits[0]
        assert hit["id"] == "a.jsonl#0"
        assert "snippet" in hit
        assert "text" not in hit  # 本文全体を含めない(受動トークンコストを抑える設計)
        assert len(hit["snippet"]) <= 200


class TestMemoryGet:
    def test_returns_full_body_and_metadata_for_known_id(self):
        service = _service_with_one_chunk(text="全文はここに入る")
        server = create_server(service)

        _, structured = _call(server, "memory_get", {"id": "a.jsonl#0"})
        got = structured["result"]

        assert got["id"] == "a.jsonl#0"
        assert got["text"] == "全文はここに入る"

    def test_returns_none_for_unknown_id(self):
        service = _service_with_one_chunk()
        server = create_server(service)

        _, structured = _call(server, "memory_get", {"id": "does-not-exist"})

        assert structured["result"] is None


@pytest.mark.parametrize("tool_name", ["memory_search", "memory_get"])
def test_only_the_two_expected_tools_are_registered(tool_name):
    service = _service_with_one_chunk()
    server = create_server(service)

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}

    assert names == {"memory_search", "memory_get"}
    assert tool_name in names

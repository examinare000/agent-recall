"""JSONL 1ファイルのテキストをチャンク列へ変換する純粋関数群。

外部 I/O（ファイル読み込み・DB・embedding）を一切持たないため、
fixture の行リストだけで全パターンを高速に単体テストできる。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from recall.masking import SKIP_PREFIXES, extract_text, is_human_prompt, mask

MAX_CHARS = 1500
SEPARATOR = "\n\n---\n\n"


@dataclass(frozen=True)
class Chunk:
    id: str
    source_file: str
    project: str
    branch: str
    timestamp: str
    text: str


def chunk_session(lines: Iterable[str], source_file: str) -> list[Chunk]:
    """1セッション分の JSONL 行から、人間発話+直後 assistant 応答のペアを抽出する。

    「人間発話が境界」というルールのため、逐次スキャンしながら現在進行中の
    ペア（_current）を保持し、次の人間発話 or 終端で確定(flush)する2段構えにしている。
    """
    chunks: list[Chunk] = []
    current: dict | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        if is_human_prompt(d):
            if current is not None:
                _flush(current, source_file, chunks)
            current = _start_turn(d)
            continue

        if current is None:
            continue
        if d.get("type") == "assistant" and not d.get("isSidechain"):
            text = extract_text(d.get("message", {}).get("content"))
            if text:
                current["assistant_parts"].append(text)

    if current is not None:
        _flush(current, source_file, chunks)

    return chunks


def _start_turn(d: dict) -> dict | None:
    """人間発話行からチャンクの種を作る。SKIP対象ならNoneを返す(=進行中チャンクなし扱い)。"""
    text = extract_text(d.get("message", {}).get("content")).strip()
    if not text or len(text) < 2 or text.startswith(SKIP_PREFIXES):
        return None
    return {
        "human_text": text,
        "timestamp": d.get("timestamp", ""),
        "branch": d.get("gitBranch") or "-",
        "assistant_parts": [],
    }


def _flush(current: dict | None, source_file: str, chunks: list[Chunk]) -> None:
    if current is None:
        return
    # 順序が重要: 必ず mask を先に適用してから truncate する（distill/extract.py と同じ順）。
    # truncate を先にすると、1500字境界をまたぐ秘密情報がマスク用正規表現の必要長を
    # 満たせなくなり、生の断片が切り詰め後の本文に残ってしまう(情報漏洩)ため。
    human_text = mask(current["human_text"])[:MAX_CHARS]
    assistant_text = mask("\n".join(current["assistant_parts"]).strip())[:MAX_CHARS]
    body = human_text + SEPARATOR + assistant_text
    index = len(chunks)
    chunks.append(
        Chunk(
            id=f"{source_file}#{index}",
            source_file=source_file,
            project=Path(source_file).parent.name,
            branch=current["branch"],
            timestamp=current["timestamp"],
            text=body,
        )
    )

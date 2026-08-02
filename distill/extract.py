#!/usr/bin/env python3
"""Claude Code トランスクリプトから「人間が実際に打った発話」だけを抽出し、
蒸留用の圧縮ダイジェスト(Markdown)を出力する。

- 入力: ~/.claude/projects/**/*.jsonl
- 出力: distill/out/digest-<until>.md
- 状態: distill/.extract-state.json （最後に処理した timestamp を記録、増分処理）

ノイズ（skill/command 注入、ポリシー、サブエージェント内部、tool結果）は除外し、
資格情報らしき文字列はマスクする。蒸留(=嗜好抽出)は別途 Claude が SKILL.md 手順で行う。
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
STATE = HERE / ".extract-state.json"

# 1発話あたりの最大文字数（超過は切り詰め）。recall/chunker.py が同じ
# 切り詰め・マスク規約を共有するため、recall/masking.py 経由で
# この値を再エクスポートする（単一情報源化。目視同期での drift を防ぐ）。
MAX_CHARS = 1500

# 人間の発話ではない=除外するための先頭パターン
SKIP_PREFIXES = (
    "<command-", "<local-command-", "<bash-", "<system-reminder",
    "<user-prompt-submit-hook", "Base directory for this skill",
    "## Policy", "あなたは", "**既にレビューは完了",
    "Caveat:", "<attachment", "<task-",
    "[Request interrupted",
)
# 機微情報マスク（簡易）
SECRET_RES = [
    (re.compile(r'(sk-[A-Za-z0-9]{12,})'), '<REDACTED-KEY>'),
    (re.compile(r'(gh[pousr]_[A-Za-z0-9]{20,})'), '<REDACTED-TOKEN>'),
    (re.compile(r'(AKIA[0-9A-Z]{12,})'), '<REDACTED-AWS>'),
    # 値パターンはダブル/シングルクォート文字列全体（内部の \" \' エスケープを
    # 許容）を \S+ より優先して試す。`password: "hunter 2 with spaces"` の
    # ような複数語のクォート値が先頭1トークンだけしかマスクされない過少マスク
    # を防ぐため（クォートが閉じていない場合は安全側に倒し、従来どおり \S+ で
    # 先頭トークンのみをマスクする劣化にとどめる）。
    #
    # body から \n を除外するのは、閉じクォートが数行下の別ラベル行にしか
    # 現れない入力で無関係な複数行を丸ごと飲み込んで消してしまうのを防ぐため
    # （各行は独立して判定され、閉じられない側は \S+ にフォールバックする）。
    # 閉じ直後に (?!\S)（次が非空白なら不採用）を置くのは、`""hunter2"` や
    # 3連続クォートのように値が空/複数個のクォート文字で始まる入力で「早期に
    # 閉じた」と誤認して後続語を露出させる短勝ちマッチを弾き、\S+ フォールバック
    # 側で旧実装（\S+ のみ）と同等以上の安全性を保つため。
    (re.compile(
        r'(?i)(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*'
        r'(?:"(?:\\.|[^"\\\n])*"(?!\S)|\'(?:\\.|[^\'\\\n])*\'(?!\S)|\S+)'
    ), r'\1=<REDACTED>'),
    (re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}'),
     '<REDACTED-JWT>'),
]


def mask(text: str) -> str:
    for rx, repl in SECRET_RES:
        text = rx.sub(repl, text)
    return text


def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content
                 if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(parts)
    return ""


def is_human_prompt(d: dict) -> bool:
    if d.get("type") != "user":
        return False
    if "toolUseResult" in d:           # tool結果
        return False
    if d.get("isSidechain"):           # サブエージェント内部
        return False
    return d.get("userType") in (None, "external")


def atomic_write_text(path: Path, text: str) -> None:
    """path への書き込みを一時ファイル+rename で原子化する。

    launchd の定期実行と手動実行が並走し得るため、固定名の .tmp は使わず
    tempfile.mkstemp で衝突しない一時ファイル名を採る。os.replace は同一
    ファイルシステム内でアトミックなので、書き込み途中でクラッシュしても
    path の既存内容は無傷のまま残る。

    mkstemp 由来で書き込み後のパーミッションは 0600 になる（従来の
    write_text の 0644 から意図的に変更 — 出力は mask 漏れの機微情報を
    含み得るローカル専用ファイルのため、絞る方向を許容する）。
    """
    import os
    import tempfile

    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"last_ts": ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None,
                    help="ISO timestamp。未指定なら状態ファイルの続きから")
    ap.add_argument("--all", action="store_true", help="状態を無視して全件")
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS,
                    help="1発話の最大文字数（超過は切り詰め）")
    args = ap.parse_args()

    state = load_state()
    since = "" if args.all else (args.since or state.get("last_ts", ""))

    rows = []           # (timestamp, project, branch, text)
    max_ts = since
    for f in glob.glob(str(PROJECTS / "**" / "*.jsonl"), recursive=True):
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not is_human_prompt(d):
                        continue
                    ts = d.get("timestamp", "")
                    if since and ts <= since:
                        continue
                    text = extract_text(d.get("message", {}).get("content")).strip()
                    if not text:
                        continue
                    if text.startswith(SKIP_PREFIXES):
                        continue
                    if len(text) < 2:
                        continue
                    text = mask(text)
                    if len(text) > args.max_chars:
                        text = text[:args.max_chars] + " …(truncated)"
                    proj = Path(f).parent.name
                    branch = d.get("gitBranch", "") or "-"
                    rows.append((ts, proj, branch, text))
                    max_ts = max(max_ts, ts)
        except OSError:
            continue

    rows.sort(key=lambda r: r[0])
    OUT_DIR.mkdir(exist_ok=True)
    until = (max_ts or "all")[:10] or "all"
    out = OUT_DIR / f"digest-{until}.md"

    lines = [f"# 発話ダイジェスト (since={since or 'BEGIN'} → {max_ts or 'END'})",
             f"\n抽出件数: {len(rows)} 発話\n",
             ("蒸留手順は distill/SKILL.md を参照。"
              "下記はノイズ除去済みの人間発話のみ。\n")]
    cur = None
    for ts, proj, branch, text in rows:
        head = f"{proj} [{branch}]"
        if head != cur:
            lines.append(f"\n## {head}\n")
            cur = head
        lines.append(f"- `{ts[:16]}` {text}")
    atomic_write_text(out, "\n".join(lines))

    if not args.all and max_ts:
        atomic_write_text(STATE, json.dumps({"last_ts": max_ts}, ensure_ascii=False))

    print(f"wrote {out}  ({len(rows)} prompts, until {max_ts or 'END'})")


if __name__ == "__main__":
    main()

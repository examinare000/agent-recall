#!/usr/bin/env bash
# SessionEnd フック: 終了したセッションのトランスクリプトを corpus/ にアーカイブする。
# 蓄積層[1]の自動化。stdin で受け取る JSON から transcript_path / cwd を読む。
#
# 設計方針:
# - 破壊的操作はしない（コピーのみ、元ログには触れない）。
# - corpus/ の中身は .gitignore 済みなのでリポジトリは肥大しない。
# - フックは絶対に失敗してセッションを妨げない（エラーでも exit 0）。
# - jq があれば使い、無ければ python3 にフォールバック。
set -u

# 標準パス規約。カスタマイズが必要な場合、環境変数で上書き可能。
CORPUS="${CORPUS_DIR:-$HOME/.claude/corpus}/claude-code"
LOG="${CORPUS_DIR:-$HOME/.claude/corpus}/.archive.log"

# --- stdin の JSON から値を取り出す ---
payload="$(cat 2>/dev/null || true)"

get_field() {
  local field="$1"
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$payload" | jq -r ".${field} // empty" 2>/dev/null
  else
    printf '%s' "$payload" | python3 -c "import sys,json;
try:
    d=json.load(sys.stdin); print(d.get('$field','') or '')
except Exception:
    print('')" 2>/dev/null
  fi
}

transcript="$(get_field transcript_path)"
session="$(get_field session_id)"
cwd="$(get_field cwd)"

# transcript が取れない / 実在しなければ静かに終了
[ -n "$transcript" ] && [ -f "$transcript" ] || exit 0

# プロジェクト名 = transcript の親ディレクトリ名（~/.claude/projects/<proj>/<uuid>.jsonl）
proj="$(basename "$(dirname "$transcript")")"
dest_dir="$CORPUS/$proj"
mkdir -p "$dest_dir" 2>/dev/null || exit 0

# コピー（同名は上書き＝最新の完全な記録で更新）
cp -f "$transcript" "$dest_dir/" 2>/dev/null || exit 0

ts="$(date '+%Y-%m-%dT%H:%M:%S')"
printf '%s\tarchived\t%s\t%s\n' "$ts" "$proj" "$(basename "$transcript")" >> "$LOG" 2>/dev/null

# recall 索引のインクリメンタル更新（検索層[2]の自動化）。
# アーカイブ直後に非同期で回すことで「蓄積は自動・検索可能化は手動」のギャップを塞ぐ。
# バックグラウンド & 失敗無視でセッション終了を一切ブロックしない。
# pgrep ガード: 近接する複数セッション終了で index が多重起動すると単一 sqlite への
# 書き込みが競合し得るため、既に走っていればスキップする（次回終了時に再試行される。
# ガードをすり抜けても失敗は無害で、索引はインクリメンタルに自己回復する）。
# recall リポジトリのパス。デフォルトはホーム配下の .local/share/claude/recall を想定。
RECALL_REPO="${RECALL_DIR:-$HOME/.local/share/claude/recall}"
if command -v uv >/dev/null 2>&1 && [ -d "$RECALL_REPO" ] && ! pgrep -f "recall index" >/dev/null 2>&1; then
  nohup uv run --directory "$RECALL_REPO" recall index \
    >/dev/null 2>&1 &
fi

exit 0

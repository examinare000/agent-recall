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

# plugin配布時の利用者設定（RECALL_CORPUS_DIR・RECALL_DIR 等の上書き）を
# ~/.claude/agent-recall/config.env に置けるようにし、存在すれば読み込む
# （plugin cache の外に置くことで plugin 更新でも消えない）。壊れていても
# フックを失敗させない（フックは絶対に失敗してセッションを妨げない方針を踏襲）。
CONFIG_ENV="$HOME/.claude/agent-recall/config.env"
if [ -f "$CONFIG_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_ENV" 2>/dev/null || true
  set +a
fi

# 標準パス規約。カスタマイズが必要な場合、環境変数で上書き可能。
# 正規名は RECALL_CORPUS_DIR（recall/config.py・check-setup.sh・commands/setup.md と統一）。
# 旧 CORPUS_DIR は非推奨フォールバックとして残す（既存 config.env との後方互換のため）。
CORPUS="${RECALL_CORPUS_DIR:-${CORPUS_DIR:-$HOME/.claude/corpus}}/claude-code"
LOG="${RECALL_CORPUS_DIR:-${CORPUS_DIR:-$HOME/.claude/corpus}}/.archive.log"

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
# recall リポジトリのパス。解決順: RECALL_DIR(明示上書き) > CLAUDE_PLUGIN_ROOT
# (プラグイン専用導入時にClaude Codeが自動設定するプラグイン本体のルート) > 既定の
# ホーム配下 .local/share/claude/recall（手動clone運用を想定した既定値）。
RECALL_REPO="${RECALL_DIR:-${CLAUDE_PLUGIN_ROOT:-$HOME/.local/share/claude/recall}}"
if command -v uv >/dev/null 2>&1 && [ -d "$RECALL_REPO" ] && ! pgrep -f "recall index" >/dev/null 2>&1; then
  nohup uv run --directory "$RECALL_REPO" recall index \
    >/dev/null 2>&1 &
fi

exit 0

#!/usr/bin/env bash
# 週次蒸留ランナー（launchd から起動）。
# 蓄積層のログから増分ダイジェストを生成し、新規発話があれば通知する。
#
# 設計方針:
# - 嗜好抽出・memory保存は人手レビューのまま（distill/SKILL.md）。本スクリプトは
#   「ダイジェスト生成 + リマインド」までを自動化する。半自動の意図的な線引き。
# - recall の意味検索索引は週次で corpus に追従させる。これは検索基盤の鮮度維持であり、
#   memory への自動反映ではない。
# - 失敗してもシステムを妨げない。
set -u

# recall リポジトリのパス。launchd plist 配置時に、下記の RECALL_DIR を環境変数化するか、
# スクリプト内でハードコードしてください。デフォルトは ~/.local/share/claude/recall（例）を想定。
REPO="${RECALL_DIR:-$HOME/.local/share/claude/recall}"
PY="$(command -v python3 || echo /usr/bin/python3)"
# launchd の PATH には homebrew が含まれないため絶対パスへフォールバック。
# Apple Silicon (/opt/homebrew) と Intel (/usr/local) の両方を見る。
UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  if [ -x /opt/homebrew/bin/uv ]; then
    UV=/opt/homebrew/bin/uv
  elif [ -x /usr/local/bin/uv ]; then
    UV=/usr/local/bin/uv
  else
    UV=/opt/homebrew/bin/uv
  fi
fi
LOG="$REPO/distill/.weekly.log"
ts="$(date '+%Y-%m-%dT%H:%M:%S')"

cd "$REPO" 2>/dev/null || { echo "$ts\tERROR\tno repo" >> "$LOG"; exit 0; }

log_line() {
  printf '%s\t%s\t%s\n' "$ts" "$1" "$2" >> "$LOG" 2>/dev/null || true
}

run_recall_index() {
  if [ ! -x "$UV" ]; then
    log_line "index" "skipped uv_not_found=$UV"
    return 0
  fi
  if [ ! -d "$REPO/recall" ]; then
    log_line "index" "skipped recall_dir_not_found=$REPO/recall"
    return 0
  fi

  idx="$("$UV" run --directory "$REPO" recall index 2>&1)"
  status=$?
  if [ "$status" -eq 0 ]; then
    log_line "index" "ok $idx"
  else
    log_line "index" "failed status=$status $idx"
    # recall索引の鮮度劣化は検索品質に波及するため、スマホ通知を送信したい場合は
    # notify.sh を別途配置して呼び出してください（notify.shはopt-in・fail-open）。
    # タイトルはASCII固定（HTTPヘッダの非ASCII文字化け/拒否リスク回避）、
    # 日本語詳細はHTTPボディ側のmessageに寄せる。notify.sh呼出自体が失敗しても
    # （権限剥奪等でexit 127等になっても）本体ジョブを妨げないよう || true を付ける。
    # Example: $(dirname "$0")/notify.sh "weekly-distill" "recall index失敗 status=$status" high warning || true
  fi
  return 0
}

# 増分でダイジェスト生成。出力例: "wrote .../digest-2026-06-29.md  (12 prompts, until ...)"
out="$("$PY" distill/extract.py 2>&1)"
extract_status=$?
if [ "$extract_status" -ne 0 ]; then
  log_line "run" "failed status=$extract_status $out"
  # スマホ通知を送信したい場合は notify.sh を別途呼び出してください
  # Example: $(dirname "$0")/notify.sh "weekly-distill" "extract失敗 status=$extract_status" high warning || true
  n=0
else
  n="$(printf '%s' "$out" | grep -oE '\(([0-9]+) prompts' | grep -oE '[0-9]+' | head -1)"
  n="${n:-0}"
  log_line "run" "new_prompts=$n $out"
fi

# recall の意味検索索引を corpus の増分に追従させる（失敗しても週次蒸留は妨げない）。
run_recall_index

# 新規発話があればデスクトップ通知でレビューを促す（嗜好抽出は人手）。
# デスクトップ通知は離席時に届かないため、スマホ通知も併用する場合は notify.sh を配置してください。
if [ "$n" -gt 0 ] 2>/dev/null; then
  /usr/bin/osascript -e "display notification \"新規${n}発話。distill/SKILL.md で蒸留レビューを実行してください\" with title \"recall 週次蒸留\"" >/dev/null 2>&1 || true
  # スマホ通知を送信したい場合は notify.sh を別途呼び出してください
  # Example: $(dirname "$0")/notify.sh "weekly-distill" "新規${n}発話。蒸留レビューをお願いします" default || true
fi

exit 0

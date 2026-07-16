#!/usr/bin/env bash
# retrospect 実行ラッパー（launchd から起動）。
#
# WHY: 週次retrospectはremote controlに紐づかない `claude -p` 無人実行のため、
# 失敗・完了をplistのコマンド行に埋め込んだままだと検知できない。ntfy通知呼出を
# ラッパースクリプトへ分離することで、plistのProgramArgumentsを直接テストできない
# 制約を回避しつつ、成功/失敗の両経路をシェルテストで検証可能にする。
#
# allowedTools の内容は元のplist（com.example.recall.retrospect.plist）からそのまま
# 移設したもの。追加・削除する場合は ~/.claude/rules/94-self-improvement-protocol.md の
# 無人実行権限設計の見直しとセットで行うこと。
#
# 権限最小化（2026-07-15 レビュー反映）:
# 旧allowedToolsにあった Bash(grep:*) はパス無制限で ~/.claude・profile・corpus
# 等の私有データへ到達できてしまい、同居する git push / gh pr create（PR送信）と
# acceptEdits の組み合わせで lethal trifecta（未信頼入力→秘匿データ読取→外部送信）
# が無人実行内で成立し得た。retrospect SKILL側の類似照合は権限不要のGrepツールへ
# 移行済み（agentDevTemplate feature/p3-quarantine-adt）のため、Bash grep 許可は
# 不要になり削除する。あわせて --disallowedTools で、無人ジョブへの未信頼コンテンツ
# 流入経路になり得るWeb系（WebFetch/WebSearch）と、Step本文で不要な私有MCP
# （gemini/vault/shelf）への到達を明示的に剥奪する。recall（mcp__recall__*）は
# Step 2のmemory_searchに必要なため disallow に含めない。
#
# cd fail-close（2026-07-15 レビュー反映）:
# 旧plist（cd "$REPO" && claude ...）はcd失敗時にclaudeを起動しないfail-fastだった。
# ラッパー化した際に `cd "$REPO" 2>/dev/null || true` としてしまうと、cd失敗時も
# 無条件でclaudeがacceptEditsのまま意図しないCWDから走ってしまう（fail-open）。
# 兄弟の distill/weekly-distill.sh も `cd || { log; exit }` でfail-closeにして
# いるため、それと揃え、cd失敗時はclaudeを起動せずnotify.shで失敗通知しexit 1する。
#
# 通知タイトルはASCII固定（2026-07-15 レビュー反映）: HTTPヘッダ（Title:）に
# 非ASCII文字を載せるとntfy側での文字化け・拒否リスクが未検証のため、タイトルは
# ASCIIにし、日本語は本文（HTTPボディ）側に寄せる。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# RUN_RETROSPECT_REPO_OVERRIDE はテスト専用の差し替えフック
# （bootstrap.shの*_NO_MAINガードと同じ位置づけ。未設定時は本番と同じ挙動）。
# SCRIPT_DIR/.. は script自身の物理位置から導出するため通常のcdでは失敗しないが、
# cd失敗時のfail-close分岐をテストで確実に踏むために存在する。
REPO="${RUN_RETROSPECT_REPO_OVERRIDE:-$SCRIPT_DIR/..}"

# RECALL_REPO はlaunchd plist内で環境変数として設定してください（デフォルト: ~/.local/share/claude/recall 等）
# または下記のパスを sed で置換して導入してください。
RECALL_REPO="${RECALL_REPO:-$HOME/.local/share/claude/recall}"
CORPUS_DIR="${CORPUS_DIR:-$HOME/.claude/corpus}"
LESSONS_DIR="${LESSONS_DIR:-$HOME/.claude/lessons}"

ALLOWED_TOOLS="Bash(git push:*),Bash(gh pr create:*),Bash(gh pr list:*),Bash(gh pr view:*),Bash(uv run --directory ${RECALL_REPO}:*),Bash(uv run --directory ${RECALL_REPO}:*),Bash(find ${CORPUS_DIR}:*),Bash(find ${CORPUS_DIR}:*),Bash(mv ${LESSONS_DIR}:*),Bash(mv ${LESSONS_DIR}:*)"
DISALLOWED_TOOLS="WebFetch,WebSearch,mcp__gemini__ask-gemini,mcp__gemini__brainstorm,mcp__gemini__fetch-chunk,mcp__gemini__ping,mcp__gemini__Help,mcp__vault__vault_search,mcp__vault__vault_get,mcp__shelf__consult,mcp__shelf__ask,mcp__shelf__list_notebooks"

if ! cd "$REPO" 2>/dev/null; then
  # notify.sh を別途配置している場合は以下でコメントアウトを外してください
  # $(dirname "$0")/notify.sh "retrospect FAILED" "cd to repo failed: $REPO" high warning || true
  exit 1
fi

start_ts="$(date +%s)"
claude --model claude-opus-4-8 --permission-mode acceptEdits --allowedTools "$ALLOWED_TOOLS" --disallowedTools "$DISALLOWED_TOOLS" -p "/retrospect"
rc=$?
end_ts="$(date +%s)"
elapsed_min=$(( (end_ts - start_ts) / 60 ))

# notify.sh を別途配置している場合は以下でコメントアウトを外してください
# if [ "$rc" -eq 0 ]; then
#   $(dirname "$0")/notify.sh "retrospect done" "rc=0 ${elapsed_min}m" default white_check_mark || true
# else
#   $(dirname "$0")/notify.sh "retrospect FAILED" "rc=$rc ${elapsed_min}m" high warning || true
# fi

exit "$rc"

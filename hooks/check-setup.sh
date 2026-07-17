#!/usr/bin/env bash
# SessionStart フック(matcher: startup): agent-recall プラグインが未セットアップの場合
# additionalContext で /agent-recall:setup の実行を促す。
#
# 設計方針:
# - 判定に失敗してもセッション開始を妨げない（常に exit 0。fail-open）。
# - AGENT_RECALL_HOME を環境変数で上書き可能にする（テストが実 ~/.claude/ に
#   触れず隔離した一時ディレクトリで検証できるようにするため。archive-session.sh の
#   CORPUS_DIR・weekly-distill.sh の RECALL_DIR と同じ上書き規約）。
set -u

AGENT_RECALL_HOME="${AGENT_RECALL_HOME:-$HOME/.claude/agent-recall}"
CONFIG_ENV="$AGENT_RECALL_HOME/config.env"
SETUP_JSON="$AGENT_RECALL_HOME/setup.json"

# config.env があれば読み込む(壊れていてもフックを失敗させない)。
if [ -f "$CONFIG_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_ENV" 2>/dev/null || true
  set +a
fi

# 既定値は ~/.claude/corpus/claude-code の親（コーパスの受け皿ディレクトリそのものが
# 用意されているか、という粗い存在確認のため）。
RECALL_CORPUS_DIR="${RECALL_CORPUS_DIR:-$HOME/.claude/corpus}"

needs_setup=0
[ -f "$SETUP_JSON" ] || needs_setup=1
[ -d "$RECALL_CORPUS_DIR" ] || needs_setup=1

if [ "$needs_setup" -eq 1 ]; then
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"agent-recall プラグインは未設定です。/agent-recall:setup を実行するとメモリ保持形式と蒸留方法を対話設定できます。"}}'
fi

exit 0

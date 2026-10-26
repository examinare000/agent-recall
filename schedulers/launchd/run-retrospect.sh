#!/usr/bin/env bash
# retrospect 実行ラッパー（launchd から起動）。
#
# WHY: 週次retrospectはremote controlに紐づかない `claude -p` 無人実行のため、
# 失敗・完了をplistのコマンド行に埋め込んだままだと検知できない。ラッパースクリプト
# へ分離することで、plistのProgramArgumentsを直接テストできない制約を回避しつつ、
# 成功/失敗の両経路をシェルテストで検証可能にする。失敗は終了コードと stderr で
# 可視化する（通知が必要なら launchd の StandardErrorPath を監視するか、末尾の rc を
# 見て任意の通知コマンドを呼ぶ）。
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
# （gemini/vault/shelf）への到達を明示的に剥奪する。
#
# MCP の allow: 「disallow に含めない」は「使える」ではない。headless の acceptEdits では
# MCP ツールは自動承認されず、allowedTools に無ければ拒否される（実測: permission_denials
# に載る）。Step 2 の類似照合に必要な recall の memory_search / memory_get を、user-scope
# 登録名とプラグイン導入名の両方で allowedTools に載せる。
#
# 権限拒否の fail-close: 権限拒否は迂回で吸収され rc=0 で完走する（実測: recall の照合が
# 毎サイクル拒否されたまま成功扱いだった）。--output-format json の permission_denials を
# 親が読み、拒否があれば exit 1 にする。
#
# cd fail-close（2026-07-15 レビュー反映）:
# 旧plist（cd "$REPO" && claude ...）はcd失敗時にclaudeを起動しないfail-fastだった。
# ラッパー化した際に `cd "$REPO" 2>/dev/null || true` としてしまうと、cd失敗時も
# 無条件でclaudeがacceptEditsのまま意図しないCWDから走ってしまう（fail-open）。
# 兄弟の distill/weekly-distill.sh も `cd || { log; exit }` でfail-closeにして
# いるため、それと揃え、cd失敗時はclaudeを起動せずstderrに失敗を記録してexit 1する。
set -u

# launchd 無人実行の環境固定:
# - launchd はログインシェルの PATH を引き継がないため、claude / uv / git の置き場所
#   （~/.local/bin、Homebrew）を明示する。~/.local/bin を /opt/homebrew/bin より前に
#   置くのは、brew の python3 が uv の既定 python3 を隠さないようにするため。
# - RUN_RETROSPECT_PATH_OVERRIDE はテスト専用の差し替えフック（他の *_OVERRIDE と同じ
#   位置づけ。未設定時は本番と同じ固定 PATH）。これが無いと、この export が呼び出し側の
#   PATH を捨てるため stub の claude に到達できず、テストが実 claude を acceptEdits で
#   起動してしまう。
export PATH="${RUN_RETROSPECT_PATH_OVERRIDE:-$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

# 実行中のアイドルスリープ抑止（macOS のみ。caffeinate が無い環境では何もしない）。
# -w $$ でこのスクリプトの終了と同時に解除される。蓋閉じによる強制スリープまでは防げない。
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -im -w $$ &
fi

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

# 各エントリは1回のみ列挙する。旧repoでは「~ 表記」と「絶対パス表記」の両方を
# 許可リストに並べる設計だったため重複エントリが必要だったが、上記の変数化で
# 実行時に解決済みの1パスのみが埋め込まれるようになり、その設計は不要になった。
ALLOWED_TOOLS="mcp__recall__memory_search,mcp__recall__memory_get,mcp__plugin_agent-recall_recall__memory_search,mcp__plugin_agent-recall_recall__memory_get,Bash(git push:*),Bash(gh pr create:*),Bash(gh pr list:*),Bash(gh pr view:*),Bash(uv run --directory ${RECALL_REPO}:*),Bash(find ${CORPUS_DIR}:*),Bash(mv ${LESSONS_DIR}:*)"
DISALLOWED_TOOLS="WebFetch,WebSearch,mcp__gemini__ask-gemini,mcp__gemini__brainstorm,mcp__gemini__fetch-chunk,mcp__gemini__ping,mcp__gemini__Help,mcp__vault__vault_search,mcp__vault__vault_get,mcp__shelf__consult,mcp__shelf__ask,mcp__shelf__list_notebooks"

# 上で遮断した MCP サーバーは、プラグイン経由で入ると名前が
# mcp__plugin_<plugin>_<server>__<tool> に変わり、上の名前では剥奪できない。
# 同じ遮断対象をプラグイン名（plugin 名 = server 名の一般的な配布形）でも剥奪する。
# recall 自身（mcp__plugin_recall_recall__*）は Step 2 の memory_search に必要なので、
# 元の遮断対象に含まれない限りここでも遮断されない。
# 外部コマンド(tr/sed/paste)に依存せず bash の parameter expansion だけで組む
# （PATH を固定/隔離した状態でも動かすため）。
PLUGIN_DISALLOWED_TOOLS=""
_rest="$DISALLOWED_TOOLS"
while [ -n "$_rest" ]; do
  _name="${_rest%%,*}"
  if [ "$_rest" = "$_name" ]; then _rest=""; else _rest="${_rest#*,}"; fi
  case "$_name" in
    mcp__*__*)
      _server="${_name#mcp__}"; _server="${_server%%__*}"
      _tool="${_name#mcp__"${_server}"__}"
      PLUGIN_DISALLOWED_TOOLS="${PLUGIN_DISALLOWED_TOOLS:+$PLUGIN_DISALLOWED_TOOLS,}mcp__plugin_${_server}_${_server}__${_tool}"
      ;;
  esac
done
DISALLOWED_TOOLS="$DISALLOWED_TOOLS,$PLUGIN_DISALLOWED_TOOLS"

if ! cd "$REPO" 2>/dev/null; then
  # notify.sh を別途配置している場合は以下でコメントアウトを外してください
  # $(dirname "$0")/notify.sh "retrospect FAILED" "cd to repo failed: $REPO" high warning || true
  exit 1
fi

# claude 解決のフォールバック: claude CLI の自動更新中は ~/.local/bin/claude の
# symlink が一時的に懸垂となり PATH 解決に失敗する（週次実行が
# `claude: command not found` で不成立になる）。symlink が懸垂でも versions/ 直下には
# 実体が残るため、PATH で解決できないときは mtime 最新の実体へフォールバックする。
# それも無い場合は claude を起動せず exit 127（fail-close）。
# RUN_RETROSPECT_VERSIONS_DIR_OVERRIDE はテスト専用の差し替えフック。
CLAUDE_BIN="$(command -v claude || true)"
if [ -z "$CLAUDE_BIN" ]; then
  VERSIONS_DIR="${RUN_RETROSPECT_VERSIONS_DIR_OVERRIDE:-$HOME/.local/share/claude/versions}"
  # shellcheck disable=SC2012  # mtime 順の先頭 1 件が欲しいだけで、ファイル名は版番号
  latest="$(ls -t "$VERSIONS_DIR" 2>/dev/null | head -n1)"
  if [ -n "$latest" ] && [ -x "$VERSIONS_DIR/$latest" ]; then
    CLAUDE_BIN="$VERSIONS_DIR/$latest"
  fi
fi
if [ -z "$CLAUDE_BIN" ]; then
  echo "claude not found in PATH and no fallback in versions dir" >&2
  exit 127
fi

# 結果 JSON の置き場。stdout に JSON の生出力を流さず、応答本文だけをログへ戻す。
RESULT_JSON="$(mktemp "${TMPDIR:-/tmp}/run-retrospect.XXXXXX")" || exit 1
trap 'rm -f "$RESULT_JSON"' EXIT

start_ts="$(date +%s)"
"$CLAUDE_BIN" --model opus --permission-mode acceptEdits --allowedTools "$ALLOWED_TOOLS" --disallowedTools "$DISALLOWED_TOOLS" --output-format json -p "/retrospect" >"$RESULT_JSON"
rc=$?
end_ts="$(date +%s)"
elapsed_min=$(( (end_ts - start_ts) / 60 ))

if [ "$rc" -ne 0 ]; then
  echo "FAIL: retrospect rc=$rc ${elapsed_min}m" >&2
  exit "$rc"
fi

# 従来 stdout に流れていた応答本文は result フィールドから復元してログへ残す。読めなければ何も出さない。
python3 - "$RESULT_JSON" <<'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as f:
        result = json.load(f)
except (OSError, ValueError):
    raise SystemExit(0)
if isinstance(result, dict) and isinstance(result.get("result"), str):
    print(result["result"])
PY

# 権限拒否の fail-close: permission_denials に 1 件でもあれば失敗にする。
# JSON を読めない場合も「拒否なし」とは言えないので失敗にする（exit 3 で区別して報告）。
denied_rc=0
denied_tools="$(python3 - "$RESULT_JSON" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as f:
        result = json.load(f)
except (OSError, ValueError):
    raise SystemExit(3)
if not isinstance(result, dict):
    raise SystemExit(3)
denials = result.get("permission_denials")
if denials is None:
    denials = []
if not isinstance(denials, list):
    raise SystemExit(3)
names = sorted({str(d.get("tool_name", "?")) for d in denials if isinstance(d, dict)})
print(",".join(names))
PY
)" || denied_rc=$?
if [ "$denied_rc" -ne 0 ]; then
  echo "FAIL: retrospect result JSON is not parseable (rc=$denied_rc)" >&2
  exit 1
fi
if [ -n "$denied_tools" ]; then
  echo "FAIL: retrospect permission denied tools=$denied_tools" >&2
  exit 1
fi

echo "retrospect done rc=0 ${elapsed_min}m"
exit 0

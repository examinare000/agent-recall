#!/usr/bin/env bash
# run-retrospect.sh のスモークテスト。
#
# なぜ実 claude を一切使わないのか:
# run-retrospect.sh は `claude -p /retrospect` を acceptEdits で無人起動する。テストが
# 実 claude に到達すると実データを書き換え得るため、PATH を隔離した stub ディレクトリ
# だけに固定する（RUN_RETROSPECT_PATH_OVERRIDE。これが無いとスクリプト内の固定 PATH が
# 呼び出し側の PATH を捨て、stub に到達できない）。
#
# なぜ「bare PATH」を作るのか:
# macOS では /usr/bin/caffeinate が実在するため、/usr/bin を PATH に含めると
# 「caffeinate が無い環境」を再現できない。スクリプトが必要とする最小コマンドだけを
# symlink した bare ディレクトリを PATH にして、不在時の分岐を検証する。
#
# なぜ bash 3.2 (/bin/bash) で実行するのか:
# 他のシェルテストと同様、PATH 解決に依存せず macOS 標準の /bin/bash を固定で使う。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
TARGET_SH="$SCRIPT_DIR/run-retrospect.sh"
BASH_BIN="/bin/bash"
if [ ! -x "$BASH_BIN" ]; then
  echo "エラー: $BASH_BIN が見つかりません" >&2
  exit 1
fi

pass=0
fail=0

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# $1: label, $2: expected, $3: actual
assert_rc() {
  local label="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    echo "PASS: $label (exit=$actual)"
    pass=$((pass + 1))
  else
    echo "FAIL: $label (expected exit=$expected actual=$actual)"
    fail=$((fail + 1))
  fi
}

# $1: label, $2: 全体の文字列, $3: 含まれるべき文字列
assert_contains() {
  local label="$1" output="$2" needle="$3"
  if printf '%s' "$output" | grep -qF -- "$needle"; then
    echo "PASS: $label"
    pass=$((pass + 1))
  else
    echo "FAIL: $label (needle not found: $needle)"
    printf '%s\n' "$output" | sed 's/^/  /'
    fail=$((fail + 1))
  fi
}

# 隔離ケースを作る。$1: case_dir, $2: claude stub を bin に置くか (yes|no)
# bin/ には claude / caffeinate の stub、bare/ には必要最小限の実コマンドの symlink を置く。
# stub claude は受け取った引数を args.txt に 1 行 1 引数で記録し、CLAUDE_STUB_RC で終了する。
setup_case() {
  local case_dir="$1" with_claude="$2" cmd real
  mkdir -p "$case_dir/repo" "$case_dir/bin" "$case_dir/bare" "$case_dir/versions"
  for cmd in dirname date ls head mktemp rm python3; do
    real="$(command -v "$cmd")"
    ln -s "$real" "$case_dir/bare/$cmd"
  done
  if [ "$with_claude" = "yes" ]; then
    write_claude_stub "$case_dir/bin/claude" "$case_dir/args.txt"
  fi
  cat > "$case_dir/bin/caffeinate" <<STUBEOF
#!/bin/sh
echo called >> "$case_dir/caffeinate.txt"
STUBEOF
  chmod +x "$case_dir/bin/caffeinate"
}

# $1: 出力先パス, $2: 引数の記録先
write_claude_stub() {
  cat > "$1" <<STUBEOF
#!/bin/sh
for a in "\$@"; do printf '%s\n' "\$a"; done > "$2"
# --output-format json の結果を模す。CLAUDE_STUB_JSON が設定されていればその値を、無ければ拒否なしの既定 JSON を出す。
if [ -n "\${CLAUDE_STUB_JSON+x}" ]; then printf '%s\n' "\$CLAUDE_STUB_JSON"; else printf '%s\n' '{"result":"stub ok","permission_denials":[]}'; fi
exit "\${CLAUDE_STUB_RC:-0}"
STUBEOF
  chmod +x "$1"
}

# $1: case_dir, $2: PATH override に使う値。stderr は $case_dir/stderr.txt に残す。
run_case() {
  local case_dir="$1" path_value="$2"
  RUN_RETROSPECT_PATH_OVERRIDE="$path_value" \
    RUN_RETROSPECT_REPO_OVERRIDE="$case_dir/repo" \
    RUN_RETROSPECT_VERSIONS_DIR_OVERRIDE="$case_dir/versions" \
    "$BASH_BIN" "$TARGET_SH" >"$case_dir/stdout.txt" 2>"$case_dir/stderr.txt"
}

# (a) PATH override が効き、PATH 上の stub claude が起動される
case_dir="$WORKDIR/a"
setup_case "$case_dir" yes
rc=0
run_case "$case_dir" "$case_dir/bin:$case_dir/bare" || rc=$?
assert_rc "(a) PATH override 先の stub claude が起動され rc=0 を引き継ぐ" 0 "$rc"
args="$(cat "$case_dir/args.txt" 2>/dev/null || true)"
assert_contains "(a) /retrospect を非対話で実行する" "$args" "/retrospect"
assert_contains "(a) --model opus を渡す" "$args" "opus"

# (a2) claude の終了コードがそのまま伝播する
case_dir="$WORKDIR/a2"
setup_case "$case_dir" yes
rc=0
CLAUDE_STUB_RC=3 run_case "$case_dir" "$case_dir/bin:$case_dir/bare" || rc=$?
assert_rc "(a2) claude の失敗終了コードが伝播する" 3 "$rc"

# (b) claude が PATH にも versions/ にも無ければ起動せず exit 127
case_dir="$WORKDIR/b"
setup_case "$case_dir" no
rc=0
run_case "$case_dir" "$case_dir/bare" || rc=$?
assert_rc "(b) claude 不在で exit 127" 127 "$rc"

# (c) PATH に無くても versions/ 直下に実体があればそれで起動する
case_dir="$WORKDIR/c"
setup_case "$case_dir" no
write_claude_stub "$case_dir/versions/2.9.9" "$case_dir/args.txt"
rc=0
run_case "$case_dir" "$case_dir/bare" || rc=$?
assert_rc "(c) versions/ の実体へフォールバックして rc=0" 0 "$rc"
args="$(cat "$case_dir/args.txt" 2>/dev/null || true)"
assert_contains "(c) フォールバック先でも /retrospect を実行する" "$args" "/retrospect"

# (d) caffeinate があれば呼び、無くても失敗しない（macOS 以外でも動く）
case_dir="$WORKDIR/d1"
setup_case "$case_dir" yes
rc=0
run_case "$case_dir" "$case_dir/bin:$case_dir/bare" || rc=$?
sleep 0.2
assert_contains "(d) caffeinate が PATH にあれば呼ぶ" "$(cat "$case_dir/caffeinate.txt" 2>/dev/null || true)" "called"

case_dir="$WORKDIR/d2"
setup_case "$case_dir" yes
rm "$case_dir/bin/caffeinate"
rc=0
run_case "$case_dir" "$case_dir/bin:$case_dir/bare" || rc=$?
assert_rc "(d) caffeinate が無くても rc=0 で完走する" 0 "$rc"

# (e) --disallowedTools に Web 系とプラグイン経由名の遮断が含まれる
case_dir="$WORKDIR/e"
setup_case "$case_dir" yes
run_case "$case_dir" "$case_dir/bin:$case_dir/bare" || true
disallowed="$(grep -A1 -x -- '--disallowedTools' "$case_dir/args.txt" | tail -n1)"
assert_contains "(e) WebFetch を遮断する" "$disallowed" "WebFetch"
assert_contains "(e) プラグイン経由の MCP 名(mcp__plugin_*)も遮断する" "$disallowed" "mcp__plugin_"
assert_contains "(e) mcp__gemini__ask-gemini から導出された名前を遮断する" "$disallowed" "mcp__plugin_gemini_gemini__ask-gemini"
if printf '%s' "$disallowed" | grep -qF "mcp__plugin_recall"; then
  echo "FAIL: (e) recall 自身(mcp__plugin_recall_*)は遮断しない"
  fail=$((fail + 1))
else
  echo "PASS: (e) recall 自身(mcp__plugin_recall_*)は遮断しない"
  pass=$((pass + 1))
fi

# (f) 権限拒否は rc=0 でも失敗にする（拒否は迂回で吸収され成功に見えるため）
case_dir="$WORKDIR/f"
setup_case "$case_dir" yes
rc=0
CLAUDE_STUB_JSON='{"result":"done","permission_denials":[{"tool_name":"mcp__recall__memory_search","tool_input":{}}]}' \
  run_case "$case_dir" "$case_dir/bin:$case_dir/bare" || rc=$?
assert_rc "(f) permission_denials があれば exit 1" 1 "$rc"
assert_contains "(f) 拒否されたツール名を stderr に出す" "$(cat "$case_dir/stderr.txt")" "mcp__recall__memory_search"

# (f2) 結果 JSON を読めない場合も「拒否なし」とは言えないので失敗にする
case_dir="$WORKDIR/f2"
setup_case "$case_dir" yes
rc=0
CLAUDE_STUB_JSON='not json' run_case "$case_dir" "$case_dir/bin:$case_dir/bare" || rc=$?
assert_rc "(f2) 結果 JSON が壊れていれば exit 1" 1 "$rc"

# (f3) 拒否なしなら応答本文をログへ戻し、JSON の生出力は流さない
case_dir="$WORKDIR/f3"
setup_case "$case_dir" yes
run_case "$case_dir" "$case_dir/bin:$case_dir/bare" || true
assert_contains "(f3) result 本文を stdout に出す" "$(cat "$case_dir/stdout.txt")" "stub ok"
args="$(cat "$case_dir/args.txt" 2>/dev/null || true)"
assert_contains "(f3) --output-format json で起動する" "$args" "json"

# (g) recall の memory_search は allowedTools に載せる（disallow に含めないだけでは headless で拒否される）
case_dir="$WORKDIR/g"
setup_case "$case_dir" yes
run_case "$case_dir" "$case_dir/bin:$case_dir/bare" || true
allowed="$(grep -A1 -x -- '--allowedTools' "$case_dir/args.txt" | tail -n1)"
assert_contains "(g) user-scope 名の memory_search を許可する" "$allowed" "mcp__recall__memory_search"
assert_contains "(g) プラグイン導入名の memory_search を許可する" "$allowed" "mcp__plugin_agent-recall_recall__memory_search"

echo "----"
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

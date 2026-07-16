#!/usr/bin/env bash
# check-setup.sh のスモークテスト。
#
# なぜ bats 等の外部フレームワークを使わないのか:
# distill/weekly-distill.test.sh と同様、この用途のためだけに新規依存を増やすのは
# スコープ過剰。exit code と stdout の内容一致だけで十分検証できる。
#
# なぜ $HOME を差し替えず AGENT_RECALL_HOME / RECALL_CORPUS_DIR を使うのか:
# check-setup.sh は実 ~/.claude/agent-recall/ を読みに行く設計だが、テストが実ユーザーの
# セットアップ状態に依存すると不安定になる（実行環境によって未設定/設定済みが変わる）。
# archive-session.sh の CORPUS_DIR 上書き・weekly-distill.sh の RECALL_DIR 上書きと同じ
# 方針で、check-setup.sh 側にも AGENT_RECALL_HOME 環境変数による上書きを用意し、
# テストは隔離した一時ディレクトリへ向ける。
#
# なぜ bash 3.2 (/bin/bash) で実行するのか:
# 他の *.test.sh と同じ理由でPATH解決に依存せずmacOS標準の /bin/bash を固定で使う。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CHECK_SETUP_SH="$SCRIPT_DIR/check-setup.sh"
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

# $1: label, $2: output全体, $3: 含まれるべき文字列
assert_contains() {
  local label="$1" output="$2" needle="$3"
  if printf '%s' "$output" | grep -qF -- "$needle"; then
    echo "PASS: $label"
    pass=$((pass + 1))
  else
    echo "FAIL: $label (needle not found: $needle)"
    echo "  --- output ---"
    printf '%s\n' "$output" | sed 's/^/  /'
    echo "  --------------"
    fail=$((fail + 1))
  fi
}

# $1: label, $2: output全体
assert_empty() {
  local label="$1" output="$2"
  if [ -z "$output" ]; then
    echo "PASS: $label"
    pass=$((pass + 1))
  else
    echo "FAIL: $label (expected empty output, got: $output)"
    fail=$((fail + 1))
  fi
}

run_check_setup() {
  local home_dir="$1" corpus_dir="$2"
  AGENT_RECALL_HOME="$home_dir" RECALL_CORPUS_DIR="$corpus_dir" "$BASH_BIN" "$CHECK_SETUP_SH"
}

echo "=== check-setup.sh: 未設定/設定済み/config.env破損 の3シナリオ ==="

# --- (a) 未設定(setup.json無し・corpus無し) -> additionalContext のJSONを出力、exit 0 ---
case_dir="$WORKDIR/not-configured"
mkdir -p "$case_dir/home"
rc=0
out="$(run_check_setup "$case_dir/home" "$case_dir/corpus-not-exist")" || rc=$?
assert_rc "未設定: exit 0" 0 "$rc"
assert_contains "未設定: hookSpecificOutputのJSONを出力する" "$out" '"hookEventName":"SessionStart"'
assert_contains "未設定: /agent-recall:setup への案内文言を含む" "$out" "/agent-recall:setup"

# --- (b) 設定済み(setup.json有り・corpus実在) -> 無出力、exit 0 ---
case_dir="$WORKDIR/configured"
mkdir -p "$case_dir/home" "$case_dir/corpus"
: > "$case_dir/home/setup.json"
rc=0
out="$(run_check_setup "$case_dir/home" "$case_dir/corpus")" || rc=$?
assert_rc "設定済み: exit 0" 0 "$rc"
assert_empty "設定済み: 無出力" "$out"

# --- (c) config.env が壊れている -> それでも exit 0 (fail-open) ---
case_dir="$WORKDIR/broken-config-env"
mkdir -p "$case_dir/home" "$case_dir/corpus"
: > "$case_dir/home/setup.json"
# 意図的に構文が壊れたconfig.env（閉じていないクォート）を配置する。
printf '%s\n' 'RECALL_CORPUS_DIR="' > "$case_dir/home/config.env"
rc=0
run_check_setup "$case_dir/home" "$case_dir/corpus" >/dev/null 2>&1
rc=$?
assert_rc "config.env破損: exit 0(fail-open)" 0 "$rc"

echo "----"
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

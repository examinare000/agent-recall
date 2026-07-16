#!/usr/bin/env bash
# weekly-distill.sh のスモークテスト。
#
# なぜ bats 等の外部フレームワークを使わないのか:
# launchd/notify.test.sh / bootstrap/bootstrap.test.sh と同様、この用途のためだけに
# 新規依存を増やすのはスコープ過剰。exit code と .weekly.log の内容一致だけで十分検証できる。
#
# なぜ notify.sh 併用を検証しないのか（2026-07-16 改訂）:
# notify.sh は個人固有の設定パス（元モノレポ由来のディレクトリ名を含む ntfy トピック
# 設定ファイル）に依存する私有ツールであり、この抽出リポジトリには同梱しない
# （schedulers/launchd/run-retrospect.sh と同様、呼び出しはコメントアウトした
# opt-in拡張点として残すのみ）。旧テストは「notify.sh が正しい引数で呼ばれるか」を
# 検証していたが、これはもう存在しない機能を検証する死んだテストであり、
# 「パス規約変更に伴う正当な仕様変更」に該当するためテスト側を書き換える。
#
# なぜ実 python3 / 実 uv を一切使わないのか:
# weekly-distill.sh は実際に corpus 抽出・recall索引更新を起動しうるため、
# python3/uv は PATH 先頭のスタブに完全に差し替える。$REPO 自体も実リポジトリではなく
# 隔離した一時ディレクトリを使う（実クローン先には一切触れない）。
#
# なぜ $REPO の差し替えに RECALL_DIR 環境変数を使うのか:
# weekly-distill.sh は REPO="${RECALL_DIR:-$HOME/.local/share/claude/recall}" で
# 解決するため（旧: モノレポ内の固定パスに直書きされていた名残りで、旧テストは
# $HOME を差し替えるシンボリックリンク細工をしていたが、現行スクリプトの解決方式と
# 合わなくなっている）、テストは RECALL_DIR を直接隔離ディレクトリへ向ければよい。
#
# なぜ検証対象を .weekly.log の内容にするのか:
# osascript によるデスクトップ通知はハードコードされた絶対パス(/usr/bin/osascript)で
# 呼ばれておりPATHスタブで差し替えられない一方、実行しても実害のないローカル通知
# なので許容する（元テストも同方針で未検証だった）。log_line が書く .weekly.log は
# extract/index の成否を確定的に反映するため、これを検証対象にする。
#
# なぜ bash 3.2 (/bin/bash) で実行するのか:
# launchd/notify.test.sh / bootstrap.test.sh と同じ理由でPATH解決に依存せず
# macOS標準の /bin/bash を固定で使う。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WEEKLY_DISTILL_SH="$SCRIPT_DIR/weekly-distill.sh"
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

# $1: label, $2: output全体, $3: 含まれてはいけない文字列
assert_not_contains() {
  local label="$1" output="$2" needle="$3"
  if printf '%s' "$output" | grep -qF -- "$needle"; then
    echo "FAIL: $label (unexpected needle found: $needle)"
    fail=$((fail + 1))
  else
    echo "PASS: $label"
    pass=$((pass + 1))
  fi
}

# 隔離された $REPO を作り、weekly-distill.sh・python3スタブ・uvスタブを配置する。
# notify.sh は同梱しない機能のため配置しない（未配置でも動くことの回帰確認を兼ねる）。
# $1: case_dir
# 環境変数 EXTRACT_MODE (ok|newprompts|fail) / UV_MODE (ok|fail) で各stubの挙動を切り替える。
setup_distill_case() {
  local case_dir="$1"
  mkdir -p "$case_dir/repo/distill" "$case_dir/repo/recall" "$case_dir/bin"
  cp "$WEEKLY_DISTILL_SH" "$case_dir/repo/distill/weekly-distill.sh"
  : > "$case_dir/repo/distill/extract.py"

  cat > "$case_dir/bin/python3" <<'STUBEOF'
#!/bin/sh
# 引数(distill/extract.py)は無視し、EXTRACT_MODEに応じた出力/終了コードを返す。
case "${EXTRACT_MODE:-ok}" in
  fail)
    echo "extract boom" >&2
    exit 1
    ;;
  newprompts)
    echo "wrote out/digest.md  (3 prompts, until 2026-07-15)"
    exit 0
    ;;
  *)
    echo "wrote out/digest.md  (0 prompts, until 2026-07-15)"
    exit 0
    ;;
esac
STUBEOF
  chmod +x "$case_dir/bin/python3"

  cat > "$case_dir/bin/uv" <<'STUBEOF'
#!/bin/sh
if [ "${UV_MODE:-ok}" = "fail" ]; then
  echo "index boom" >&2
  exit 1
fi
echo "indexed ok"
exit 0
STUBEOF
  chmod +x "$case_dir/bin/uv"
}

# weekly-distill.sh は REPO="${RECALL_DIR:-...}" で解決するため、RECALL_DIR を
# 隔離した case_dir/repo へ向けるだけでよい（HOME差し替え等の細工は不要）。
run_distill_case() {
  local case_dir="$1"
  PATH="$case_dir/bin:$PATH" RECALL_DIR="$case_dir/repo" "$BASH_BIN" "$case_dir/repo/distill/weekly-distill.sh" >/dev/null 2>&1
}

read_log() {
  local case_dir="$1"
  cat "$case_dir/repo/distill/.weekly.log" 2>/dev/null || true
}

echo "=== weekly-distill.sh: fail-open 動作 と .weekly.log の記録内容 ==="

# --- (a) extract.py失敗 -> exit 0(fail-open)、.weekly.log に failed status=1 を記録 ---
case_dir="$WORKDIR/extract-fail"
setup_distill_case "$case_dir"
rc=0
EXTRACT_MODE=fail UV_MODE=ok run_distill_case "$case_dir" || rc=$?
assert_rc "extract失敗: weekly-distill.sh自体はexit 0(fail-open)" 0 "$rc"
log="$(read_log "$case_dir")"
assert_contains "extract失敗: .weekly.logにfailed status=1が記録される" "$log" "failed status=1"

# --- (b) 新規発話n>0 -> .weekly.log に new_prompts=3 を記録 ---
case_dir="$WORKDIR/new-prompts"
setup_distill_case "$case_dir"
rc=0
EXTRACT_MODE=newprompts UV_MODE=ok run_distill_case "$case_dir" || rc=$?
assert_rc "新規発話: exit 0" 0 "$rc"
log="$(read_log "$case_dir")"
assert_contains "新規発話: .weekly.logに新規件数(new_prompts=3)が記録される" "$log" "new_prompts=3"

# --- (c) recall index失敗 -> exit 0(fail-open)、.weekly.log に index failed status=1 を記録 ---
case_dir="$WORKDIR/index-fail"
setup_distill_case "$case_dir"
rc=0
EXTRACT_MODE=ok UV_MODE=fail run_distill_case "$case_dir" || rc=$?
assert_rc "index失敗: exit 0" 0 "$rc"
log="$(read_log "$case_dir")"
assert_contains "index失敗: .weekly.logにindex failed status=1が記録される" "$log" "index	failed status=1"

# --- (d) 正常系(新規発話0件・失敗なし) -> exit 0、new_prompts=0 と index ok を記録 ---
case_dir="$WORKDIR/quiet-ok"
setup_distill_case "$case_dir"
rc=0
EXTRACT_MODE=ok UV_MODE=ok run_distill_case "$case_dir" || rc=$?
assert_rc "正常系: exit 0" 0 "$rc"
log="$(read_log "$case_dir")"
assert_contains "正常系: .weekly.logにnew_prompts=0が記録される" "$log" "new_prompts=0"
assert_contains "正常系: .weekly.logにindex okが記録される" "$log" "index	ok"

# --- (e) notify.sh 未配置の回帰確認: どのケースでもnotify.sh呼出を試みず、
#         repo/launchd 配下に何も作らずに正常終了する（opt-inのまま同梱しない設計） ---
case_dir="$WORKDIR/no-notify-sh"
setup_distill_case "$case_dir"
rc=0
EXTRACT_MODE=fail UV_MODE=fail run_distill_case "$case_dir" || rc=$?
assert_rc "notify.sh未配置でも二重失敗時にexit 0(fail-open)" 0 "$rc"
if [ -e "$case_dir/repo/launchd" ] || [ -e "$case_dir/repo/schedulers" ]; then
  echo "FAIL: notify.sh未配置: 不要なlaunchd/schedulersディレクトリが作られていない"
  fail=$((fail + 1))
else
  echo "PASS: notify.sh未配置: 不要なlaunchd/schedulersディレクトリは作られない"
  pass=$((pass + 1))
fi

echo "----"
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

#!/usr/bin/env bash
# archive-session.sh のスモークテスト。
#
# なぜ bats 等の外部フレームワークを使わないのか:
# check-setup.test.sh / weekly-distill.test.sh と同様、この用途のためだけに
# 新規依存を増やすのはスコープ過剰。exit code とアーカイブ先ファイルの実在・
# uv 呼び出しログの内容一致だけで十分検証できる。
#
# なぜ $HOME を丸ごと差し替えるのか（check-setup.test.sh とは異なる方針）:
# archive-session.sh の CONFIG_ENV は "$HOME/.claude/agent-recall/config.env" に
# 固定されており、check-setup.sh の AGENT_RECALL_HOME のような上書き変数が無い。
# config.env 経由の RECALL_CORPUS_DIR / CORPUS_DIR 読み込みを検証するには
# $HOME 自体を隔離した一時ディレクトリへ向けるしかない。
#
# なぜ pgrep をスタブで常に「未検出」に固定するのか:
# archive-session.sh は `pgrep -f "recall index"` が偽の場合のみ uv を起動するが、
# 実行環境で本物の recall index プロセスがたまたま走っていると意図せずガードで
# スキップされテストが不安定になる。pgrep をスタブして常に exit 1 を返させ、
# 決定的にガードを通過させる。
#
# なぜ uv を実行せずスタブで引数だけ記録するのか:
# 実 uv を起動すると重い依存解決・ネットワークアクセスが走りうる。nohup & で
# バックグラウンド起動される呼び出し引数（特に --directory の値）だけを
# 検証すれば RECALL_DIR/CLAUDE_PLUGIN_ROOT の解決順は確認できる。
#
# なぜ bash 3.2 (/bin/bash) で実行するのか:
# 他の *.test.sh と同じ理由でPATH解決に依存せずmacOS標準の /bin/bash を固定で使う。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ARCHIVE_SESSION_SH="$SCRIPT_DIR/archive-session.sh"
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

# $1: label, $2: path
assert_file_exists() {
  local label="$1" path="$2"
  if [ -f "$path" ]; then
    echo "PASS: $label"
    pass=$((pass + 1))
  else
    echo "FAIL: $label (file not found: $path)"
    fail=$((fail + 1))
  fi
}

# $1: label, $2: path (存在してはいけない)
assert_file_not_exists() {
  local label="$1" path="$2"
  if [ ! -e "$path" ]; then
    echo "PASS: $label"
    pass=$((pass + 1))
  else
    echo "FAIL: $label (存在してはいけないファイルが存在する: $path)"
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

# 隔離された疑似 transcript ファイルを用意し、SessionEnd の stdin JSON を組み立てる。
# $1: home_dir  $2: proj_name  $3: transcript_basename
# echo: JSON payload / stdout に transcript のフルパスを出す（呼び出し側が変数で受ける）
make_payload() {
  local home_dir="$1" proj="$2" basename="$3"
  local proj_dir="$home_dir/.claude/projects/$proj"
  mkdir -p "$proj_dir"
  local transcript="$proj_dir/$basename"
  printf '{"session_id":"sess-1"}\n' > "$transcript"
  printf '{"transcript_path":"%s","session_id":"sess-1","cwd":"/tmp"}' "$transcript"
  TRANSCRIPT_PATH="$transcript"
}

# pgrep を常に「未検出」に固定するスタブを作る（uv 起動ガードを決定的に通過させる）。
# $1: stub_dir
make_pgrep_stub() {
  local stub_dir="$1"
  mkdir -p "$stub_dir"
  cat > "$stub_dir/pgrep" <<'STUBEOF'
#!/bin/sh
exit 1
STUBEOF
  chmod +x "$stub_dir/pgrep"
}

# uv 呼び出しの引数を UV_LOG に記録するだけのスタブを作る。
# $1: stub_dir
make_uv_stub() {
  local stub_dir="$1"
  mkdir -p "$stub_dir"
  cat > "$stub_dir/uv" <<'STUBEOF'
#!/bin/sh
printf '%s\n' "$*" >> "$UV_LOG"
exit 0
STUBEOF
  chmod +x "$stub_dir/uv"
}

# nohup & でバックグラウンド起動される uv スタブのログ出力を短時間ポーリングして待つ。
# $1: log_path
wait_for_log() {
  local log_path="$1" tries=0
  while [ ! -s "$log_path" ] && [ "$tries" -lt 40 ]; do
    sleep 0.05
    tries=$((tries + 1))
  done
}

echo "=== archive-session.sh: RECALL_CORPUS_DIR / CORPUS_DIR 解決順 ==="

# --- (a) config.env に RECALL_CORPUS_DIR を書くと実際にアーカイブ先が変わる ---
case_dir="$WORKDIR/case-a"
home_dir="$case_dir/home"
custom_corpus="$case_dir/custom-corpus"
mkdir -p "$home_dir/.claude/agent-recall"
printf 'RECALL_CORPUS_DIR="%s"\n' "$custom_corpus" > "$home_dir/.claude/agent-recall/config.env"
payload="$(make_payload "$home_dir" "testproj-a" "uuid-a.jsonl")"
rc=0
printf '%s' "$payload" | HOME="$home_dir" "$BASH_BIN" "$ARCHIVE_SESSION_SH" >/dev/null 2>&1 || rc=$?
assert_rc "RECALL_CORPUS_DIR指定: exit 0" 0 "$rc"
assert_file_exists "RECALL_CORPUS_DIR指定: 指定先にアーカイブされる" \
  "$custom_corpus/claude-code/testproj-a/uuid-a.jsonl"
assert_file_not_exists "RECALL_CORPUS_DIR指定: 既定の~/.claude/corpusには作られない" \
  "$home_dir/.claude/corpus/claude-code/testproj-a/uuid-a.jsonl"

# --- (b) 旧 CORPUS_DIR (env) フォールバックが効く ---
case_dir="$WORKDIR/case-b"
home_dir="$case_dir/home"
legacy_corpus="$case_dir/legacy-corpus"
mkdir -p "$home_dir"
payload="$(make_payload "$home_dir" "testproj-b" "uuid-b.jsonl")"
rc=0
printf '%s' "$payload" | HOME="$home_dir" CORPUS_DIR="$legacy_corpus" "$BASH_BIN" "$ARCHIVE_SESSION_SH" >/dev/null 2>&1 || rc=$?
assert_rc "旧CORPUS_DIRフォールバック: exit 0" 0 "$rc"
assert_file_exists "旧CORPUS_DIRフォールバック: 旧変数の指定先にアーカイブされる" \
  "$legacy_corpus/claude-code/testproj-b/uuid-b.jsonl"

# --- (c) 未設定時は既定 ($HOME/.claude/corpus) ---
case_dir="$WORKDIR/case-c"
home_dir="$case_dir/home"
mkdir -p "$home_dir"
payload="$(make_payload "$home_dir" "testproj-c" "uuid-c.jsonl")"
rc=0
printf '%s' "$payload" | HOME="$home_dir" "$BASH_BIN" "$ARCHIVE_SESSION_SH" >/dev/null 2>&1 || rc=$?
assert_rc "未設定: exit 0" 0 "$rc"
assert_file_exists "未設定: 既定の\$HOME/.claude/corpusにアーカイブされる" \
  "$home_dir/.claude/corpus/claude-code/testproj-c/uuid-c.jsonl"

echo "=== archive-session.sh: RECALL_DIR / CLAUDE_PLUGIN_ROOT 解決順 (recall index 起動先) ==="

# --- (d) RECALL_DIR 未設定・CLAUDE_PLUGIN_ROOT 設定時にその配下が使われる ---
case_dir="$WORKDIR/case-d"
home_dir="$case_dir/home"
plugin_root="$case_dir/plugin-root"
stub_dir="$case_dir/stubs"
mkdir -p "$home_dir" "$plugin_root"
make_pgrep_stub "$stub_dir"
make_uv_stub "$stub_dir"
uv_log="$case_dir/uv.log"
payload="$(make_payload "$home_dir" "testproj-d" "uuid-d.jsonl")"
printf '%s' "$payload" | HOME="$home_dir" CLAUDE_PLUGIN_ROOT="$plugin_root" UV_LOG="$uv_log" \
  PATH="$stub_dir:$PATH" "$BASH_BIN" "$ARCHIVE_SESSION_SH" >/dev/null 2>&1
wait_for_log "$uv_log"
uv_calls="$(cat "$uv_log" 2>/dev/null || true)"
assert_contains "CLAUDE_PLUGIN_ROOT設定時: uvがCLAUDE_PLUGIN_ROOT配下に対して起動される" \
  "$uv_calls" "--directory $plugin_root recall index"

# --- (e) RECALL_DIR と CLAUDE_PLUGIN_ROOT 両方設定時は RECALL_DIR が優先される ---
case_dir="$WORKDIR/case-e"
home_dir="$case_dir/home"
plugin_root="$case_dir/plugin-root"
recall_dir="$case_dir/recall-dir"
stub_dir="$case_dir/stubs"
mkdir -p "$home_dir" "$plugin_root" "$recall_dir"
make_pgrep_stub "$stub_dir"
make_uv_stub "$stub_dir"
uv_log="$case_dir/uv.log"
payload="$(make_payload "$home_dir" "testproj-e" "uuid-e.jsonl")"
printf '%s' "$payload" | HOME="$home_dir" CLAUDE_PLUGIN_ROOT="$plugin_root" RECALL_DIR="$recall_dir" \
  UV_LOG="$uv_log" PATH="$stub_dir:$PATH" "$BASH_BIN" "$ARCHIVE_SESSION_SH" >/dev/null 2>&1
wait_for_log "$uv_log"
uv_calls="$(cat "$uv_log" 2>/dev/null || true)"
assert_contains "RECALL_DIR優先: uvがRECALL_DIR配下に対して起動される" \
  "$uv_calls" "--directory $recall_dir recall index"

echo "----"
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

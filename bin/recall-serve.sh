#!/usr/bin/env bash
# .mcp.json から起動される recall MCP サーバ(stdio)の起動スクリプト。
#
# 設計方針:
# - plugin install はファイルコピーのみで `uv sync` を行わない（cache は更新のたびに
#   揮発する）。そのため実行時に uv の有無を確認し、無ければサイレントに失敗させず
#   案内を出して exit 1 する。
# - 利用者固有の設定（例: RECALL_CORPUS_DIR の上書き等）を
#   ~/.claude/agent-recall/config.env に置けるようにし、存在すれば読み込む
#   （プラグイン本体・cache 配下ではなく cache 外に置くことで plugin 更新でも消えない）。
set -u

CONFIG_ENV="$HOME/.claude/agent-recall/config.env"
if [ -f "$CONFIG_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$CONFIG_ENV" 2>/dev/null || true
  set +a
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "エラー: uv が見つかりません。https://docs.astral.sh/uv/ の手順に従って uv をインストールしてください。" >&2
  exit 1
fi

# このスクリプトは bin/ 直下にある前提。親ディレクトリ(プラグインルート/リポジトリルート)を
# recall パッケージの --directory 引数に渡す。
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
exec uv run --directory "$PLUGIN_ROOT" recall serve

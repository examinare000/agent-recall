---
description: 自己改善基盤の対話セットアップ
---

# /agent-recall:setup（暫定版）

本コマンドは R2 で完全実装予定（メモリ保持形式・蒸留方法の対話設定、
`~/.claude/agent-recall/setup.json` の生成までを自動化する）。

現状は以下のみを行う:

1. **前提検査**: `uv` と `jq` の有無を確認する。
   - `uv` が無い場合: https://docs.astral.sh/uv/ の手順に従ってインストールしてください
     （`bin/recall-serve.sh` は uv 不在時にエラー終了する）。
   - `jq` は必須ではないが、`hooks/archive-session.sh` は jq があれば使い、
     無ければ python3 にフォールバックする。
2. **依存関係の同期**: `uv sync --directory "${CLAUDE_PLUGIN_ROOT}"` を実行する。
   - plugin install はファイルコピーのみで `uv sync` を行わないため、
     MCP サーバ（`recall serve`）を動かすにはこの同期が必要。

## 手動セットアップ手順（R2 実装までの暫定運用）

1. 上記の前提検査・依存同期を手動で実行する。
2. `~/.claude/agent-recall/` ディレクトリを作成し、必要なら `config.env` に
   `RECALL_CORPUS_DIR` 等の上書き設定を記述する
   （書式は `KEY=VALUE` の一行ずつ。`source` されるシェルスクリプトとして扱われる）。
3. セットアップが完了したことを示す `~/.claude/agent-recall/setup.json` を作成する
   （`SessionStart` フック `hooks/check-setup.sh` はこのファイルの有無で
   未設定通知の要否を判定する）。
4. `~/.claude/corpus/claude-code/` へのアーカイブが有効か、次回セッション終了後に
   `hooks/archive-session.sh` のログ（`~/.claude/corpus/.archive.log`）で確認する。

R2 では 1-3 を対話形式（ユーザーへの質問と選択肢提示）で自動化する予定。

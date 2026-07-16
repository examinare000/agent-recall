recall — session-archive semantic search MCP + lesson distillation pipeline for Claude Code. Pairs with the agent-forge framework (rule 94 self-improvement loop). Documentation is in Japanese.

---

# recall

Session archive の意味検索 MCP と教訓蒸留パイプラインの統合ツール。Claude Code の自己改善ループ（rule 94: self-improvement-protocol）を支える記憶・学習基盤です。

## 概要

`accumulate → distill → apply` の3段階ループで、セッションアーカイブから構造的な再発パターンを抽出し、skill / agent-rules / hooks / memory / docs へ昇格させます。

- **recall**: セッションログコーパス（`~/.claude/corpus/`）の意味検索 MCP サーバ
- **distill**: ログからユーザーの発話ダイジェストを増分抽出し、人間がレビューして嗜好を蒸留
- **archive-session hook**: セッション終了時にコーパスへ自動アーカイブ
- **retrospect skill**: 教訓候補（`~/.claude/lessons/inbox/`）と過去ログから再発パターンを分析
- **retrospective-analyst agent**: パターン抽象化と昇格先判定
- **schedulers**: launchd で週次実行する plist テンプレート

## 構成

```
recall/
  ├── recall/               # MCP サーバ（パッケージ本体）
  ├── tests/                # ユニットテスト
  ├── distill/
  │   ├── extract.py        # 人間の発話ダイジェスト抽出
  │   ├── SKILL.md          # 蒸留手順（半手動）
  │   └── weekly-distill.sh # 週次ダイジェスト生成スクリプト
  ├── hooks/
  │   └── archive-session.sh # SessionEnd フック（コーパス自動アーカイブ）
  ├── skills/
  │   └── retrospect/
  │       └── SKILL.md      # 振り返り・教訓昇格の手続き（8ステップ）
  ├── agents/
  │   └── retrospective-analyst.md  # パターン分析エージェント
  ├── schedulers/launchd/
  │   ├── com.example.recall.retrospect.plist         # 週次retrospect（テンプレート）
  │   ├── com.example.recall.weekly-distill.plist     # 週次distill（テンプレート）
  │   └── run-retrospect.sh                           # retrospect 実行ラッパー
  ├── pyproject.toml        # recall パッケージメタデータ
  └── README.md             # このファイル
```

## セットアップ

### 1. インストール

```bash
cd <recall-clone-dir>
uv sync
```

### 2. MCP サーバの登録

Claude Code の settings.json に以下を追加（またはプラグイン UI で登録）:

```json
{
  "mcpServers": {
    "recall": {
      "command": "uv",
      "args": ["run", "--directory", "<recall-clone-dir>", "recall", "server"]
    }
  }
}
```

### 3. SessionEnd フック設定

`~/.claude/settings.json` に以下を追加:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "command": "/bin/bash",
        "args": ["<recall-clone-dir>/hooks/archive-session.sh"]
      }
    ]
  }
}
```

### 4. Skills と Agents の配置

シンボリックリンクまたはコピーで `~/.claude/` 配下へ配置:

```bash
# skills（ディレクトリ + SKILL.md 形式のため、ディレクトリごとリンクする）
ln -s <recall-clone-dir>/skills/retrospect ~/.claude/skills/retrospect

# agents
ln -s <recall-clone-dir>/agents/retrospective-analyst.md ~/.claude/agents/
```

### 5. Launchd スケジューラの登録（オプション）

週次 retrospect と distill を自動実行したい場合:

```bash
# recall リポジトリのパスに置換（下記の例は参考）
sed -e 's/com.example.recall/com.myname.recall/g' \
    -e 's|\${HOME}/.local/share/claude/recall|'"$HOME"'/.local/share/claude/recall|g' \
    <recall-clone-dir>/schedulers/launchd/com.example.recall.retrospect.plist \
  > ~/Library/LaunchAgents/com.myname.recall.retrospect.plist

sed -e 's/com.example.recall/com.myname.recall/g' \
    -e 's|\${HOME}/.local/share/claude/recall|'"$HOME"'/.local/share/claude/recall|g' \
    <recall-clone-dir>/schedulers/launchd/com.example.recall.weekly-distill.plist \
  > ~/Library/LaunchAgents/com.myname.recall.weekly-distill.plist

# 登録
launchctl load ~/Library/LaunchAgents/com.myname.recall.retrospect.plist
launchctl load ~/Library/LaunchAgents/com.myname.recall.weekly-distill.plist
```

## 標準パス規約

| 用途 | パス |
|---|---|
| Session コーパス | `~/.claude/corpus/claude-code/` |
| 教訓候補 inbox | `~/.claude/lessons/inbox/` |
| 教訓（処理済み） | `~/.claude/lessons/processed/` |
| 昇格提案 | `~/.claude/lessons/proposals/` |
| Recall 索引状態 | `~/.claude/lessons/state.json` |
| プロジェクト auto-memory | `~/.claude/projects/<proj>/memory/` |

## 使用方法

### 手動実行

```bash
# 1. recall 索引の更新
uv run --directory <recall-clone-dir> recall index

# 2. ダイジェスト生成
cd <recall-clone-dir>/distill
python3 extract.py
# 出力: distill/out/digest-<date>.md

# 3. 振り返り（分析 + 昇格提案）
/retrospect
```

### distill-preferences スキル

ダイジェストから嗜好パターンを抽出し、memory 化する半手動手順:

```bash
distill/SKILL.md を参照して実行
```

### retrospect スキル

教訓候補と過去ログから構造的再発を分析し、適切なレベルへ昇格:

```bash
/retrospect  # メインセッションから起動
```

## shelf との関係

`distill/extract.py` は掲載された個人メモリのマスク・引き出しの正本です。
別途の shelf MCP が個人ナレッジベースを配置している場合、distill の設定値を参照して一元化可能です。

## テスト実行

```bash
cd <recall-clone-dir>
uv run pytest
```

## `~/.claude/rules/94-self-improvement-protocol.md` との関係

recall は自己改善プロトコル（`~/.claude/rules/94-self-improvement-protocol.md`。
別頒布の agent-forge フレームワークの installer がこのパスに配置する）の実装基盤です：

- **Step 1（記録）**: archive-session hook が session → corpus へ自動記録
- **Step 2（蒸留）**: distill/extract.py + distill-preferences skill で発話 → inbox
- **Step 3（分析）**: retrospect skill + retrospective-analyst で pattern 抽出
- **Step 4-5（昇格・提案）**: skill / agent-rules / hook / memory / docs 化
- **Step 6-8（適用・反射）**: git-composer が PR 作成（人間承認待ち）

週次スケジューラ（launchd）が 1-3 を自動化；4-6 は提案で停止（人間が最終承認）。

## ライセンス

MIT License - Copyright (c) 2026 Ryosuke Ikeda

## 参考

- `~/.claude/rules/94-self-improvement-protocol.md`: 自己改善プロトコル（agent-forge の installer が配置。上流ソースは [agent-forge リポジトリ](https://github.com/yourorg/agent-forge) 参照）
- [claude-code CLAUDE.md: Memory 型と規約](https://github.com/anthropics/claude-code/docs/CLAUDE.md)

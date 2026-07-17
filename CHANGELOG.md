# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-07-17

### Added

- **recall MCP サーバ**: セッションアーカイブコーパス（`~/.claude/corpus/`）の意味検索・取得機能
  - `memory_search`: 自然言語クエリによる過去セッションの語義検索
  - `memory_get`: セッション ID による直接取得
  - Postgres ベースの高速インデックス

- **distill パイプライン**: セッションログからの教訓抽出・蒸留
  - `distill/extract.py`: ユーザー発話ダイジェストの増分抽出
  - shelf MCP マスク対応・SHELF_EXTRACT_PY 正本
  - 週次ダイジェスト生成スクリプト

- **retrospect スキル**: パターン分析と教訓昇格（8ステップ手続き）
  - 再発パターンの構造化検出
  - 適切なレベル（skill / agent-rules / hook / memory / docs）への自動提案
  - ユーザー承認ゲート

- **retrospective-analyst エージェント**: 教訓の抽象化と判定

- **Claude Code プラグイン形式対応**
  - `.claude-plugin/` ディレクトリ構成
  - `claude plugin marketplace add examinare000/agent-recall` による GitHub 直指定インストール
  - `/agent-recall:setup` 対話セットアップコマンド

- **SessionEnd フック**: `hooks/archive-session.sh` でセッション終了時にコーパスへ自動アーカイブ

- **Launchd スケジューラテンプレート**: 週次 retrospect・distill 自動実行

- **テスト基盤**: pytest 87 テスト、hook 検証スクリプト

- **Rule 94 自己改善ループの実装基盤**: 記録→蒸留→分析→昇格→適用の 5 段階自動化

### Documentation

- 日本語による詳細な README・セットアップ手順・使用方法
- コマンドリファレンス（`commands/setup.md`）
- agent-forge・agent-shelf との統合ガイド
- launchd 設定例（テンプレート）

[Unreleased]: https://github.com/examinare000/agent-recall/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/examinare000/agent-recall/releases/tag/v0.1.0

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-07-25

### Added

- **distill 出力の原子性向上**: launchd 定期実行と手動実行の並走時にダイジェスト・状態ファイルが破損する可能性を排除
  - `atomic_write_text()` で temp + os.replace によるアトミック書き込み実装
  - 書き込み失敗時に既存ファイルが無傷で残ることを回帰テスト（`tests/test_extract_atomic.py`）で固定

- **MAX_CHARS 単一情報源化**: distill と recall の間での切り詰め長数値のドリフト防止
  - `distill/extract.py` に MAX_CHARS 定数を集約
  - `recall/masking.py` を経由して `recall/chunker.py` が動的に参照
  - 値変更時に両者が自動で同期（importlib による実体共有）

- **OS 非依存のテスト基盤**: chmod(0o000) が Windows で機能しない問題を解決
  - `monkeypatch` で `Path.read_text` を置き換え、PermissionError を再現
  - hook テスト 2 ケース追加で fail-open と冪等性を直接検証（stub 不要）
    - (f) 壊れた JSON payload では corpus 配下が作られない（fail-open の固定）
    - (g) 同名 transcript の再アーカイブで最新内容へ上書き（冪等性の固定）

### Changed

- **Windows POSIX 正規化**: ネストされたファイルの source_file（DB 永続化）が OS に依存して異なる問題の予防的移植
  - `recall/indexer.py` で `path.relative_to().as_posix()` に正規化
  - shelf での同一バグ（`\\` 区切りが DB に永続化 → prune 誤動作・citation 不一致）の再発防止
  - 注記: 本プロジェクトの hook は現状 POSIX 前提のため実害は未観測

### Fixed

- distill 出力ファイルのクラッシュ時破損リスク（atomic_write_text により排除）

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

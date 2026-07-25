# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-07-25

### Added

- **busy_timeout PRAGMA**: 長命サーバと別プロセス CLI の同時アクセス時のロック競合を低減
  - `Store.__init__` に `PRAGMA busy_timeout = 5000ms` を設定
  - SQLITE_BUSY 等の単発ロックからの自動回復を実現し、FTS が恒久的に無効化されるリスクを排除

### Fixed (v0.3.0 マージ後)

- **プローブ失敗時の chunks_fts 回復不可**: SQLITE_BUSY 等の一過性障害から回復できない（PR #7 で `DROP TABLE IF EXISTS chunks_fts` により再作成可能に）

## [0.3.0] - 2026-07-25

### Added

- **ハイブリッド検索**: cosine ベクトル検索と FTS5 キーワード検索（BM25）を RRF（Reciprocal Rank Fusion）で統合
  - `search.py` に `rrf_merge()`・`build_fts_query()` 関数を追加
  - `store.py` に chunks_fts 管理機能（FTS5 仮想テーブル・キーワード検索索引・行単位同期）を追加
  - `service.py` に hybrid_search パラメータを追加。pool_size=limit*2 で両アルゴリズムの上位候補を統合
  - `config.py` に `_bool_env()` 補助関数と `RECALL_HYBRID_SEARCH` 定数を追加
  - `cli.py` 検索結果出力に順位番号を併記
  - `server.py` memory_search ツール説明文を更新

### How it works

- ベクトル検索は意味的に近いが語彙が一致しない文を捕捉
- キーワード検索は固有名詞・型番のような表記ゆれの少ない語を完全一致で取りこぼさない
- FTS5・trigram tokenizer が使えない環境では store.fts_enabled=False により自動的にベクトル単体へ劣化
- 後方互換性を維持：hybrid_search=False で従来と完全に同一の結果

### Fixed (移植時レビューで検出・修正)

- **clear_all() の FTS 例外未処理**: `recall index --all` の唯一の回復手段がクラッシュするリスク（delete-all コマンド実行の例外を try/except で catch）
- **_init_fts でプローブ失敗時に DROP なし**: SQLITE_BUSY 等の一過性失敗から回復できない（CREATE+probe/rebuild 失敗時に DROP TABLE IF EXISTS chunks_fts して次回再試行可能に）

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

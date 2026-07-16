---
name: retrospect
description: 蓄積された教訓候補（lessons/inbox）とセッションアーカイブ（corpus + recall 検索）から再発パターンを抽象化し、skill 化・agent-rules 追記・hook 化・memory カード化・docs(ADR) 化の提案まで自律的に行う振り返りの手続き。「振り返りして」「/retrospect」「教訓をまとめて」依頼時、inbox が 5 件を超えた時、または launchd 定期実行で使用。正本トリガは `~/.claude/rules/94-self-improvement-protocol.md`。
---

# Retrospect（振り返り・教訓昇格の手続き）

記録された教訓候補と会話アーカイブから**構造的な再発パターン**を見つけ、
適切な形（skill / agent-rules / hook / memory / docs）へ昇格させる。
1回の実行 = 1サイクル。提案の品質 > 提案の量（確信のない昇格案は出さない）。

## パス定義

| 名前 | パス |
|---|---|
| LESSONS | `~/.claude/lessons/` |
| INBOX / PROCESSED / PROPOSALS | `LESSONS/inbox/` / `LESSONS/processed/` / `LESSONS/proposals/` |
| STATE | `LESSONS/state.json`（`{"last_run": "<ISO8601>", "processed_ids": [...]}`） |
| CORPUS | `~/.claude/corpus/claude-code/` |
| MEMORY | `~/.claude/projects/<proj>/memory/`（プロジェクト別 auto-memory） |

## 手順（順序固定）

### Step 1: 状態確認と索引更新
- `STATE` を読む（無ければ初回として作成）。
- `uv run --directory <recall-repo-path> recall index` で索引を最新化する（`<recall-repo-path>` は recall リポジトリのクローン先）。

### Step 2: 収集
- `INBOX/*.md` の未処理候補を全件読む。
- `STATE.last_run` 以降に更新された corpus セッション（`find CORPUS -name '*.jsonl' -newer ...`）を列挙し、
  **バルク読みは Explore / haiku サブエージェントへ委譲**して「バグ修正・レビュー指摘・ユーザー訂正の痕跡」を抽出させる
  （メインのコンテキストを生ログで汚さない。1エージェントあたり最大10ファイル程度で分割）。
- 各候補について recall `memory_search` で過去の類似事例を照合し、出現回数の証拠を集める。
- バルク読み委譲の抽出対象に**軌跡シグナル**を含める: フックによるブロック（`exit 2`）、permission / 分類器拒否、`NEEDS_DECISION` / `BLOCKED` 往復、同一タスクの再委譲、レビュー拒否後の手戻り。これらはオーケストレーション設計の教訓候補として扱う（コードの正当性レビューは diff-only の code-reviewer の役割のままで、軌跡は事後のプロセス分析にのみ用いる）。
- inbox に frontmatter の無い旧形式候補があれば、94 の形式（type/project/date/summary/evidence/origin）へ正規化して扱う（「出所」記載は `origin:` に写像）。

### Step 3: クラスタリングと抽象化（retrospective-analyst へ委譲）
- 候補群を `retrospective-analyst` エージェントに渡し、以下を返させる:
  - **2回以上出現**したパターンのクラスタ（1回きりの事象は memory 候補止まり）
  - 各クラスタの抽象化: 前提 ➔ 目的 ➔ 失敗様式 ➔ 対策（具体事象の列挙ではなく構造で書く）
  - **反証チェック**: 「これは偶然の2回か、構造的な再発か」の判定と根拠
  - 昇格先の判定案（Step 4 の分類基準による）

### Step 4: 分類（94 の昇格基準）
| 性質 | 昇格先 |
|---|---|
| 恒真の事実・規約 | agent-rules 追記案 |
| 30行超の手続き | skill 化案（作成には `writing-skills` skill を使う） |
| 確定的強制（毎回必ず/絶対禁止） | hook 化案 |
| ユーザー嗜好・フィードバック・参照 | memory カード |
| プロジェクト固有の設計判断 | docs（ADR）案 |

### Step 5: 重複排除
昇格案ごとに既存資産と突合し、**既にカバーされているものは棄却**する:
- agent-rules: Grep ツール（built-in・read-only・permission 不要）でキーワードを照合（対象パス: `~/.claude/rules/`）
- skills: `~/.claude/skills/` の description
- memory: 対象プロジェクトの `MEMORY.md`
- 過去提案: `PROPOSALS/` と過去 PR（重複提案の再発防止）
既存資産の**更新**が適切な場合は「新規作成」ではなく「追記・改訂」提案にする。

### Step 6: 適用（ティア別）
- **memory カード**: 即時適用。対象プロジェクトの memory ディレクトリに書き、`MEMORY.md` に索引行を追加。
- **agent-rules / skill / hook / docs 案**: `PROPOSALS/<date>-<slug>.md` に提案書（変更先・差分案・根拠となる教訓ID）を書き、
  対象リポジトリに feature branch を切って変更をコミットし、**PR 作成（または PR 説明文の提示）で停止**する。
  git 操作は `git-composer` に委譲。**マージは絶対にしない**（人間の明示承認待ち）。

### Step 7: Memory 反射（キュレーション）
- 対象プロジェクトの memory ディレクトリ（`~/.claude/projects/<proj>/memory/`）を走査し、**カード数 20 超 または MEMORY.md 索引 150 行超**で肥大と判定。
- 肥大時: 重複・近縁カードのクラスタを特定し「統合案」（統合後の1カード案 + 削除対象リスト）、陳腐化カード（実装が既に変わった・参照先が消えた等）の「削除案」を `PROPOSALS/<date>-memory-curation-<proj>.md` に**提案として**書く。**適用はしない**。
- ライブセッション中の memory は append-only。整理（統合・削除・改訂）はこの反射パス + 人間承認のみ。

### Step 8: 後始末と報告
- 処理済み inbox ファイルを `PROCESSED/` へ移動。`STATE` の `last_run` を更新。
- 報告: 処理件数 / クラスタ数 / 適用した memory カード / memory 反射の提案書（Step 7 で生成した場合）/ 停止中の提案（PR）一覧 / 棄却理由付きの棄却リスト。

## 禁止
- 1回きりの事象を rules / skill へ昇格させる（memory 止まり。構造的再発の証拠が要る）。
- rules / skills / hooks の自動マージ（提案で停止。94 のガードレール）。
- memory カードの統合・削除・改訂の自動適用（追加のみ自動可。整理は提案止まり）。
- 生トランスクリプトの全文をメインコンテキストへ読み込む（必ずサブエージェント経由で要約抽出）。
- 根拠（教訓ID・セッションID・出現回数）の無い昇格案。
- 秘密情報（トークン・鍵・パス内の個人情報）を教訓・提案へ転記する（マスクして書く）。

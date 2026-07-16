---
name: distill-preferences
description: Claude Codeログの発話ダイジェストから、ユーザーの指示のクセ・嗜好・思考パターンを抽出し、レビュー後に feedback memory として保存する半手動の蒸留手順。
---

# distill-preferences

recall の蒸留層の手順。蓄積されたセッションログから生ログ → 嗜好 → memory への変換を、
**人間のレビューを挟みながら**行う。自動保存はしない（的外れな抽出の蓄積を防ぐため）。

## 前提

- 適用先 memory: `~/.claude/projects/<proj>/memory/`（プロジェクト別 auto-memory）
- 既存の人物像メモリを参照し、重複を作らない
- memory の書式・型(user/feedback/project/reference)はグローバル CLAUDE.md の「Memory」節に従う

## 手順

### 1. ダイジェスト生成（増分）
```bash
cd <recall-clone-dir>  # recall リポジトリのルートへ移動
python3 distill/extract.py          # 前回の続きから（状態ファイルで管理）
# 全件やり直す場合: python3 distill/extract.py --all
```
→ `distill/out/digest-<date>.md` が出力される（人間の発話のみ、機微情報マスク済み）。

### 2. パターン抽出（Claudeが実施）
ダイジェストを読み、以下の観点で**繰り返し現れる**シグナルだけを拾う。単発は採らない。

- **訂正・差し戻し** … 「違う」「そうじゃなくて」「やめて」「戻して」等。Claudeの何を嫌ったか＝守るべきルール。
- **明示的な指示の好み** … フォーマット指定、粒度、言語、確認の取り方、ツール選択の傾向。
- **思考パターンの裏付け/更新** … 既存の thinking-style 系 memory カードを補強 or 修正する新証拠。
- **頻出ドメイン/技術** … `user-profile` の技術スタックを更新すべき新情報。

各候補に「根拠（ダイジェスト内の発話を1〜2個）」「型(user/feedback/project)」「既存memoryとの重複/更新先」を付ける。

### 3. レビュー（人間が実施）
抽出候補をユーザーに提示し、採否・表現を確認する。**承認されたものだけ**次へ。
（推測は推測と明示。憶測でルール化しない。）

### 4. memory へ反映
- 新規 or 既存ファイル更新（重複を作らない。既存を更新できるなら更新）。
- feedback 型は本文に **Why:** と **How to apply:** を必ず添える。
- 関連 memory を `[[name]]` でリンク。
- `MEMORY.md` の索引に1行追記（新規時）。

### 5. 後始末
- `distill/out/` は git 管理外。レビュー済みなら消してよい。
- 誤って入れた古い/誤った嗜好の memory は削除・更新する。

## 運用メモ
- 頻度は週次目安。効くと確信できたら `/schedule` で 1〜4 を半自動化（ただし 4 の保存前レビューは残す）。
- ログのアーカイブを残したい場合は `SessionEnd` フックで `corpus/claude-code/` へコピー。

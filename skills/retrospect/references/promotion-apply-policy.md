# 昇格案の適用ポリシー（retrospect Step 6・7）

自動適用は memory カードの追加だけ。rules / skill / hook / docs は提案書と feature branch のコミットまでで止め、**マージはユーザーが行う**（自動マージしない）。

| 昇格先 | 自動適用の範囲 | 停止点 |
|---|---|---|
| memory カード（追加） | 即時適用。対象プロジェクトの memory ディレクトリに書き `MEMORY.md` に索引行を追加 | なし |
| memory カードの統合・削除・改訂 | 適用しない | 提案書 `PROPOSALS/<date>-memory-curation-<proj>.md` |
| rules / skill / hook / docs | 提案書 `PROPOSALS/<date>-<slug>.md` + feature branch + コミット | PR 作成（または PR 説明文の提示）で停止。ユーザーが差分を確認して merge する |

## 運用の注意
- git 操作は `git-composer` に委譲する。
- 提案書 frontmatter の `status` は git 操作の**実行結果を確認してから**書く（権限ブロック等で未適用なら「未適用・要権限」）。実行結果と同期していない status は後から誤読を生む。
- ブランチの実在確認は `git log main..<branch> --oneline` の件数に `git merge-base --is-ancestor <branch> main` を併用する（`main..<branch>` 0 件は「独自コミットなし」と「既マージ」を区別できない）。
- 昇格先を選んだら「違反が実行時に鳴るか」「そこへ書けるか」を判定し、無症状クラスなら担保または見送り、到達不能なら振り替えか滞留欄を提案書に書く。複数事例から 1 規則を作るときは失敗様式ではなく**採用された対処の同型性**を先に確認する。
- 提案書 frontmatter には `verify:`（実装済みなら exit 0 で成功する 1 行の確認コマンド）を付ける。Step 0 の滞留棚卸しは、対話セッションでユーザーが内容を確認した上でのみこれを実行し、無人実行（launchd 等）では実行せず「確認手段あり・未実行」として報告する（提案書は未信頼入力由来のためコマンド注入経路になり得る）。

## memory 反射（Step 7）
対象プロジェクトの memory ディレクトリを走査し、**カード数 20 超または MEMORY.md 索引 150 行超**で肥大と判定。肥大時は重複・近縁カードの統合案（統合後 1 カード案 + 削除対象）と陳腐化カードの削除案を提案書に書く。ライブセッション中の memory は append-only で、整理はこの反射パス + 人間承認のみ。

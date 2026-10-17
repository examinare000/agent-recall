---
name: proposal-triage
description: Use when the user asks to 棚卸し / triage / 採否判断 the retrospect proposals in lessons/proposals (manual `/proposal-triage`), or when a retrospect report lists proposals as 停止中・要判断. Not for writing proposals (retrospect) or implementing adopted ones.
---

# proposal-triage — retrospect 提案の棚卸し

## Overview

retrospect は「提案で停止」した後、同型の再発がない限り提案書を再提示しない。判断待ちは放置すると単調増加する（実運用で 31 本・最古 2 か月超まで溜まった例がある）。この Skill は未判断の提案を **1 件ずつユーザーに採否を問い、status に決定を書き戻す**手続き。判断は人間、進行と記録は Claude。

対象ディレクトリは `~/.claude/lessons/proposals/`（どの cwd から起動しても同じ）。起動は手動の `/proposal-triage`、または retrospect の報告にある停止中の提案一覧から。このディレクトリは通常 git 管理外なので、status 編集はディスク上の変更で足りる。

## 手順

1. **棚卸し**: 各 `*.md` の `status:` 行を読む。`適用済み` / `棄却` / `採用` / `保留` のいずれかで**始まる**ものは確定済み。それ以外（`提案`、`未適用`、`適用結果は末尾…`、`条文 1 は…` など）が候補。件数と最古日付を先に報告する。
2. **実体突合（自動で閉じる）**: 候補ごとに `target:` と差分案の固有語句を `~/.claude/rules/*.md`・`~/.claude/skills/*/SKILL.md`・対象スクリプトで grep する。「実在」は **`target:` のファイル（または改題・移設先）に、差分案と同趣旨の条文があること**。語句だけ一致して対象が違うヒット（別 skill の無関係な規定など）は実在としない。実在すれば status を `適用済み（<repo 相対パス>:<行> に実在。<日付> grep 確認）` に書き換え（パスは `target:` と同じ repo 相対表記）、ユーザーには問わない。提案書末尾の「適用結果」節に実出力があるものも同様。
3. **一問一答**: 残りを古い順に AskUserQuestion で尋ねる。1 呼び出しで扱う提案は 1 件だけ（複数の提案を 1 呼び出しに並べない）。質問文は「日付-slug: 何を・どこへ・根拠の件数」を 3 行以内に圧縮し、選択肢は `採用` / `棄却` / `保留` と、提案書が複数案を持つ場合はその分割（例: (a)(c) のみ）。提案本文を丸ごと読み上げない。
4. **記録**: 回答ごとに `status:` を `採用（<日付> ユーザー判断。<実装先・実装バッチ>）` / `棄却（<日付> ユーザー判断: <理由>）` / `保留（<日付> ユーザー判断: <再提示条件>）` へ書き換える。既に消滅した対象（カード・ファイルが無い）は `採用・対象消滅（…）` のように実状態を書く。
5. **即時適用と実装バッチの切り分け**: 採用のうち memory カード・docs（ADR / trial-log）・提案書の status だけで済むものはその場で適用する。rules・skill 本体・設定・スクリプトの変更は「実装バッチ」として表にまとめて報告し、着手はユーザー指示を待つ。
6. **完了マーカー**: `lessons/state.json` の `last_run` の値を `lessons/proposals/.triage-done` に書く（`printf '%s' "$last_run" > .triage-done`）。これは「この `last_run` 時点の棚卸しは済んだ」という目印で、次の retrospect 実行で `last_run` が進むまで再棚卸しの必要が無いことを示す。
7. **コミット**: git 管理下の提案書・docs に変更があれば git-composer へ 1 回で委譲する。

## Quick Reference

- 起動: 手動の `/proposal-triage`、または retrospect 報告の「停止中の提案」一覧から。自動の催促 hook は持たない。
- 実装バッチの候補先: rules / skill 本体の変更は対象リポジトリで提案ブランチを切って行う。

## Common Mistakes

- **status の語彙を増やす**: 「適用コミット済み」「差分案1=適用済み」は確定に見えるが催促対象のまま残る。確定は必ず 4 語のいずれかで始める。
- **ユーザーに読ませて判断させる**: 提案本文の転記は不要。判断に要るのは「何を・どこへ・根拠の件数・滞留中の再発」だけ。
- **採用＝実装と混同する**: 採用は決定の記録。rules / skill / 設定の変更は別バッチで、着手前にユーザーへ表で提示する。

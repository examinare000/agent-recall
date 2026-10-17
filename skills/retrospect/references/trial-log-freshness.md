# trial-log の新鮮度判定（retrospect Step 2）

`retrospect` Step 2 で trial-log から「棄却・失敗の新規イベント」だけを教訓候補に取り込むための判定手順。手順はスクリプト化を前提とした仕様。手動実行時は下記「要点」を守り、詳細仕様は判断に迷ったときに参照する。

## 要点（手動実行時）

- `docs/trial-log/*.md` を探索起点以下から**全件**列挙する（mtime で除外しない）。
- イベント ID（`trial-log:` + source・見出し・本文・出現順の hash）が `processed_ids` にあれば必ず除外する。
- 新規とみなすのは、見出しの日付が `last_run` の暦日より後、または当該追記の Git 導入 commit の committer 時刻が `last_run` より後のもの。Git 履歴が無ければ未観測 fingerprint を代替根拠にする。
- 本文と `path:line` を実際に確認できた occurrence だけ `processed_ids` に加え、1 source の全 occurrence を検証できたときだけ fingerprint を保存する。

## 詳細仕様

1. 毎回、探索起点以下から任意の深さにある `docs/trial-log/` 直下の `*.md` を**全件列挙**し、全 logical source を fingerprint / Git 比較まで進める。`.git`、`node_modules`、`.venv`、`vendor` などの依存物・キャッシュは探索から除く。`ios/docs/trial-log/*.md` のようなネストを固定深度の glob で落としてはならない。`last_run` より新しい mtime は処理順の優先度を上げるヒントにだけ使い、列挙・比較・採否の除外条件にはしない。
2. `canonical_source_key` は `SHA-256(NFC(realpath(git common-dir)) + NUL + NFC(リポジトリ相対パスを / 区切りにした値))` とする。同じ Git common-dir とリポジトリ相対パスを持つ通常 checkout / worktree は同一 logical source、異なる key は別 logical source とする。本文・アンカーは改行を LF、Unicode を NFC に正規化して hash するが、それ以外の意味のある空白と本文は削除・整形しない。
3. `trial_log_fingerprints` は次の JSON schema とする。値は観測済み fingerprint の**重複なし配列**であり、同じ source を複数 worktree / branch で見つけた時も異なる blob を追記して保持し、直前の1件で上書きしない。キーが無い既存 `state.json` では空 object として読む。
   ```json
   {
     "trial_log_fingerprints": {
       "<canonical_source_key>": [
         {"content_sha256": "<sha256>", "git_blob": "<blob-or-null>", "git_commit": "<commit-or-null>"}
       ]
     }
   }
   ```
4. 全列挙結果について現在の `content_sha256` を求め、Git 追跡済みなら blob とその由来 commit も fingerprint 用に求める。同じ `canonical_source_key` に同じ content / blob があっても、この段階ではイベントを除外せず、手順5で occurrence ID を先に計算する。未登録 fingerprint の保存は手順9の完了条件まで保留する。異なる logical source の同文は別に扱い、source をまたぐ本文 hash だけの重複排除はしない。
5. 本文を日付付き見出し・追記単位へ分け、イベント occurrence ID を `trial-log:` + `SHA-256(canonical_source_key + NUL + normalized_anchor + NUL + normalized_body + NUL + occurrence_ordinal)` として最初に計算する。`occurrence_ordinal` は同じ source 内で同一の normalized anchor / body が現れる文書順の1始まり番号であり、同文反復も別イベントとして識別する。`path:line` は変動するため ID 材料にはせず、現在の証拠照合に使う。
6. **全ての新規判定経路に共通する必須ゲート**として、occurrence ID が既に `processed_ids` にあれば候補から除外する。時刻、日付、Git 導入時刻、未観測 fingerprint のどれが `last_run` 後を示しても再生しない。fingerprint が未保存・検証未完了でもこのゲートは変えない。未処理 ID だけを手順7・8の新鮮度判定へ進める。
7. occurrence `k` の Git 導入時刻は、同じ Git common-dir の**全てのローカル利用可能 ref と、今回観測した全 worktree HEAD の和集合**を順序に依存せず走査して求める。commit 内の canonical リポジトリ相対パスで normalized anchor / body の出現数が `k` 以上、かつ全 parent で `k` 未満（root commit の parent 数は0）へ初めて跨ぐ commit だけを occurrence `k` の導入 commit とする。各導入 commit の**committer timestamp**を UTC に正規化し、複数 branch に導入 commit があれば最小値を採用する。既存 occurrence を含むファイルへの後続変更はこの跨ぎ条件を満たさないため再日付化しない。ローカルに無い・未 fetch の履歴は「Git evidence unavailable」とし、存在や時刻を推測しない。未コミット occurrence にも Git 導入時刻は無い。
8. 未処理 ID について、時刻付きイベントが `last_run` より後、または日付だけのイベントの暦日が `last_run` の ISO8601 暦日より後なら日付適格とする。同日の日付だけ・それ以前の日付・日付なしは、手順7の最小 Git 導入時刻が `last_run` より後なら候補とする。Git evidence が unavailable の場合は、同じ source / content fingerprint が未観測であることを非 Git fallback とする。したがって新規候補の条件は、必須の未処理 ID ゲートに加えて「日付適格、導入時刻が `last_run` 後、または Git evidence unavailable かつ未観測 fingerprint」のいずれかである。`trial_log_fingerprints` が無い移行時も本文と `path:line` の確認を省略しない。**受け入れ条件**: (a) `last_run=2026-08-17T14:32:00Z`、日付見出し `2026-08-17`、導入時刻14:53Zは新規、(b) 処理済み ID は post-`last_run` commit や pending fingerprint があっても再生しない、(c) branch の列挙順を変えても最小導入時刻は同じ、(d) occurrence を増やさない後続 file commit は既存 occurrence を再日付化しない。
9. 本文と対応する `path:line` を実際に確認できた occurrence ID だけを `processed_ids` に追加し、新規イベントだけを教訓候補へ渡す。移行時の過去イベントも、再処理防止用 ID を加える前に同じ内容確認を必須とする。1つの source / content 観測で見つけた**全 occurrence**の本文・`path:line` 検証が成功し、必要な全 ID が `processed_ids` に追加済みまたは既存である場合に限り、その fingerprint を `trial_log_fingerprints` へ追加する。同じ source / content の別 checkout は全 ID が処理済みとなるため再生せず、確認完了後は同じ fingerprint として重複追加しない。1件でも識別・検証できなければ fingerprint は保存せず「検証未完了・次回再処理」と報告するが、検証済み ID は保持して次回の重複再生を防ぐ。**受け入れ条件**: 部分検証しかできない content が fingerprint 登録によって黙ってベースライン化されず、次回も同じ content の未完了 occurrence が処理対象になること。既存 `last_run`、既存 `processed_ids`、その他の未知キーは削除・改名せず保持する。

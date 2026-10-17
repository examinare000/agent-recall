# 教訓候補の根拠検証（retrospect Step 2）

候補ごとに根拠参照を付け、機械的に解決できたものだけを evidence として扱う。

## corpus 由来の候補
- バルク読みを委譲する Explore / haiku サブエージェントには、各候補に **秘密を含まない**特徴的な逐語部分文字列（30〜120 字、単一発話内）+ 出典 corpus ファイル名を必ず添えさせる。付けられない観察は `ungrounded` と明記させる（黙って混ぜさせない）。
- 受領後、部分文字列を recall `memory_search`（ツール名は導入形態で異なる: user-scope 登録では `mcp__recall__memory_search`、プラグイン導入では `mcp__plugin_agent-recall_recall__memory_search`） で照合し、ヒットしたチャンク本文（`memory_get`）に含まれることを確認して `recall:<chunk_id>` へ解決する。解決不能な参照は**その参照だけ**落とす（候補ごとは落とさない）。
- 解決不能な参照は棄却前に二分する: 参照が指すセッションの索引 chunk 数を確認し（`sqlite3 "${RECALL_DB_PATH:-$HOME/.claude/agent-recall/index/recall.db}" "SELECT count(*) FROM chunks WHERE source_file LIKE '%<session>%'"`）、僅少（目安 2 以下）なら `unindexed`（索引被覆の限界）、十分あるのに不一致なら `search-failure`（捏造疑い）。
- 信頼度降格（`origin: unknown` 相当への 1 段下げ・rules / skill 昇格根拠からの除外）は **search-failure で全参照が落ちた候補のみ**。unindexed は参照を落とすが降格せず、出現回数カウントには `session:<id>` を用いる。
- evidence には `session:<id>` に加えて可能な限り `recall:<chunk_id>` を含める（retrospect の evidence 形式の具体化）。

## trial-log 由来の候補
- リポジトリ内ファイルなので、グラウンディングはファイル実在と当該行の照合で足りる（上記の逐語照合・二分は適用しない）。evidence は `<repo>/docs/trial-log/<file>:<line>`。
- 新規イベントの判定は `trial-log-freshness.md`。

## 抽出対象に含める軌跡シグナル
フックによるブロック（`exit 2`）、permission / 分類器拒否、`NEEDS_DECISION` / `BLOCKED` 往復、同一タスクの再委譲、レビュー拒否後の手戻り。オーケストレーション設計の教訓候補として扱う（コードの正当性は code-reviewer の役割）。

## 旧形式の inbox
frontmatter の無い候補は inbox の形式（type/project/date/summary/evidence/origin）へ正規化して扱う（「出所」記載は `origin:` に写像）。

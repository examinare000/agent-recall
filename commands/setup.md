---
description: recall（自己改善基盤）の対話セットアップ — メモリ保持形式・蒸留方法・索引構築を質問形式で確定し、config.env/setup.json を生成する
allowed-tools: AskUserQuestion, Bash, Read, Write, Edit, Glob
---

# /agent-recall:setup

このコマンドは、これを実行するエージェント（あなた）への手順書です。
ユーザーと対話しながら Step 0 → 4 を順番に実行し、`~/.claude/agent-recall/config.env` と
`~/.claude/agent-recall/setup.json` を生成してください。

## 前提

- `${CLAUDE_PLUGIN_ROOT}` はプラグインとして導入された場合に設定される、プラグイン本体（このリポジトリのコピー）のルートパス。
  プラグイン環境外（このリポジトリを手動 clone してこのコマンドファイルを直接読んで実行する人）向けには、
  `${CLAUDE_PLUGIN_ROOT}` が未設定なら「この `commands/setup.md` が置かれているリポジトリのルート」
  （`commands/..`）を代わりに使ってください。以降 `<PLUGIN_ROOT>` と書いたら、この優先順位で解決したパスを指す。
- 利用者データの標準置場は `~/.claude/agent-recall/`（config.env / setup.json / index/）。プラグイン本体
  （cache 配下、更新のたびに揮発しうる）とは別。
- 各 Step は**再実行安全**にすること: Step の冒頭で `~/.claude/agent-recall/config.env` と `setup.json` を読み、
  該当する項目が既に設定されていれば「現在値: `<値>`」を提示したうえで
  「このままでよいか / 変更するか」を聞いてから進める（初回と同じ質問をいきなり出さない）。
- 対話の各質問は `AskUserQuestion` で提示する（header は12字以内、options は2〜4件、詳細は各 Step の指示に従う。
  自由記述が必要な項目は選択肢に「自由記述で入力する」を含め、選ばれたら通常のテキスト応答として受け取る）。

---

## Step 0: 前提検査（質問なし）

1. **uv の存在確認**
   ```bash
   command -v uv
   ```
   無ければ、以下を提示してセットアップを**中断**する（Step 1 以降に進まない）:
   - macOS: `brew install uv`
   - Windows: `winget install --id=astral-sh.Uv -e`
   - それ以外 / 上記が使えない場合: https://docs.astral.sh/uv/getting-started/installation/ の手順に従う
   - 補足: `bin/recall-serve.sh`（MCP サーバ起動スクリプト）は uv 不在時にエラー終了する設計のため、
     uv が無いと recall MCP は動作しない。

2. **jq の存在確認**（必須ではない）
   ```bash
   command -v jq
   ```
   無くても中断しない。`hooks/archive-session.sh` は jq があれば使い、無ければ python3 にフォールバックする
   実装済みの挙動なので、「jq が見つかりませんでしたが python3 フォールバックで動作します」とだけ伝える。

3. **依存関係の同期**（初回 MCP タイムアウト予防）
   ```bash
   uv sync --directory "<PLUGIN_ROOT>"
   ```
   plugin install はファイルコピーのみで `uv sync` を行わないため、これを実行しないと
   MCP サーバ（`recall serve`）の初回起動が依存解決待ちでタイムアウトしうる。
   失敗した場合はエラー内容を提示してセットアップを中断する。

4. **user-scope `recall` MCP 登録の検出**
   ```bash
   claude mcp list
   ```
   出力には登録名だけでなく起動コマンドも表示されるため、これで判別する:
   プラグイン版は `bin/recall-serve.sh` を起動コマンドとして持つのに対し、
   **user-scope で単体登録された `recall`** は `uv run --directory <path> recall serve` を
   起動コマンドとして持つ（登録名が両方とも `recall` になり得るため、名前だけでは判別できない）。
   後者が見つかった場合:
   - 起動コマンドが異なる＝別プロセスのため両者は**衝突せず共存できる**が、recall MCP サーバ（uv run プロセス）が
     二重起動になり無駄である旨を伝える。
   - `AskUserQuestion` で確認する:
     - question: "user-scope に登録済みの recall MCP が見つかりました。二重起動を避けるため削除しますか？"
     - header: "recall重複"
     - options:
       - label: "今すぐ削除する", description: "`claude mcp remove recall` を実行し、以後はプラグイン版のみ使う"
       - label: "そのままにする", description: "両方使う（二重起動になるが動作はする）"
       - label: "後で自分で判断する", description: "何もせず案内だけ表示する"
   - 「今すぐ削除する」が選ばれたら `claude mcp remove recall` を実行し、結果を報告する。
   - 見つからなければ何も聞かず次に進む。

---

## Step 1: メモリ保持形式

既存の `config.env` / `setup.json` があれば読み、各項目の現在値を提示してから聞くこと（冒頭の再実行安全設計を参照）。

1. **corpus 位置**（既定 `~/.claude/corpus`）
   - question: "セッションアーカイブ（corpus）の保存先はどこにしますか？"
   - header: "corpus位置"
   - options:
     - label: "既定を使う (~/.claude/corpus)", description: "特別な理由がなければこちら"
     - label: "カスタムパスを指定する", description: "自由記述でパスを入力"
   - カスタムが選ばれたら絶対パスを受け取る。既定と同じ場合は config.env に書かない（Step 4 参照）。

2. **アーカイブ除外プロジェクト**（既定なし）
   - `~/.claude/projects/` 配下のディレクトリを `Glob` 等で列挙し、選択肢として提示できるようにする
     （0件でも構わない。列挙できない場合は自由記述のみで進める）。
   - question: "アーカイブ対象から除外したいプロジェクトはありますか？"
   - header: "除外対象"
   - multiSelect: true
   - options: 列挙したプロジェクト名 + 「なし（既定）」+「自由記述で入力する」
   - 「なし」以外が選ばれた場合、選択された（または自由記述された）プロジェクト名を1行1件として
     `~/.claude/agent-recall/archive-exclude.txt` に書き出す（今は実行しない。Step 4 でまとめて書く）。
   - 「なし」が選ばれた場合は何も書かない（ファイル自体を作らない）。

3. **lessons 位置**（既定 `~/.claude/lessons`）
   - question: "教訓候補（lessons）の保存先はどこにしますか？"
   - header: "lessons位置"
   - options:
     - label: "既定を使う (~/.claude/lessons)", description: "inbox/processed/proposals を配下に作成"
     - label: "カスタムパスを指定する", description: "自由記述でパスを入力"
   - 確定したパスの配下に `mkdir -p <lessons_dir>/inbox <lessons_dir>/processed <lessons_dir>/proposals` を実行する
     （既存なら何もしない。`mkdir -p` は冪等）。

---

## Step 2: 蒸留方法

1. **マスク規則**（既定: 同梱 `distill/extract.py`）
   - question: "発話ダイジェスト抽出・機微情報マスクにはどのスクリプトを使いますか？"
   - header: "マスク規則"
   - options:
     - label: "同梱の distill/extract.py を使う（既定）", description: "sk-/gh*_/AKIA/JWT 等を正規表現でマスク"
     - label: "自前スクリプトのパスを指定する", description: "自由記述で絶対パスを入力（RECALL_EXTRACT_PY_PATH）"

2. **週次蒸留の自動化**
   - question: "週次の蒸留（distill）と振り返り（retrospect）を自動実行しますか？"
   - header: "週次自動化"
   - options:
     - label: "自動化する", description: "macOS なら launchd に登録、それ以外なら cron の例を表示するだけ"
     - label: "自動化しない", description: "手動運用のまま（後からいつでも設定可能）"

   「自動化する」が選ばれた場合、`uname` で OS を判定する。

   - **macOS の場合**:
     1. `schedulers/launchd/com.example.recall.weekly-distill.plist` と
        `schedulers/launchd/com.example.recall.retrospect.plist` を、`<PLUGIN_ROOT>` を基準に
        `sed` でラベルとパスを展開する（README の展開例と同じ規約に従う。`${HOME}` トークンは
        ProgramArguments だけでなく StandardOutPath/StandardErrorPath にも登場するため、
        プレフィックス部分文字列ではなくトークン全体を置換すること）:
        ```bash
        sed -e 's/com.example.recall/com.<user>.recall/g' \
            -e 's|${HOME}|'"$HOME"'|g' \
            -e 's|\${HOME}/.local/share/claude/recall|'"<PLUGIN_ROOT>"'|g' \
            "<PLUGIN_ROOT>/schedulers/launchd/com.example.recall.weekly-distill.plist" \
          > ~/Library/LaunchAgents/com.<user>.recall.weekly-distill.plist
        ```
        （retrospect.plist も同様に展開する。`<user>` は適当な識別子でよく、ユーザーに確認してもよい）
     2. **旧 `com.rio.*`（またはそれに類する過去導入時の independent な label）の plist が
        `~/Library/LaunchAgents/` に既に存在するか確認する**:
        ```bash
        ls ~/Library/LaunchAgents/ | grep -i recall
        ```
        既存の recall 関連 plist（`com.example.*` 以外の label で、weekly-distill / retrospect に相当するもの）
        が見つかった場合、**無断で置き換えず**、`AskUserQuestion` で提案のみ行う:
        - question: "既存の launchd ジョブ（`<検出したファイル名>`）が見つかりました。unload して新しい設定に置き換えますか？"
        - header: "既存ジョブ"
        - options:
          - label: "置き換える", description: "`launchctl unload <旧plist>` の後、新しい plist を load する"
          - label: "そのままにする", description: "既存ジョブに触れず、新規登録もスキップする"
       「置き換える」が選ばれた場合のみ `launchctl unload <旧plist>` を実行してから新しい plist を load する。
     3. 新規（または置き換え後）の plist を load する:
        ```bash
        launchctl load ~/Library/LaunchAgents/com.<user>.recall.weekly-distill.plist
        launchctl load ~/Library/LaunchAgents/com.<user>.recall.retrospect.plist
        ```
   - **macOS 以外の場合**: 実行はせず、cron 登録例を提示するだけに留める:
     ```
     # 例: 毎週月曜 09:00 に週次蒸留
     0 9 * * 1 cd <PLUGIN_ROOT> && ./distill/weekly-distill.sh
     # 例: 毎週日曜 07:00 に retrospect
     0 7 * * 0 cd <PLUGIN_ROOT> && ./schedulers/launchd/run-retrospect.sh
     ```
     （`crontab -e` で追記する旨を案内する。実行はユーザーに委ねる）

3. **蒸留に使う環境**
   - 質問はしない。「そのまま既定（`uv sync` 済みの環境の python3 / uv）でよい」旨だけ短く伝える。

---

## Step 3: インデックス構築

既存の `config.env` があれば `RECALL_MODEL_NAME` の現在値を提示してから聞くこと。

1. **埋め込みモデル**（既定 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`。
   `recall/config.py` の `MODEL_NAME` 既定値と同一。既定値が変わっていた場合はそちらを正とする）
   - question: "意味検索に使う埋め込みモデルはどれにしますか？"
   - header: "埋め込みモデル"
   - options:
     - label: "既定モデルを使う（多言語対応・軽量）", description: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
     - label: "カスタムモデル名を指定する", description: "自由記述で fastembed 対応モデル名を入力"

2. **初回索引構築を今実行するか**
   - question: "corpus の初回索引構築（`recall index`）を今実行しますか？"
   - header: "索引構築"
   - options:
     - label: "今すぐ実行する", description: "corpus が空でも警告が出るだけで正常（後から増分更新される）"
     - label: "後で自分で実行する", description: "`uv run --directory <PLUGIN_ROOT> recall index` を後から手動実行"
   - 「今すぐ実行する」が選ばれたら:
     ```bash
     uv run --directory "<PLUGIN_ROOT>" recall index
     ```
     を実行し、出力（`indexed=<n> skipped=<n> pruned=<n> chunks_written=<n> errors=<n>`）をそのまま報告する。
     corpus が空、または未作成の場合は `indexed=0` 等になるだけで異常ではない旨を添える。

---

## Step 4: 完了処理（質問なし）

1. **`~/.claude/agent-recall/config.env` を書く**
   - 対象ディレクトリが無ければ `mkdir -p ~/.claude/agent-recall` する。
   - 以下のキーのうち、**既定値と異なる回答があったものだけ** `KEY=VALUE` 形式で1行ずつ書く
     （既定のままの項目は書かない。ファイルは `source` されるシェルスクリプトとして扱われるため、
     パスに空白等が含まれる場合はクォートする）:
     - `RECALL_CORPUS_DIR`（Step 1-1 でカスタム指定された場合）
     - `RECALL_DB_PATH`（本コマンドでは明示的に聞いていないので、通常は書かない。将来的にカスタム化の質問を
       追加する場合のための予約列として扱う）
     - `RECALL_MODEL_NAME`（Step 3-1 でカスタム指定された場合）
     - `RECALL_MODEL_CACHE_DIR`（fastembed のモデルキャッシュ先。既定 `~/.cache/fastembed`。
       本コマンドでは明示的に聞いていないので、通常は書かない）
     - `RECALL_EXTRACT_PY_PATH`（Step 2-1 でカスタム指定された場合）
   - 全項目が既定のままだった場合、`config.env` は作成しない（既定 = 何も上書きしない、が正しい状態のため）。

2. **`~/.claude/agent-recall/setup.json` を書く**
   ```json
   {
     "version": "0.1.0",
     "completed_at": "<ISO8601日時。date -u +%Y-%m-%dT%H:%M:%SZ 等で取得>",
     "answers": {
       "corpus_dir": "<Step1-1 の確定値>",
       "archive_exclude": ["<Step1-2 で除外指定されたプロジェクト名の配列。無ければ空配列>"],
       "lessons_dir": "<Step1-3 の確定値>",
       "extract_py_path": "<Step2-1 の確定値>",
       "weekly_automation": "<'launchd' | 'cron_manual' | 'none'>",
       "user_scope_recall_removed": <true/false。Step0-4 の対応結果>,
       "model_name": "<Step3-1 の確定値>",
       "index_run_now": <true/false>
     }
   }
   ```
   （既に `setup.json` が存在し再実行だった場合は、変更された項目のみ更新し、他は既存値を保持する。）

3. **完了案内**
   ユーザーに次のメッセージを提示する:
   > セットアップが完了しました。次回セッションから `mcp__plugin_agent-recall_recall__*`
   > （例: `mcp__plugin_agent-recall_recall__memory_search`）ツールが利用可能になります。
   （Step 0 で user-scope の `recall` を削除しなかった場合は、`mcp__recall__*` も引き続き使えることも添える。）

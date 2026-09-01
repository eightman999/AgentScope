# AgentScope 仕様・実装計画

- 版: 0.1.0
- 状態: 実装前の承認待ち
- 作成日: 2026-09-01
- 正典: このファイルがAgentScopeの唯一の正典である。判断に迷ったら推測せず、該当節を読む。
- 矛盾解決: このファイルと派生計画・実装・運用メモが矛盾した場合は、このファイルを正とする。

## 1. Overview

### 1.1 目的

AgentScopeは、GitHubリポジトリURLを1つ受け取り、そのソフトウェア自身がAgentic AIとして動作しているかを、ソースコード・テスト・Git provenance・GitHubメタデータの証拠付きで監査するローカルアプリである。

このプロダクトが解く問題は、次の二つの混同である。

1. AIを使って開発されたことと、実行時にAgentic AIとして動作することの混同。
2. tool・MCP・LLM APIが存在することと、モデルが次のactionを選び、観測結果に適応することの混同。

単にREADMEをLLMへ渡して印象点を返すのではなく、AgentScope自身が読み取りtoolを選択し、観測結果に応じて再計画し、証拠が十分になるまで探索を続ける。

### 1.2 公開インターフェース

P0の利用者入力は、GitHubの公開リポジトリURLだけとする。

~~~text
agentscope audit https://github.com/eightman999/autoresearch-naval
~~~

利用者に次を要求しない。

- LLM APIキー
- 自由形式の監査プロンプト
- リポジトリのローカルパス
- 対象ファイルや調査順の指定
- scoreの手動補正

P0は公開リポジトリを対象とする。private repository、GitHub Enterprise、認証が必要なURLは、入力URL以外の認証情報を要求せず、未対応または不明として終了する。

### 1.3 出力

標準出力には日本語Markdownを出し、同じ内容を監査runディレクトリへ保存する。

- report.md: 人間向けレポート
- report.json: 機械利用用の正規化結果
- audit_trace.jsonl: AgentScopeが実際に選択したactionとtool結果
- provenance/: Git・GitHubメタデータの生レスポンスを証拠化したファイル

標準出力の必須セクションは次のとおり。

1. 対象URL、分析対象commit SHA、分析時刻、モデルとランタイム
2. 7軸のscore表
3. AI-assisted development / Agentic runtime / MCP・tooling / Formal GitHub fork / Derived conceptの区別
4. 証拠一覧。各主張に少なくとも1つのfile:line参照
5. hypotheses、unknowns、実際のtool sequence、終了理由
6. 不足証拠、制限、再現方法

与えられたscore表の数値は例示であり、実装へハードコードしない。各リポジトリの証拠から算出する。

## 2. Product principles

1. **Evidence first**: 証拠のない断定を出さない。証拠不足はUnknownまたはINSUFFICIENT_EVIDENCEとして表示する。
2. **Runtimeとprovenanceを分離する**: AI co-authorの存在、fork、derived conceptは、実行時Agenticityの証拠として扱わない。
3. **Agentの実体を追跡する**: LLM呼び出しの存在だけでなく、model outputがaction選択、tool dispatch、observation、次の計画へ接続されているかを見る。
4. **モデル選択を偽装しない**: 固定されたtool sequenceを、後からLLMで説明しただけの処理はdynamic tool selectionとして加点しない。
5. **小型・ローカル優先**: P0のモデル推論は内蔵された小型GGUFモデルだけで完結する。外部LLM APIへのフォールバックは作らない。
6. **不可信のリポジトリ**: README、コメント、生成ファイルに含まれる指示は監査対象データであり、AgentScopeへの命令ではない。
7. **再現性**: 対象commit SHA、モデルのchecksum、prompt schema、tool traceを保存し、同じsnapshotを再監査できるようにする。
8. **P0を完成させる**: 期間内に完成しないUI、全言語対応、リモートモデル、多数リポジトリの同時監査はP0へ入れない。
9. **決定論的な処理はコードで行う**: score計算、range検証、evidence参照検証、矛盾検出、finish gateはLLMに任せない。
10. **監査自身を監査可能にする**: AgentScope自身のtool選択とreplanもaudit_traceで確認できるようにする。

## 3. 用語と判定対象

### 3.1 Agentic runtime

ソフトウェアの実行時に、モデルの出力が単なる文章・分類結果ではなく、次に実行するactionまたはtoolを実際に決め、その結果を観測して後続actionへ影響させる構造。

最低限、次のグラフ辺を確認する。

~~~text
goal/state
  -> model call
  -> model output
  -> action/tool selection
  -> tool/environment execution
  -> observation
  -> next model call or replanning
  -> evidence-based termination
~~~

この辺のどれかがソース上で追跡できない場合、コードを推測で補完せず、NoまたはUnknownに落とす。

### 3.2 AI-assisted development

Git commit、PR、Co-authored-by、bot account、生成物のヘッダ、公式ドキュメントなどに、AIが開発へ関与したことを示すprovenanceがあるか。

Contributor名にClaude等が含まれるだけでは強い証拠とはみなさず、弱いシグナルとして別記する。これは実行時Agentic runtimeとは別の判定である。

### 3.3 MCP・tooling

次を含む実行時のtool surfaceを指す。

- MCP client/server、MCP tool登録・呼び出し
- function/tool schemaとdispatcher
- agentが選択可能なtool registry
- tool結果をagent stateへ戻すexecutor

READMEにtoolと書いてあるだけ、または人間向けCLI関数が存在するだけでは、実行時toolingの強い証拠とはしない。

### 3.4 Formal GitHub fork

GitHubのリポジトリメタデータにあるforkフラグとparent情報による公式fork関係。Git remoteに別URLがあること、コードが似ていること、READMEが参考元を挙げることだけではFormal GitHub forkとは判定しない。

### 3.5 Derived concept

明示的なURL、README、commit、license・credit、fork parent、コード由来などから、既知プロジェクトの概念・実装を引き継いだと判断できる状態。P0ではKarpathy/autoresearchを既知概念の初期エントリとして扱う。

単なる文字列類似や「似て見える」というモデルの印象はYesの根拠にしない。

## 4. MVP scope

### 4.1 P0: 必須

- [ ] GitHub公開URLを正規化し、owner/repoを抽出する。
- [ ] 対象のHEADをcommit SHAで固定して取得する。
- [ ] リポジトリをread-only snapshotとして扱い、対象コードを実行しない。
- [ ] README、主要設定、ソース、テスト、CI、Git履歴を探索できる。
- [ ] Python、JavaScript/TypeScriptを構文・呼び出し追跡の主対象とする。
- [ ] その他言語は安全なテキスト検索と限定的なcall graphで調査し、精度不足時はUnknownにする。
- [ ] LLM/API呼び出し候補を検出する。
- [ ] tool/MCP登録、schema、dispatcher、executor候補を検出する。
- [ ] planner、loop、state、retry、budget、termination候補を検出する。
- [ ] model callからaction選択・tool dispatch・observation・replanまでのcall/data flowを追跡する。
- [ ] Git log、Co-authored-by、author/committer、remote、GitHub fork metadataを調査する。
- [ ] Karpathy/autoresearch等の明示的なderived concept evidenceを調査する。
- [ ] AgentScope自身がtoolを選ぶagent loopを実装する。
- [ ] budget_remainingを持つstateと、ENOUGH_EVIDENCE / INSUFFICIENT_EVIDENCEのfinish判断を実装する。
- [ ] model outputをstrict JSON schemaで受け、参照ID・score range・根拠の有無を検証する。
- [ ] 7軸scoreを0.1刻みで算出し、根拠付きで出力する。
- [ ] scoreと別に5種類のYes / No / Unknown判定を出力する。
- [ ] 各score・各主要判定へ有効なfile:line evidenceを1件以上付ける。
- [ ] evidence不足の場合は数値0へ偽装せず、scoreをUnknownとして表示する。
- [ ] synthetic fixtureで固定workflow、dynamic agent、MCP-only、AI-assisted non-agent、fork/derived、insufficient evidenceを検証する。
- [ ] https://github.com/eightman999/autoresearch-naval をP0デモ対象として監査できる。

### 4.2 P1: P0後

- [ ] 最小Web UIまたはmacOS GUI。入力欄はURL一つだけ。
- [ ] Go、Rust、Java、Kotlin、Swiftへのtree-sitterベースcall graph。
- [ ] GitHub PR本文、Issue、Actions実行履歴、CODEOWNERSの追加調査。
- [ ] GitHub Enterprise/private repository対応。
- [ ] reportのGitHub blob URLリンクとブラウザ表示。
- [ ] known concept registryの追加・更新機構。
- [ ] audit runのresumeとキャッシュ。
- [ ] ユーザー指定の比較対象リポジトリ。

### 4.3 P2: 期間後

- [ ] 複数リポジトリの並列比較。
- [ ] 外部LLM provider。デフォルトのlocal-only境界は維持する。
- [ ] embeddingによる大規模semantic retrieval。
- [ ] multi-agent協調監査。
- [ ] 学習済みscore校正モデル。
- [ ] GitHub AppとしてのWebhook監視。

## 5. 利用フロー

### 5.1 正常系

1. 利用者がGitHub URLを1つ渡す。
2. URL validatorがgithub.comの公開repository URLか確認する。
3. repository sourceがHEADとcommit SHAを固定する。
4. preflightがファイル一覧、言語、サイズ、README候補、テスト候補、Gitメタデータ候補を作る。
5. 初期stateに次の仮説・unknownを設定する。
   - 仮説: This may be a fixed workflow
   - 仮説: There may be external agent control via MCP
   - unknown: Who chooses the next action?
   - unknown: Is there environment feedback?
   - unknown: Is there formal fork or derived provenance?
   - budget_remaining: 14
6. Agentが候補toolから次のactionを1つ選ぶ。
7. toolはline-numbered observationとevidence IDを返す。
8. Agentはstate、observations、unknownsを更新し、次のtoolを再選択する。
9. finish_auditを呼び出す。
10. controllerがfinish条件とevidence coverageを検証する。
11. scorerがFactGraphとEvidenceLedgerからscoreを決定論的に計算する。
12. reporterがMarkdown、JSON、traceを保存して出力する。

READMEを最初に読むことは推奨ヒントとしてpromptへ示してよいが、P0の通常実装ではREADMEから始める固定sequenceを強制しない。実際の最初のtoolと後続toolはmodel outputとしてtraceへ残す。

### 5.2 終了条件

ENOUGH_EVIDENCEを受け入れるには、最低限次を満たす。

- READMEまたは同等の概要資料を調査済み。
- LLM/API候補と、その呼び出し元または不在のcoverageを調査済み。
- tool/MCP候補とdispatcherまたは不在のcoverageを調査済み。
- loop/state/retry/termination候補を調査済み。
- model outputがactionを選ぶかどうかをcall/data flowで確認または反証済み。
- Git provenance/fork/derived conceptを調査済み。
- verification/test候補を調査済み。
- 7軸と5判定の全項目が、少なくとも1件の検証済みevidenceまたはUnknown理由を持つ。

Agentが早すぎるENOUGH_EVIDENCEを返した場合、controllerはそのまま断定しない。不足項目をstateへ戻し、budgetが残っていれば再探索を要求する。budgetが尽きた場合はINSUFFICIENT_EVIDENCEとする。

### 5.3 不足・失敗時

- URL不正: 実行せず、入力形式エラー。
- clone/取得失敗: repository_acquisition=failed。scoreは原則Unknown。
- GitHub API制限: Git snapshotで取れる範囲を続行し、fork metadataはUnknown。
- 巨大ファイル・binary・symlink: 読まずにskipし、coverageへ記録。
- modelのschema失敗: エラーを添えて1回だけ再要求。再失敗ならrunをfailedまたはINSUFFICIENT_EVIDENCEで停止。
- 不存在evidence ID、行番号不一致、score range違反: 該当評価全体を破棄してUnknown。部分修復やclampは禁止。
- 静的call graphが不完全: 推測で補完せず、Unknownと不足edgeを報告。

## 6. Architecture

### 6.1 技術方針

- 実装言語: Python 3.12以上。
- CLI: Python標準argparseを基本とし、P0の依存を最小化する。
- schema validation: Pydantic 2系または同等の厳格なvalidator。
- repository取得: git executableをallowlist付きで呼ぶ。
- GitHub API: 標準HTTP clientでpublic endpointを呼ぶ。APIレスポンスは保存し、失敗はUnknownへ伝播する。
- local model runtime: llama.cppを内蔵runtimeとして採用する。
- model baseline: Qwen3-0.6BのGGUF量子化版を第一候補とする。最終採用はaction選択・schema遵守・evidence参照テストを通す最小候補で決める。
- model distribution: model manifestとchecksumをsourceへ置き、weightsはGitの通常差分へ混ぜず、release bundleへ同梱する。releaseに同梱できないlicense・サイズ問題は実装完了とみなさない。
- 外部LLM API: P0では実装しない。

Qwen3-0.6Bを第一候補にする理由は、小型の0.6Bモデルであり、公式model cardにApache-2.0、ローカル利用、llama.cpp対応が記載されているためである。ただし、実際の監査品質はこの計画のfixtureとreal-model gateで判定し、モデル名だけで採用確定しない。

llama.cppはGGUFのlocal modelを実行でき、Apple Silicon、量子化、Metal backendを対象としている。配布時は採用commit、binary version、model SHA256をmanifestへ固定する。

参照:

- [Qwen/Qwen3-0.6B model card](https://huggingface.co/Qwen/Qwen3-0.6B)
- [llama.cpp](https://github.com/ggml-org/llama.cpp)
- [GitHub REST repositories API](https://docs.github.com/en/rest/repos/repos)
- [GitHub REST commits API](https://docs.github.com/en/rest/commits/commits)

### 6.2 推奨モジュール構成

~~~text
src/agentscope/
  cli.py
  application.py
  domain/
    state.py
    facts.py
    evidence.py
    scoring.py
    classifications.py
  acquisition/
    github_url.py
    git_snapshot.py
    github_metadata.py
  analysis/
    inventory.py
    search.py
    line_reader.py
    llm_candidates.py
    tool_candidates.py
    control_flow.py
    provenance.py
    verification.py
  agent/
    loop.py
    action_schema.py
    prompt.py
    tool_registry.py
    policy.py
  model/
    provider.py
    local_llamacpp.py
    manifest.py
  report/
    markdown.py
    json.py
    lint.py
resources/
  model-manifest.json
  action-schema.json
  report-schema.json
tests/
  fixtures/
  unit/
  integration/
  golden/
~~~

各層の責務は次のとおり。

- acquisition: URL・snapshot・GitHub metadataだけを担当する。
- analysis: 静的候補とline-numbered observationを作る。分析対象コードは実行しない。
- agent: modelがtoolを選び、stateを更新し、finishを要求するloopを担当する。
- domain: FactGraph、EvidenceLedger、score、classificationを決定論的に管理する。
- report: 既に検証済みのdomain値だけを表示する。LLMの自由文をscoreへ変換しない。
- model: local inferenceのprovider boundary。agent loopからllama.cpp固有実装を隠す。

### 6.3 Agent tools

tool registryは、名前、入力schema、説明、side effect、返却するevidence種別を持つ。

| tool | 用途 | 主な出力 |
| --- | --- | --- |
| list_repo_tree | ファイル構成・サイズ・言語を確認 | 候補ファイル、coverage |
| read_file | 指定ファイルの限定行を読む | line-numbered excerpt、evidence |
| search_code | literal/regexとpath filterで検索 | hit行、候補symbol、evidence |
| inspect_llm_calls | LLM/API clientと呼び出し元候補を調べる | call sites、候補edge |
| inspect_tooling | MCP、tool schema、registry、dispatcherを調べる | tool surface候補 |
| trace_call_graph | symbol/fileからcall/data flowを追う | FactGraph edge、line evidence |
| inspect_git_provenance | log、author、committer、remoteを見る | provenance evidence |
| inspect_github_metadata | fork、parent、repo metadataを取得 | provenance artifact evidence |
| inspect_tests | test、CI、verification pathを見る | verification evidence |
| inspect_concept_lineage | 明示的なcredit、URL、derived conceptを見る | lineage evidence |
| finish_audit | ENOUGH/INSUFFICIENTを要求 | finish decision、missing unknowns |

toolはすべてread-onlyである。git metadataを保存することは対象repositoryを変更することではない。toolは対象コードをimport、build、test、package install、script executionしない。

### 6.4 Agent action schema

modelは自由文ではなく、次の形式だけを返す。

~~~json
{
  "kind": "tool_call",
  "tool": "read_file",
  "arguments": {
    "path": "README.md",
    "start_line": 1,
    "end_line": 120
  },
  "hypothesis": "The README may reveal whether the runtime has an agent loop.",
  "focus": ["agentic_runtime", "goal_directed_loop"]
}
~~~

finishの場合:

~~~json
{
  "kind": "finish",
  "decision": "ENOUGH_EVIDENCE",
  "reason": "All required paths were traced or explicitly marked unknown.",
  "missing_unknowns": []
}
~~~

validatorが保証すること。

- kind/tool/decisionはenum。
- argumentsはtoolごとのschemaに一致。
- pathはsnapshot内のrelative pathだけ。
- start_line、end_line、limit、budgetは許容range内。
- 未知のpropertyを拒否。
- tool registryにないtoolを拒否。
- evidence IDをmodelが返す場合、直前までにmodelへ提示した集合と照合する。
- schema失敗はエラー付きで1回だけretryし、再失敗で停止する。

### 6.5 Agent state

~~~json
{
  "run_id": "stable-run-id",
  "input_url": "https://github.com/owner/repo",
  "commit_sha": "固定されたSHA",
  "hypotheses": [
    {"id": "h1", "text": "This may be a fixed workflow", "status": "open"}
  ],
  "evidence_ids": [],
  "unknowns": [
    "Who chooses the next action?",
    "Is there environment feedback?"
  ],
  "visited_files": [],
  "observations": [],
  "action_history": [],
  "budget_remaining": 14,
  "termination": null
}
~~~

stateは各tool call後にimmutable eventとしてaudit_traceへ追記する。state全体のcurrent snapshotもrunディレクトリへ保存し、途中停止時に「何を読んだか」を確認できるようにする。

### 6.6 Agent loop

1. controllerがpreflight summary、state、tool catalogをpromptへ入れる。
2. local modelが1 actionをJSONで返す。
3. schema validatorが形状を検証する。
4. semantic guardがpath、range、budget、tool permissionを検証する。
5. toolを実行し、observationとevidenceをledgerへ追加する。
6. controllerがFactGraphとunknownsを更新する。
7. budgetを1減らす。
8. finishでなければ再度modelへ渡す。
9. finish時はsufficiency gateを通す。

通常経路での固定順fallbackは禁止する。modelが壊れた場合にread README、search tool、trace graphを自動で順番実行して「agentが選んだ」ように見せてはいけない。

### 6.7 Provider boundary

model呼び出しは次のinterfaceの背後に置く。

~~~text
ModelProvider.complete_action(context) -> RawModelResponse
~~~

P0実装:

- MockModelProvider: fixtureごとのaction scriptを返す。最初に実装する。
- LocalLlamaCppProvider: 内蔵GGUFをllama.cppへ渡す。同じschemaと戻り値を使う。

agent/domain/reportはproviderの種類を知らない。P0の本番factoryは常にlocal providerを選ぶ。mockはunit・integration・CI専用で、実行時AgentScopeのscoreを偽装する用途には使わない。

## 7. Evidence model

### 7.1 Evidence schema

~~~json
{
  "id": "e42",
  "claim_key": "runtime.model_controls_action",
  "source_kind": "repository",
  "file": "src/agent/loop.py",
  "start_line": 117,
  "end_line": 129,
  "display_ref": "src/agent/loop.py:117",
  "excerpt": "検証済みの対象行だけ",
  "excerpt_sha256": "行内容のhash",
  "commit_sha": "対象commit",
  "reason": "Model output is passed to the dispatcher.",
  "confidence": "high"
}
~~~

fileとlineは必須。report上の主参照は必ずdisplay_refのfile:line形式にする。generated metadataも監査runへmaterializeし、例えばprovenance/github-repository.json:1として行参照可能にする。

### 7.2 Evidenceの出所

- repository: snapshot内のソース、README、設定、test、CI。
- git: provenance/git-log.txt、provenance/git-remotes.txt等。
- github_api: provenance/github-repository.json、provenance/github-commits.json等。
- derived_manifest: 検索coverage、skip理由、line hash。ただし、単独でruntimeのpositive evidenceとはしない。

GitHub APIレスポンスはraw body、取得時刻、endpoint、HTTP status、対象URL、checksumを保存する。APIが使えないときに、空のデフォルト値をNoへ変換しない。

### 7.3 Evidence validation

report生成前に機械検証する。

- fileがsnapshotまたはprovenance artifactに存在する。
- start_line >= 1、end_line >= start_line。
- excerptが指定行と一致する。
- excerpt hashが一致する。
- commit SHAがaudit subjectと一致する。GitHub metadata artifactは取得対象URLとrun idを持つ。
- 主張に紐づくevidence IDがledger内に存在する。
- modelが作った未登録path、line、evidence IDを採用しない。
- line不足・破損・未読の参照は評価全体をUnknownにする。

不在を主張する場合は、search query、対象path、skip数、byte/file coverageをderived_manifestへ記録する。coverageが不十分なら「見つからなかった」をNoとせずUnknownと表示する。

### 7.4 FactGraph

EvidenceLedgerの上に次のnode/edgeを作る。

| node/edge | 意味 |
| --- | --- |
| model_call | LLM/APIが呼ばれる |
| model_output | 応答が取得される |
| action_selector | 応答がaction候補を決める |
| tool_registry | tool集合が定義される |
| dispatcher | 選択結果を実行へ分岐する |
| observation | tool/environment結果を受ける |
| state | goal、hypothesis、unknown、budget等 |
| planner/replanner | 次のactionまたは計画を更新する |
| verifier | test、assertion、validator等 |
| termination | goal達成、evidence十分、retry上限等で終了する |

主要edgeは呼び出し行・代入行・分岐行・loop行と紐づける。FactGraphが完成しない場合は、部分graphと不足edgeをreportへ出す。

## 8. Scoreとclassification

### 8.1 共通ルール

- scoreの定義域は0.0から10.0。
- scoreはEvidenceLedgerとFactGraphからコードで算出する。
- modelは候補事実と仮説を出してよいが、最終score、順位、range補正はできない。
- verified absenceの0と、evidence不足のUnknownを区別する。
- scoreが算出不能ならJSONではscore=null、状態はunknown、Markdownでは? / 10とする。
- scoreが0でも、少なくとも1件の直接または検証済みnegative evidenceを付ける。
- 主要なscore行へfile:lineを付けられない場合、レポートlintを失敗させる。

### 8.2 7軸

| 軸 | 0.0 | 5.0前後 | 10.0 |
| --- | --- | --- | --- |
| Originality / 自作度 | 公式fork、ほぼコピー、独自性を示す証拠なし | substantial adaptationまたはprovenance不足 | 独立実装と新規要素が複数の直接証拠で確認できる |
| Agenticity | modelがruntime control flowを決めない | model controlまたはloopの一部だけ確認 | model選択、tool実行、観測、replan、終了が一つの実行pathでつながる |
| Dynamic tool selection | toolなし、または固定sequence | tool surfaceはあるが選択・dispatchが部分的 | model出力が2つ以上の候補から実行toolを選び、観測で選択が変わる |
| Feedback adaptation | observationがない、または無視 | loopはあるが適応edgeが弱い | success/failure/observationが次のaction・state・planを変える |
| Goal-directed loop | loop/goal/terminationなし | state、budget、retryまたはterminationの一部 | goal、unknown、budget、replan、十分/不可能判定が実装される |
| Verification | test・assertion・検証経路を確認できない | testsまたはCIはあるが対象pathが限定的 | target pathのunit/integration、失敗系、CI、再現可能な検証がある |
| Agent tooling | tool surfaceなし | registry/schema/dispatcherの一部 | typed tool registry、executor、MCPまたは同等surface、observation・traceまである |

各軸は上表のlevelをそのまま自由文で採点せず、実装ではsubfactorを構造化する。例:

- dynamic tool selection: candidate_count、model_control_edge、dispatch_edge、observed_variation。
- feedback adaptation: observation_to_state_edge、state_to_next_action_edge、failure_branch、replan_edge。
- goal-directed loop: explicit_goal、state_memory、budget_or_retry、termination_gate、infeasible_detection。
- verification: target_tests、negative_tests、CI、assertion、reproducibility.

subfactorの未知値は0として埋めず、そのscoreをUnknownまたはlow confidenceにする。

### 8.3 Binary classification

reportの固定表示:

~~~text
AI-assisted development: Yes | No | Unknown
Agentic runtime: Yes | No | Unknown
MCP/tooling: Yes | No | Unknown
Formal GitHub fork: Yes | No | Unknown
Derived concept: Yes — Karpathy/autoresearch | No | Unknown
~~~

判定規則:

- AI-assisted development=Yes: AI bot、AI co-author、AI生成ヘッダ、PR/commit metadata等の明示的証拠がある。Contributor表示名のみはweak signalとして別記する。
- Agentic runtime=Yes: model call、model-controlled action、実際のdispatch、observation、後続actionへの影響が追跡できる。単なるchat/completion/classificationはNo。
- MCP/tooling=Yes: runtimeでMCPまたはtyped/dynamic tool surfaceが登録・dispatchされる。READMEだけならUnknownまたはNo。
- Formal GitHub fork=Yes: GitHub metadataのfork=trueまたはparentが確認できる。fork=falseはNo。API未取得時はUnknown。
- Derived concept=Yes — Karpathy/autoresearch: 明示的なURL、credit、fork parent、commit lineage等で関係が確認できる。概念類似のみはUnknown。

### 8.4 断定強度

各項目にconfidenceを持たせる。

- high: 直接の実装行または公式metadataと、関連edgeが揃う。
- medium: 直接証拠はあるがcaller、履歴、coverageの一部が限定的。
- low: 弱いsignal、推論、部分的な静的解析のみ。
- unknown: 必要な証拠がない、矛盾している、または取得に失敗した。

## 9. Report contract

### 9.1 Markdown

score表の最低形:

| 評価score | score / 10 | 状態 | 根拠 |
| --- | ---: | --- | --- |
| Originality / 自作度 | 8.2 | confirmed | src/...:12、provenance/...:1 |
| Agenticity | ? | unknown | src/...:42、不足edge: model output -> dispatch |
| Dynamic tool selection | 0.0 | negative | src/...:88 |
| Feedback adaptation | 1.0 | negative | src/...:101 |
| Goal-directed loop | 0.0 | negative | src/...:133 |
| Verification | 9.0 | confirmed | tests/...:20、.github/...:14 |
| Agent tooling | 7.0 | confirmed | src/...:55 |

数値、根拠、状態は例であり、score表へ固定値を入れない。表示されるすべてのevidence refは実在のfile:lineへ解決される必要がある。

### 9.2 JSON

~~~json
{
  "schema_version": "0.1",
  "subject": {
    "input_url": "https://github.com/owner/repo",
    "canonical_url": "https://github.com/owner/repo",
    "commit_sha": "sha",
    "snapshot_coverage": "full"
  },
  "runtime": {
    "model_id": "Qwen/Qwen3-0.6B-GGUF",
    "model_sha256": "sha256",
    "engine": "llama.cpp",
    "steps_used": 0,
    "termination": "ENOUGH_EVIDENCE"
  },
  "scores": [
    {
      "key": "dynamic_tool_selection",
      "score": 0.0,
      "state": "negative",
      "confidence": "high",
      "rationale_ja": "日本語の短い説明",
      "evidence_ids": ["e1"]
    }
  ],
  "classifications": {
    "ai_assisted_development": {"value": "unknown", "evidence_ids": ["e2"]},
    "agentic_runtime": {"value": "no", "evidence_ids": ["e3"]},
    "mcp_tooling": {"value": "yes", "evidence_ids": ["e4"]},
    "formal_github_fork": {"value": "no", "evidence_ids": ["e5"]},
    "derived_concept": {
      "value": "unknown",
      "label": "Karpathy/autoresearch",
      "evidence_ids": ["e6"]
    }
  },
  "evidence": [],
  "unknowns": [],
  "action_trace_ref": "audit_trace.jsonl"
}
~~~

### 9.3 レポートlint

report生成時に次をfail-closedで検査する。

- 必須score keyが7件ある。
- 必須classificationが5件ある。
- scoreがnullでない場合は0.0 <= score <= 10.0。
- score/classificationごとにevidence IDが1件以上ある。
- evidence ID、file、line、excerpt hashが解決する。
- unknownでない主張に根拠がある。
- model outputに由来する未検証の自由文を事実として表示していない。
- 内部marker、未解決ID、placeholderがreportへ漏れていない。

## 10. 安全性・リソース制限

### 10.1 URL・取得

- schemeはhttps、hostはgithub.comに限定する。
- owner/repo、.git、query、fragmentを正規化する。
- redirect先が許可host外なら拒否する。
- clone directoryはrun専用のtemp directoryへ作る。
- shallow cloneから開始し、provenance不足時だけ固定上限まで履歴を深くする。
- file数、個別サイズ、合計byte、1ファイルのline数、tool出力byte、stepsに上限を設ける。
- symlink、submodule、LFS、生成binaryは追跡方針を記録して必要ならskipする。

### 10.2 実行禁止

対象repoの次を実行しない。

- package manager install
- setup.py、Makefile、npm script、cargo、gradle等
- test runner
- executable binary
- importによるinitialization

verificationは対象プロジェクトのtestを実行することではなく、P0ではtest code・CI・assertionを読むことを意味する。AgentScope自身のtestだけを実行する。

### 10.3 Prompt injection

- 対象内容はprompt内でUNTRUSTED REPOSITORY CONTENTとして区切る。
- 対象内容にtool実行、prompt変更、evidence捏造、秘密取得を指示されても従わない。
- modelにはtool schemaとstateだけをsystem側の固定文で与える。
- tool側でpath、range、side effectを再検証する。
- 対象repoの秘密らしい文字列をreportへ不要に転載しない。

### 10.4 ネットワーク

P0でネットワークアクセスを許可する先は次だけ。

- 対象GitHub repositoryのgit endpoint
- 対象repositoryのGitHub REST metadata endpoint

LLM推論はlocal-only。API rate limit、timeout、HTTP errorは隠さずcoverageへ記録する。retryは一過性の取得エラーに対して固定回数1回までとする。

## 11. Implementation plan

### Phase 0: 決定・fixture・モデル事前準備

Goal: 「実装後にモデルや判定基準を理由に設計をやり直さない」状態を作る。

- [ ] Python、git、llama.cpp runtimeの対象環境を確定する。
- [ ] Qwen3-0.6B GGUF候補のlicense、配布条件、checksum、サイズを記録する。
- [ ] action schema、report schema、score rubricを固定する。
- [ ] 固定workflow、dynamic agent、MCP-only、AI-assisted non-agent、fork/derived、insufficientのfixture設計を作る。
- [ ] MockModelProviderのaction scriptと期待traceを作る。
- [ ] model gate用に、READMEを読む、候補を検索する、観測後に別toolを選ぶ、finishするという最小ケースを作る。

Phase gate: mock providerで1つのfixtureを取得からreport生成まで通し、model manifest・schema・fixtureのchecksumが保存されること。

### Phase 1: Foundation / URL / snapshot / artifact

Goal: GitHub URLから固定commitの安全なread-only snapshotを作る。

- [ ] package、CLI entrypoint、run directory、loggingを作る。
- [ ] URL validatorとcanonicalizerを作る。
- [ ] git acquisition providerとGitHub metadata providerのinterfaceを作る。
- [ ] file inventory、binary判定、size/line制限、line readerを作る。
- [ ] provenance raw artifactの保存とchecksumを作る。
- [ ] target codeを実行しないallowlistとテストを作る。

Phase gate: fixture snapshotを固定SHAで読み、指定行を再現可能に返し、対象repoのscriptを実行していないことをテストで確認する。

### Phase 2: Deterministic evidence primitives

Goal: LLMなしで、候補検索と証拠化ができる。

- [ ] README、設定、source、test、CI候補のinventoryを作る。
- [ ] LLM/API候補 detectorを作る。
- [ ] MCP/tool registry/dispatcher候補 detectorを作る。
- [ ] planner/loop/state/retry/budget/termination候補 detectorを作る。
- [ ] Python ASTとJS/TSの限定的なcall/data flowを作る。
- [ ] Git log/co-author/remote/author/committerのmaterializerを作る。
- [ ] GitHub fork/parent responseのmaterializerを作る。
- [ ] evidence line/hash validatorを作る。
- [ ] FactGraphとEvidenceLedgerのunit testを作る。

Phase gate: 各fixtureで、positive evidence・negative evidence・coverage不足Unknownが、すべて実在file:line付きで生成されること。

### Phase 3: Agent loop / local model

Goal: AgentScope自身が、固定順序ではなくmodel outputで次のtoolを選ぶ。

- [ ] ToolSpec、ToolResult、Action schemaを作る。
- [ ] MockModelProviderを先にAgentLoopへ接続する。
- [ ] state、hypothesis、unknown、budget、action historyを作る。
- [ ] model promptとUNTRUSTED境界を作る。
- [ ] schema validation、semantic guard、1回限定retryを作る。
- [ ] finish_auditのsufficiency gateを作る。
- [ ] audit_trace.jsonlとstate snapshotを作る。
- [ ] LocalLlamaCppProviderを同じinterfaceへ接続する。
- [ ] fixed fixtureでは固定sequenceを選ばず、dynamic fixtureではobservationに応じてtoolが変わるreal/mock traceを確認する。

Phase gate: 同じtool catalogでもfixtureの観測結果に応じてaction sequenceが変わり、traceにmodel-selected tool、tool result、次のmodel-selected toolが記録されること。modelが無効JSONを返した場合は1回retry後に停止すること。

### Phase 4: Scoring / classification / report

Goal: 7軸scoreと5判定を、証拠付きで決定論的に出す。

- [ ] FactGraphからsubfactorを算出する。
- [ ] 7軸score calculatorを実装する。
- [ ] AI-assisted developmentとruntime Agentic AIを分離する。
- [ ] MCP/tooling、formal fork、derived conceptの判定を実装する。
- [ ] score=null / Unknown / negative 0の表示規則を実装する。
- [ ] Markdown、JSON、trace参照を実装する。
- [ ] report lintをfail-closedで実装する。
- [ ] golden reportをfixtureごとに作る。時刻・一時path・非本質的SHAは正規化する。

Phase gate: fixtureの期待判定が一致し、すべてのtable rowとclassificationが実在file:lineを持ち、AI co-authorだけのfixtureがAgentic runtime=Noになること。

### Phase 5: Hardening / reproducibility

Goal: 悪意のある・巨大な・不完全なrepositoryでも、安全に不明を返せる。

- [ ] prompt injection fixtureを追加する。
- [ ] path traversal、symlink、巨大file、binary、malformed UTF-8のテストを追加する。
- [ ] network timeout、rate limit、partial snapshot、API unavailableのテストを追加する。
- [ ] evidence捏造、line mismatch、unknown ID、score range違反のguard testを追加する。
- [ ] runの再現性を確認する。
- [ ] model、runtime、prompt schema、対象SHAのmanifestをreportへ出す。
- [ ] model weightsをrelease artifactへ同梱する。

Phase gate: failureを成功扱いせず、対象コードを実行せず、取得不能やevidence不足をUnknown/INSUFFICIENT_EVIDENCEとして再現可能に出すこと。

### Phase 6: Demo / release

Goal: URL一つで価値が伝わるP0デモを成立させる。

- [ ] agentscope audit https://github.com/eightman999/autoresearch-naval を実行する。
- [ ] README、LLM/API、tool/MCP、planner/loop/state/retry、model action、Git provenance、fork、co-author、derived concept、testsをtraceで確認する。
- [ ] report.mdの7軸scoreをfile:line付きで表示する。
- [ ] 5種類のYes/No/Unknownを混同なく表示する。
- [ ] AgentScope自身のaudit traceを提示する。
- [ ] model weights、runtime、license、checksumをrelease bundleで確認する。
- [ ] clean environmentで、URL以外の入力なしにrunできることを確認する。
- [ ] 未確認範囲とINSUFFICIENT_EVIDENCEをサンプルとして確認する。

Phase gate: clean environmentで対象URLを1つ渡すだけでreport.md、report.json、audit_trace.jsonlが生成され、全主張に検証済みfile:lineがあること。

## 12. Test strategy

### 12.1 Fixture matrix

| fixture | 目的 | 期待 |
| --- | --- | --- |
| fixed_workflow | LLMは呼ぶが手順は固定 | Agentic runtime=No、dynamic tool selection低 |
| dynamic_agent | model outputがregistryからtoolを選び、観測でreplan | Agentic runtime=Yes、feedback高 |
| mcp_only | MCP serverはあるがmodel control loopなし | MCP/tooling=Yes、Agentic runtime=NoまたはUnknown |
| ai_assisted_non_agent | Co-authored-by: Claude等がある単純workflow | AI-assisted=Yes、Agentic runtime=No |
| fork_derived | fork metadataとKarpathy/autoresearch creditがある | Formal fork=Yes、Derived concept=Yes |
| insufficient | READMEと一部ファイルだけでpathが切れる | 不足をUnknown、終了=INSUFFICIENT_EVIDENCE |
| prompt_injection | READMEが監査agentへ命令する | 命令を実行せず、通常のevidenceのみ |

### 12.2 検証レイヤ

- unit: URL、line reader、schema、evidence hash、score、classification。
- integration: mock model + fixture repository + full report。
- real-model smoke: 内蔵モデルでaction JSON、tool選択、finishを確認。
- security: path、symlink、未trusted content、実行禁止。
- golden: reportの必須項目、score、Unknown、evidence ref。
- self-audit: AgentScope自身を対象に、agent traceが証拠付きで出ること。

### 12.3 Real-model gate

最小モデルを採用する条件:

- action JSON schema遵守が所定ケースで再現する。
- 不正schema時に1回retryで終わる。
- read、search、trace、provenance、finishのtoolから、観測に合ったものを選べる。
- fixed_workflowとdynamic_agentを混同しない。
- evidence ID、path、lineを捏造しない。
- 同一seed・同一snapshotで、許容した揺らぎ以外のreport差分がない。

第一候補がこのgateを通らない場合、原因をprompt/schema/tool outputの設計で先に直す。モデルサイズを大きくする場合は、候補、増加サイズ、改善した失敗ケースを記録し、内蔵local-only方針は維持する。

## 13. Acceptance Criteria

### Functional

- [ ] GitHub公開URL一つでauditが開始する。
- [ ] 対象commit SHAがreportに出る。
- [ ] Agentが少なくとも2種類のtoolを実際に選べる。
- [ ] observation後に異なるtoolを選び直すtraceがあるfixtureを通る。
- [ ] README、LLM/API、tool/MCP、loop/state/retry、model action、provenance、testsの調査結果が出る。
- [ ] 7軸scoreが定義済み順序で出る。
- [ ] 5種類のbinary classificationが別欄で出る。
- [ ] 各scoreと主要判定がfile:line evidenceを持つ。
- [ ] AI-assisted development=YesだけではAgentic runtime=Yesにならない。
- [ ] MCP/tooling=YesだけではAgentic runtime=Yesにならない。
- [ ] fork=falseと「git remoteに別URLがある」を混同しない。
- [ ] derived conceptは明示証拠なしにYesへならない。

### Evidence / correctness

- [ ] 存在しないpath、line、evidence IDをreportへ出さない。
- [ ] evidence excerptとline hashが一致する。
- [ ] unknownをscore 0やNoへ黙って変換しない。
- [ ] score range違反をclampしない。
- [ ] modelが返したscoreをそのまま表示しない。
- [ ] 不足coverage、API失敗、call graph不足がreportへ残る。
- [ ] finish gate未通過でENOUGH_EVIDENCEにならない。

### Security / resource

- [ ] target repositoryのコードを実行しない。
- [ ] URL、path、symlink、size、line、stepの制限を通る。
- [ ] README等のprompt injectionを命令として実行しない。
- [ ] P0のLLM推論が外部APIへ送信されない。
- [ ] retryが固定上限を超えない。

### Packaging / reproducibility

- [ ] model manifestにmodel ID、runtime、license URL、checksumがある。
- [ ] clean environmentでモデルを含むrelease bundleから起動する。
- [ ] run artifactに対象SHA、model SHA、schema version、traceがある。
- [ ] 同一snapshotを再監査できる。

## 14. Definition of Done

次の一連のストーリーを、clean environmentで完走した時点をP0完了とする。

> 利用者がGitHub URLを1つ入力する → AgentScopeが対象commitを固定する → AgentScope内蔵の小型local modelが最初の調査toolを選ぶ → tool結果からunknownとhypothesisを更新する → modelが次のtoolを再選択する → model/APIからaction、tool dispatch、feedback、loop、verification、Git provenance、fork、derived conceptを証拠付きで追跡する → modelがENOUGH_EVIDENCEまたはINSUFFICIENT_EVIDENCEを要求する → controllerがfinish gateを検証する → 7軸scoreと5種類の区別を、すべて検証済みfile:line付きでreport.md/report.jsonへ出力する。

DoDに含めないもの:

- Web UIやネイティブGUIの完成
- private repository対応
- 全プログラミング言語の完全なcall graph
- リモートLLM provider
- scoreの人間による後編集

ただし、DoDに含めない項目を理由にP0 CLIのevidence・security・local model・report要件を省略してはならない。

## 15. Final priority

判断に迷った場合の優先順位:

1. 1つのGitHub URLで価値が伝わるか。
2. 本当にmodelがtool/actionを選んだことをtraceで確認できるか。
3. すべての主張へfile:line evidenceがあるか。
4. AI-assisted、runtime Agentic、MCP/tooling、fork、derived conceptを混同していないか。
5. 不明を不明のまま表示できるか。
6. 小型local modelで再現可能か。
7. UI、最適化、全言語対応の美しさ。

作らないもの: READMEだけをscoreするデモ、contributor名だけでruntimeを判定する分類器、固定sequenceをagentと称するwrapper、証拠なしの0〜10採点器。

## 16. リスクと保留判断

### R1: 小型モデルのaction選択能力

Qwen3-0.6Bを第一候補にするが、実際のaction選択精度は未検証。Phase 0のreal-model gateで測る。失敗を隠すために固定workflowへ戻さない。

### R2: 構文解析のcoverage

P0の対象言語以外でcall graphが切れる可能性がある。静的検索の結果をpositive proofへ格上げせず、Unknownとcoverageを出す。追加言語はP1でtree-sitterを導入する。

### R3: GitHub metadataの可用性

API rate limitや認証状態でfork判定ができない場合がある。git historyとGitHub APIを別証拠として保存し、取得できなかった項目はUnknownとする。

### R4: Originalityの主観性

Originality / 自作度は客観的な著作権判断ではない。score名をevidence-based estimateとし、fork、credit、lineage、独自要素、provenance coverageの根拠を併記する。

### R5: 入力repoの悪意

対象コードを実行せず、toolとpathをallowlistする。prompt injectionはfixture化し、reportへ混入した場合をfailにする。

## 17. 完了後の実装ルール

- 仕様変更はこのファイルを先に改訂し、版を更新する。
- 実装計画・tasks・レビュー文書は本ファイルの節番号を引用する。
- scoreやclassificationの新軸追加は、report schema、fixture、Acceptance Criteriaを同時に変更する。
- 新しいmodel/providerを追加しても、MockModelProviderとLocalLlamaCppProviderのinterfaceを壊さない。
- 外部API、model、GitHub metadataのレスポンスをrawのままdomainへ流さず、validatorとmaterializerを通す。
- 完了報告前にgit status、git diff、test、real-model smoke、P0 demoを実行する。

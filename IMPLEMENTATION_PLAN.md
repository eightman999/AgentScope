# AgentScope 実装計画

- 正典: /Users/eightman/dev/apps/AgentScope/spec.md
- 運用: spec.mdを唯一の正典とし、このファイルは実行順とチェック項目だけを持つ派生計画とする。
- 状態: 未着手
- 対象: P0のみ

## 0. 実装方針

AgentScopeの公開入力はGitHub公開URL一つだけとする（spec.md §1.2、§4.1）。

中心機能は次の順で作る。

~~~text
安全なsnapshot
  -> 決定論的な候補検索とfile:line evidence
  -> mock-first agent loop
  -> 内蔵local model
  -> FactGraph / score / classification
  -> report lint
  -> real-model smoke / self-audit / demo
~~~

固定workflowをLLMで後付け説明する実装は禁止する（spec.md §2、§5.1、§6.6）。

## 1. 実装順

### Phase 0: 事前決定・fixture・model gate

参照: spec.md §6.1、§11 Phase 0、§12.1、§12.3

- [ ] P0のCLIコマンドとrun artifactの配置を確定する。
- [ ] Python、git、llama.cppの最小対応環境を確認する。
- [ ] Qwen3-0.6B GGUF候補のlicense、サイズ、checksum、配布可否を記録する。
- [ ] action-schema、report-schema、Evidence schema、FactGraph schemaを確定する。
- [ ] fixture 6種とprompt injection fixtureの最小ソースを設計する。
- [ ] MockModelProviderのaction scriptと期待traceを作る。
- [ ] real-model gateの合格基準を固定する。

完了条件:

- mockでfixture一つをsnapshotからreportまで流せる設計がある。
- model manifestとschema versionが固定されている。
- 固定workflowとdynamic agentを区別する期待値がfixtureにある。

停止条件:

- model licenseまたはrelease同梱条件が未確認なら、weightsの配布実装へ進まない。
- scoreの意味やUnknown規則が未確定なら、report実装へ進まない。

### Phase 1: Foundation

参照: spec.md §5、§6.1、§6.2、§10、§11 Phase 1

- [ ] pyprojectとagentscope CLI entrypointを作る。
- [ ] GitHub URLのscheme、host、owner、repo、redirectを検証する。
- [ ] GitHub snapshot providerを作り、HEAD SHAを固定する。
- [ ] run専用temp directoryとartifact writerを作る。
- [ ] inventory、binary判定、symlink/submodule/LFS方針、size上限を作る。
- [ ] line readerがrelative path、start/end line、excerpt hashを返すようにする。
- [ ] git command allowlistを作る。対象repositoryのscriptは実行しない。
- [ ] GitHub metadata providerを作り、取得失敗をUnknownへ渡す。

検証:

- URL正常系、URL拒否、redirect拒否、clone失敗、巨大file、binary、symlinkをunit testする。
- fixture snapshotのcommit SHAと指定行が再実行ごとに一致することを確認する。
- subprocess監視でpackage manager、test runner、対象scriptが呼ばれないことを確認する。

Phase gate:

- 固定SHAのread-only snapshotからline-numbered excerptを取得できる。
- provenance artifactにendpoint、status、取得時刻、checksumがある。
- 対象repoコードの実行がない。

### Phase 2: Deterministic evidence primitives

参照: spec.md §3、§7、§8、§11 Phase 2

- [ ] README、設定、source、test、CIの候補inventoryを実装する。
- [ ] LLM/API client、endpoint、model、completion/generate/invoke候補を検出する。
- [ ] MCP、tool schema、registry、decorator、dispatcher、executor候補を検出する。
- [ ] planner、loop、state、retry、budget、termination候補を検出する。
- [ ] Python ASTの関数・呼び出し・代入・分岐・loop抽出を実装する。
- [ ] JavaScript/TypeScriptの限定的なsymbol/call/data-flow抽出を実装する。
- [ ] 他言語はliteral検索とcoverage記録へ限定する。
- [ ] git log、author、committer、Co-authored-by、remoteをmaterializeする。
- [ ] GitHub fork/parent metadataをmaterializeする。
- [ ] inspect_concept_lineage用のknown concept初期データへKarpathy/autoresearchを登録する。
- [ ] EvidenceLedger、Evidence validator、FactGraphを実装する。

検証:

- 直接positive evidenceが実在行を指す。
- fixed_workflowでmodel callは検出されるが、model outputからdispatcherへのedgeが作られない。
- dynamic_agentでmodel output、dispatcher、observation、replanのedgeが作られる。
- AI-assisted non-agentでco-authorは検出されるが、runtime Agentic edgeは作られない。
- API unavailable時にfork=false等のデフォルト値が生成されない。

Phase gate:

- 各fixtureのpositive、negative、coverage不足がEvidence schemaを通る。
- evidenceのexcerpt、line、hash、commit SHAが一致する。
- call graphで追跡不能なedgeを推測せず、Unknownとして返す。

### Phase 3: Agent loop

参照: spec.md §5.1、§5.2、§6.3〜§6.7、§7.3、§10.3、§11 Phase 3

- [ ] ToolSpec、ToolResult、tool registryを実装する。
- [ ] list_repo_tree、read_file、search_codeを接続する。
- [ ] inspect_llm_calls、inspect_tooling、trace_call_graphを接続する。
- [ ] inspect_git_provenance、inspect_github_metadata、inspect_tests、inspect_concept_lineageを接続する。
- [ ] finish_auditとENOUGH_EVIDENCE / INSUFFICIENT_EVIDENCEを接続する。
- [ ] Agent state、hypothesis、unknown、visited file、observation、action history、budgetを実装する。
- [ ] system promptへUNTRUSTED REPOSITORY CONTENT境界を入れる。
- [ ] action JSONをstrict validatorへ通す。
- [ ] path、range、tool、budget、evidence IDのsemantic guardを作る。
- [ ] schema error時のエラー付き1回retryを作る。
- [ ] 無効出力後に固定sequenceへfallbackしない。
- [ ] audit_trace.jsonlとcurrent state snapshotを保存する。

検証:

- MockModelProviderでREADME始動、search始動、provenance始動など複数sequenceを通す。
- observationの内容を変えると、次のmodel-selected toolが変わるfixtureを通す。
- unknown evidence ID、存在しないpath、line mismatch、range違反、未知toolを拒否する。
- ENOUGH_EVIDENCEの不足項目をcontrollerが拒否し、budget内なら再探索する。
- budget枯渇時にINSUFFICIENT_EVIDENCEになる。
- prompt injection fixtureの命令を実行しない。

Phase gate:

- traceにmodel action、実行tool、tool observation、次のmodel actionが並ぶ。
- 固定sequenceを実装していないことをテストで確認する。
- 1回retryの後に停止し、無限retryしない。

### Phase 4: score・classification・report

参照: spec.md §8、§9、§13、§11 Phase 4

- [ ] FactGraphからsubfactorを算出する。
- [ ] 7軸のscore calculatorを実装する。
- [ ] score 0とUnknownを分ける。
- [ ] AI-assisted developmentとAgentic runtimeを別々に判定する。
- [ ] MCP/tooling、Formal GitHub fork、Derived conceptを別々に判定する。
- [ ] Markdownの7軸score表と5判定欄を実装する。
- [ ] JSON schemaとreport.jsonを実装する。
- [ ] evidence一覧、unknowns、coverage、trace参照を実装する。
- [ ] report lintをfail-closedで実装する。
- [ ] fixtureごとのgolden reportを作る。

検証:

- scoreの上下限、null、state、confidenceを検査する。
- modelが返したscoreを使わず、domain calculatorの値だけがreportへ入ることを確認する。
- 各score/classificationに少なくとも一つの検証済みfile:lineがあることを確認する。
- AI co-authorだけのfixtureがAgentic runtime=Noになる。
- MCP-only fixtureがMCP/tooling=YesでもAgentic runtime=NoまたはUnknownになる。
- fork API unavailableがFormal GitHub fork=Unknownになる。
- Karpathy/autoresearchの明示creditがDerived concept=Yesになる。

Phase gate:

- fixtureの期待classificationとgolden reportが一致する。
- evidence参照がすべて解決する。
- 未検証主張、未解決ID、内部markerがreportへ出ない。

### Phase 5: hardening・reproducibility

参照: spec.md §2、§7.3、§9.3、§10、§11 Phase 5

- [ ] path traversal、absolute path、symlink escapeを拒否する。
- [ ] malformed UTF-8、巨大行、巨大output、巨大repositoryを制限する。
- [ ] GitHub timeout、rate limit、partial clone、API errorを検証する。
- [ ] model出力の捏造path、捏造evidence ID、range違反を評価全体Unknownにする。
- [ ] scoreのclampが存在しないことを静的検査する。
- [ ] prompt injection、秘密文字列、悪意あるREADMEを検証する。
- [ ] run manifestへ対象SHA、model SHA、runtime version、schema version、prompt versionを保存する。
- [ ] 同じsnapshotとseedで再監査し、許容差分を定義する。
- [ ] model weightsとllama.cpp runtimeをrelease bundleへ同梱する。

検証:

- 対象repoのコード・テスト・ビルドが実行されない。
- APIやcloneの一時障害がNoへ化けない。
- 同一入力のartifact差分が時刻などの許容項目以外で一致する。

Phase gate:

- 安全性、Unknown伝播、再現性、配布条件がすべて合格する。

### Phase 6: P0 demo・release

参照: spec.md §4.1、§11 Phase 6、§13、§14

- [ ] clean environmentを用意する。
- [ ] URL以外の入力なしでローカルモデルが起動することを確認する。
- [ ] https://github.com/eightman999/autoresearch-naval を監査する。
- [ ] traceでREADME、LLM/API、tool/MCP、planner/loop/state/retry、model action、Git provenance、fork、co-author、derived concept、testsの調査を確認する。
- [ ] report.md、report.json、audit_trace.jsonlの存在と内容を確認する。
- [ ] 全score/classificationにfile:lineがあることを確認する。
- [ ] AgentScope自身のrepositoryを監査する。
- [ ] P0以外の機能を実装へ混入させていないことをgit diffで確認する。

Phase gate:

- URL一つでP0のDoDを完走する。
- 失敗・不足証拠の場合も、INSUFFICIENT_EVIDENCEと制限が出る。
- 内蔵モデル、runtime、license、checksumがrelease artifactで確認できる。

## 2. 予定ファイル

実装開始時に、次の範囲だけを作る（spec.md §6.2）。

~~~text
pyproject.toml
src/agentscope/cli.py
src/agentscope/application.py
src/agentscope/domain/*
src/agentscope/acquisition/*
src/agentscope/analysis/*
src/agentscope/agent/*
src/agentscope/model/*
src/agentscope/report/*
resources/model-manifest.json
resources/action-schema.json
resources/report-schema.json
tests/fixtures/*
tests/unit/*
tests/integration/*
tests/golden/*
~~~

P1/P2のUI、remote provider、全言語parser、multi-agentは作成しない（spec.md §4.2、§4.3）。

## 3. 完了判定

この計画を完了とするには、spec.md §13のAcceptance Criteriaと§14のDefinition of Doneをすべて確認する。

必須の最終確認:

- git status --short --branch
- git diff --stat
- unit / integration / security test
- real-model smoke
- report lint
- clean environmentでのP0 demo
- 実際に生成されたreport.md、report.json、audit_trace.jsonlの存在と内容

未検証項目が残る場合は完了にせず、最終報告で明示する。

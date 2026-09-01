# AgentScope 実装計画

- 正典: /Users/eightman/dev/apps/AgentScope/spec.md
- 運用: spec.mdを唯一の正典とし、このファイルは実行順とチェック項目だけを持つ派生計画とする。
- 状態: P0主要実装・P1先行精度改善・release bundle / clean environment 検証済み（redirect実地検証、subprocess監視、捏造model outputのUnknown変換は未完了）
- 対象: P0 + P1先行のcontrol-flow精度改善
- 最終確認: 2026-09-01。29テスト、adversarial negative fixture、target実モデルsmoke、self-audit、同一snapshot再現性、package build、bundle hash/署名、clean environment demoを実測。

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

- [x] P0のCLIコマンドとrun artifactの配置を確定する。
- [x] Python、git、llama.cppの最小対応環境を確認する。
- [x] Qwen3-0.6B GGUF候補のlicense、サイズ、checksum、配布可否を記録する。
- [x] action-schema、report-schema、Evidence schema、FactGraph schemaを確定する。
- [x] fixture 6種とprompt injection fixtureの最小ソースを設計する。
- [x] MockModelProviderのaction scriptと期待traceを作る。
- [x] real-model gateの合格基準を固定する。

完了条件:

- mockでfixture一つをsnapshotからreportまで流せる設計がある。
- model manifestとschema versionが固定されている。
- 固定workflowとdynamic agentを区別する期待値がfixtureにある。

停止条件:

- model licenseまたはrelease同梱条件が未確認なら、weightsの配布実装へ進まない。
- scoreの意味やUnknown規則が未確定なら、report実装へ進まない。

### Phase 1: Foundation

参照: spec.md §5、§6.1、§6.2、§10、§11 Phase 1

- [x] pyprojectとagentscope CLI entrypointを作る。
- [x] GitHub URLのscheme、host、owner、repoを検証する。
- [ ] git cloneのredirect先hostを拒否する。
- [x] GitHub snapshot providerを作り、HEAD SHAを固定する。
- [x] run専用temp directoryとartifact writerを作る。
- [x] inventory、binary判定、symlink/submodule/LFS方針、size上限を作る。
- [x] line readerがrelative path、start/end line、excerpt hashを返すようにする。
- [x] git command allowlistを作る。対象repositoryのscriptは実行しない。
- [x] GitHub metadata providerを作り、取得失敗をUnknownへ渡す。

検証:

- [ ] URL正常系、URL拒否、redirect拒否、clone失敗、巨大file、binary、symlinkをunit testする（redirect拒否の実地確認は未完了）。
- [x] fixture snapshotのcommit SHAと指定行が再実行ごとに一致することを確認する。
- [ ] subprocess監視でpackage manager、test runner、対象scriptが呼ばれないことを確認する（静的実行禁止とallowlistは確認済み）。

Phase gate:

- 固定SHAのread-only snapshotからline-numbered excerptを取得できる。
- provenance artifactにendpoint、status、取得時刻、checksumがある。
- 対象repoコードの実行がない。

### Phase 2: Deterministic evidence primitives

参照: spec.md §3、§7、§8、§11 Phase 2

- [x] README、設定、source、test、CIの候補inventoryを実装する。
- [x] LLM/API client、endpoint、model、completion/generate/invoke候補を検出する。
- [x] MCP、tool schema、registry、decorator、dispatcher、executor候補を検出する。
- [x] planner、loop、state、retry、budget、termination候補を検出する。
- [x] Python ASTの関数・呼び出し・代入・分岐・loop抽出を実装する。
- [x] JavaScript/TypeScriptの限定的なsymbol/call/data-flow抽出を実装する。
- [x] 他言語はliteral検索とcoverage記録へ限定する。
- [x] git log、author、committer、Co-authored-by、remoteをmaterializeする。
- [x] GitHub fork/parent metadataをmaterializeする。
- [x] inspect_concept_lineage用のknown concept初期データへKarpathy/autoresearchを登録する。
- [x] EvidenceLedger、Evidence validator、FactGraphを実装する。

検証:

- [x] 直接positive evidenceが実在行を指す。
- [x] fixed_workflowでmodel callは検出されるが、model outputからdispatcherへのedgeが作られない。
- [x] dynamic_agentでmodel output、dispatcher、observation、replanのedgeが作られる。
- [x] AI-assisted non-agentでco-authorは検出されるが、runtime Agentic edgeは作られない。
- [x] API unavailable時にfork=false等のデフォルト値が生成されない。

Phase gate:

- 各fixtureのpositive、negative、coverage不足がEvidence schemaを通る。
- evidenceのexcerpt、line、hash、commit SHAが一致する。
- call graphで追跡不能なedgeを推測せず、Unknownとして返す。

### Phase 3: Agent loop

参照: spec.md §5.1、§5.2、§6.3〜§6.7、§7.3、§10.3、§11 Phase 3

- [x] ToolSpec、ToolResult、tool registryを実装する。
- [x] list_repo_tree、read_file、search_codeを接続する。
- [x] inspect_llm_calls、inspect_tooling、trace_call_graphを接続する。
- [x] inspect_git_provenance、inspect_github_metadata、inspect_tests、inspect_concept_lineageを接続する。
- [x] finish_auditとENOUGH_EVIDENCE / INSUFFICIENT_EVIDENCEを接続する。
- [x] Agent state、hypothesis、unknown、visited file、observation、action history、budgetを実装する。
- [x] system promptへUNTRUSTED REPOSITORY CONTENT境界を入れる。
- [x] action JSONをstrict validatorへ通す。
- [x] path、range、tool、budget、evidence IDのsemantic guardを作る。
- [x] schema error時のエラー付き1回retryを作る。
- [x] 無効出力後に固定sequenceへfallbackしない。
- [x] audit_trace.jsonlとcurrent state snapshotを保存する。

検証:

- [x] MockModelProviderでREADME始動、search始動、provenance始動など複数sequenceを通す。
- [x] observationの内容を変えると、次のmodel-selected toolが変わるfixtureを通す。
- [x] unknown evidence ID、存在しないpath、line mismatch、range違反、未知toolを拒否する。
- [x] ENOUGH_EVIDENCEの不足項目をcontrollerが拒否し、budget内なら再探索する。
- [x] budget枯渇時にINSUFFICIENT_EVIDENCEになる。
- [x] prompt injection fixtureの命令を実行しない。

Phase gate:

- traceにmodel action、実行tool、tool observation、次のmodel actionが並ぶ。
- 固定sequenceを実装していないことをテストで確認する。
- 1回retryの後に停止し、無限retryしない。

### Phase 4: score・classification・report

参照: spec.md §8、§9、§13、§11 Phase 4

- [x] FactGraphからsubfactorを算出する。
- [x] 7軸のscore calculatorを実装する。
- [x] score 0とUnknownを分ける。
- [x] AI-assisted developmentとAgentic runtimeを別々に判定する。
- [x] MCP/tooling、Formal GitHub fork、Derived conceptを別々に判定する。
- [x] Markdownの7軸score表と5判定欄を実装する。
- [x] JSON schemaとreport.jsonを実装する。
- [x] evidence一覧、unknowns、coverage、trace参照を実装する。
- [x] report lintをfail-closedで実装する。
- [x] fixtureごとのgolden reportを作る。

検証:

- [x] scoreの上下限、null、state、confidenceを検査する。
- [x] modelが返したscoreを使わず、domain calculatorの値だけがreportへ入ることを確認する。
- [x] 各score/classificationに少なくとも一つの検証済みfile:lineがあることを確認する。
- [x] AI co-authorだけのfixtureがAgentic runtime=Noになる。
- [x] MCP-only fixtureがMCP/tooling=YesでもAgentic runtime=NoまたはUnknownになる。
- [x] fork API unavailableがFormal GitHub fork=Unknownになる。
- [x] Karpathy/autoresearchの明示creditがDerived concept=Yesになる。

Phase gate:

- fixtureの期待classificationとgolden reportが一致する。
- evidence参照がすべて解決する。
- 未検証主張、未解決ID、内部markerがreportへ出ない。

### Phase 5: hardening・reproducibility

参照: spec.md §2、§7.3、§9.3、§10、§11 Phase 5

- [x] path traversal、absolute path、symlink escapeを拒否する。
- [x] malformed UTF-8、巨大行、巨大output、巨大repositoryを制限する。
- [x] GitHub timeout、rate limit、partial clone、API errorを検証する。
- [ ] model出力の捏造path、捏造evidence ID、range違反を評価全体Unknownにする（lintでfail-closedは確認済み、Unknown変換は未完了）。
- [x] scoreのclampが存在しないことを静的検査する。
- [x] prompt injection、秘密文字列、悪意あるREADMEを検証する。
- [x] run manifestへ対象SHA、model SHA、runtime version、schema version、prompt versionを保存する。
- [x] 同じsnapshotとseedで再監査し、許容差分を定義する。
- [x] model weightsとllama.cpp runtimeをrelease bundleへ同梱する（`scripts/build_release_bundle.py`でmacOS arm64 bundleを生成し、manifest hash・署名・runtime起動を確認）。

検証:

- [x] 対象repoのコード・テスト・ビルドが実行されない。
- [x] APIやcloneの一時障害がNoへ化けない。
- [x] 同一入力のartifact差分が時刻などの許容項目以外で一致する。

Phase gate:

- 安全性、Unknown伝播、再現性、配布条件がすべて合格する。

### P1先行: control-flow adversarial precision

ユーザー指摘の「単語共起だけでedgeが立つ」false positiveを、P1の他機能より先に固定する。

- [x] モデル返り値を捨てて固定actionをdispatchするnegative fixtureを追加する。
- [x] Agent語彙をコメント/docstringだけに置いたnegative fixtureを追加する。
- [x] Python control-flowをASTとmodel-derived valueの簡易data-flowで追跡し、実際につながる場合だけ`controls`、`dispatches`、`observes`、`replans`を生成する。
- [x] 非Pythonのlexical fallbackでコメント・文字列を除外し、追跡不能なruntime edgeを推測しない。

検証:

- [x] `fixed_model_output_discarded`が`model_call`だけを残し、runtime edgeを生成しない。
- [x] `comment_keywords_only`がmodel nodeとruntime edgeを生成しない。
- [x] `dynamic_agent`の4種のpositive edgeと29件のテストを維持する。

Phase gate:

- [x] adversarial negative fixtureがfull auditでも`Agentic runtime=No`、`Agenticity=2.0`になる。

### Phase 6: P0 demo・release

参照: spec.md §4.1、§11 Phase 6、§13、§14

- [x] clean environmentを用意する（新規Python 3.14 venvへbundle wheelを`--no-deps` install）。
- [x] URL以外の入力なしでローカルモデルが起動することを確認する（bundle内runtimeと`run.sh`で確認）。
- [x] https://github.com/eightman999/autoresearch-naval を監査する。
- [x] traceでREADME、LLM/API、tool/MCP、planner/loop/state/retry、model action、Git provenance、fork、co-author、derived concept、testsの調査を確認する。
- [x] report.md、report.json、audit_trace.jsonlの存在と内容を確認する。
- [x] 全score/classificationにfile:lineがあることを確認する。
- [x] AgentScope自身のrepositoryを監査する。
- [x] P0以外の機能を実装へ混入させていないことをgit diffで確認する。

Phase gate:

- [x] URL一つでP0のDoDを完走する（clean environmentのbundle target demo）。
- [x] 失敗・不足証拠の場合も、INSUFFICIENT_EVIDENCEと制限が出る。
- [x] 内蔵モデル、runtime、license、checksumがrelease artifactで確認できる。

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
LICENSE
MANIFEST.in
scripts/build_release_bundle.py
resources/model-manifest.json
resources/action-schema.json
resources/report-schema.json
tests/fixtures/*
tests/unit/*
tests/integration/*
tests/golden/*
tests/test_adversarial_precision.py
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

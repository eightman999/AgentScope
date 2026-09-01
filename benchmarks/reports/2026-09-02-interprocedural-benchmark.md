# AgentScope 実在repository benchmark報告

## 結論

interprocedural解析、runtime優先探索、非runtime/tooling evidence除外を入れた最終v5を、固定SHA snapshot 30件へ再実行した。Agentic runtimeは **precision 100.0%、recall 66.7%、false positive 0件** となった。初回baselineのrecall 0.0%からは改善したが、smolagentsとOpenHandsはモデル出力integrity gateによる棄権となり、recallはまだ保守的である。

MCP/toolingは、v2で残っていた4件の誤陽性を、README・notebook・template・汎用`dispatcher`文字列の除外で0件にした。最終値は **precision 100.0%、recall 73.7%、false positive 0件** である。

この数値は現時点では正式なgold評価ではない。30件すべてが1名による`draft` annotationで、2名独立注釈とadjudicationをまだ行っていないため、探索的な校正結果として扱う。

## 評価条件

| 項目 | 内容 |
| --- | --- |
| dataset | `benchmarks/dataset.jsonl`、30 repository、5カテゴリ×6件 |
| dataset SHA-256 | `e3008b9f45123e9aa45a078ae6ae8123f7bbcd7fd59a27b4c06be190c60b7c63` |
| 固定条件 | 各caseの40桁SHAとsnapshotの`git rev-parse HEAD`を照合 |
| model | `Qwen/Qwen3-0.6B-GGUF` / GGUF Q8_0 |
| model SHA-256 | `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` |
| engine | llama.cpp `0.3.0`、build `10621`、commit `c1d0e7a00` |
| agent budget | 最大14 steps、temperature 0、seed 42 |
| audit実装revision | `9945a51` |
| annotation/report revision | `331b95a` |
| 実行結果 | 29 completed、0 failed、1 `stale_commit` |

実行には正式CLIの固定snapshot再生モードを使った。

```sh
PYTHONPATH=src python3 -m agentscope.cli benchmark run benchmarks/dataset.jsonl \
  --snapshot-base /Users/eightman/dev/data/AgentScope/benchmark-runs/2026-09-02-qwen3-0.6b/artifacts \
  --output /Users/eightman/dev/data/AgentScope/benchmark-runs/2026-09-02-qwen3-0.6b-interprocedural-local-v5 \
  --max-steps 14 --no-resume

PYTHONPATH=src python3 -m agentscope.cli benchmark score benchmarks/dataset.jsonl \
  --results /Users/eightman/dev/data/AgentScope/benchmark-runs/2026-09-02-qwen3-0.6b-interprocedural-local-v5/results.jsonl \
  --output /Users/eightman/dev/data/AgentScope/benchmark-runs/2026-09-02-qwen3-0.6b-interprocedural-local-v5
```

Haystackだけは期待SHA `64d7a1ff030080a82bfe44d3eab3b962d924073e` に対してsnapshot HEADが `5495215d3b55baba44fed4e8aa1cbd5cd0ef670f` だったため、監査せずstaleとして除外した。

## Agentic runtimeの改善

| 実行 | n | TP | FP | TN | FN | precision | recall | FPR | FNR | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 初回baseline | 24 | 0 | 0 | 17 | 5 | — | 0.0% | 0.0% | 100.0% | 91.7% |
| interprocedural v5 | 24 | 4 | 0 | 15 | 0 | 100.0% | 66.7% | 0.0% | 33.3% | 79.2% |

初回baselineでは、AutoGen、LangGraph、CrewAI、smolagents、Pydantic AIのagentic runtime positive pathを復元できなかった。v5では4件をpositiveとして復元し、smolagentsとOpenHandsは無理な推定をせずUnknownへ棄権した。

最終confusion matrixは次の通りである。`ambiguous`は二値率から除外している。

| gold \\ prediction | yes | no | unknown | missing |
| --- | ---: | ---: | ---: | ---: |
| yes | 4 | 0 | 2 | 0 |
| no | 0 | 15 | 3 | 0 |
| ambiguous | 0 | 3 | 2 | 1 |

positive abstentionの根拠は次の通りである。

| case | 人手根拠 | AgentScope根拠 |
| --- | --- | --- |
| `huggingface/smolagents` | `README.md:34` | `provenance/model-output-integrity.txt:1` |
| `OpenHands` | `README.md:7` | `provenance/model-output-integrity.txt:1` |

30件の固定SHA source evidenceは [`annotation-evidence.md`](../annotation-evidence.md) にmaterializeしている。たとえばAutoGenのruntime/tooling根拠は `README.md:16` / `README.md:67`、LangGraphは `README.md:12` / `README.md:42` である。

## 5分類

| axis | n | precision | recall | FP | FN | coverage | abstention |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AI-assisted development | 12 | 100.0% | 58.3% | 0 | 0 | 58.3% | 41.7% |
| Agentic runtime | 24 | 100.0% | 66.7% | 0 | 0 | 79.2% | 20.8% |
| MCP/tooling | 29 | 100.0% | 73.7% | 0 | 0 | 62.1% | 37.9% |
| Formal GitHub fork | 29 | — | — | 0 | 0 | 24.1% | 75.9% |
| Derived concept | 29 | 100.0% | 100.0% | 0 | 0 | 24.1% | 75.9% |

Formal GitHub forkはpositive human labelが存在しないためprecision/recallは定義されない。Derived conceptのpositiveは`karpathy-autoresearch`の1件だけで、既知markerのない一般的な「derived」表現をpositiveにしていない。

## 7軸score

人手scoreは29件に7軸すべてを付け、各値に固定SHAのscore evidenceを付けた。ただし1名draftなので、下表のMAE/RMSEは正式性能ではなく探索的な校正値である。

| axis | n | MAE | RMSE | mean signed error |
| --- | ---: | ---: | ---: | ---: |
| Originality / 自作度 | 7 | 0.786 | 0.906 | -0.786 |
| Agenticity | 19 | 1.421 | 2.146 | +0.421 |
| Dynamic tool selection | 18 | 2.028 | 2.685 | +0.694 |
| Feedback adaptation | 9 | 0.222 | 0.408 | +0.222 |
| Goal-directed loop | 18 | 2.361 | 3.212 | +1.583 |
| Verification | 23 | 1.565 | 2.038 | +0.261 |
| Agent tooling | 18 | 2.611 | 3.037 | -2.278 |

## 実装した改善

- `src/agentscope/analysis/interprocedural.py:156-291` でPython関数index、module/import解決、runtime優先順位を構築し、`src/agentscope/analysis/interprocedural.py:434-970` でmodel-derived valueを関数境界越しに追跡する。
- `src/agentscope/analysis/interprocedural.py:1085-1262` でgraph/executor/node登録のframework contractを一般化し、`controls → dispatches → observes → replans` の順序付きpathを作る。
- `src/agentscope/analysis/control_flow.py:699-791` で従来の局所判定とinterprocedural traceを接続し、`src/agentscope/analysis/inventory.py:103` でruntime本体をtests/examplesより先に予算へ入れる。
- `src/agentscope/analysis/path_priority.py:62-100` と `src/agentscope/analysis/detectors.py:72-102` でREADME、notebook、docs、template、comment-only、汎用output文字列をtooling evidenceから除外する。
- `src/agentscope/application.py:359-410`、`src/agentscope/benchmark/runner.py:115-164`、`src/agentscope/benchmark/runner.py:197-282` で固定snapshot再生とHEAD照合を正式CLIへ追加した。
- `src/agentscope/benchmark/schema.py:267-317`、`benchmarks/annotation-rubric.md`、`benchmarks/annotation-evidence.md` で、5分類と7軸scoreを固定SHAの`file:line`証拠付きで記録する契約を追加した。

throughstoneで観測された中間FPは、`doctor.sh:47` の`echo "dispatcher is missing"`を実行時dispatcherと誤認したものだった。最終v5ではこの根拠を除外し、MCP/tooling FP=0を全30case再実行で確認した。

## 検証結果

実測した検証結果は以下の通り。

- `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` → **63 tests、OK**
- `PYTHONPATH=src python3 -m agentscope.cli benchmark validate benchmarks/dataset.jsonl` → **30 cases、各カテゴリ6、labeled_case_n=30**
- `PYTHONPATH=src python3 -m compileall -q src tests` → **成功**
- `git diff --check` → **成功**
- v5 runner → **selected=30、completed=29、failed_n=1（stale_commitのみ）**
- 同一v5 resultsへの`benchmark score`再実行 → JSON/Markdown hashが一致
  - JSON: `87aeff0bad962501e9d1a1740c37005a5d046eb38d2fb02d31a4f03bf9f5abc4`
  - Markdown: `9abdadd0bbcc2bd103c69f86831185715de6b77829470d76f2238c0225c1c07f`

## 未解決事項

1. 現在のannotationは全30件`draft`である。公開性能値にするには、`annotation-rubric.md`に従う2名独立注釈、agreement、adjudicationが必要。
2. 小型Qwenではsmolagents/OpenHandsのaction出力integrityに失敗し、positive recallを落としている。大きいモデルへ黙って置き換えず、モデル条件を固定した別benchmarkとして比較するべきである。
3. 取得範囲はbounded scanであり、Python以外の実装や動的import、外部backendへ委譲するframeworkではUnknownが増える。これをNoへ変換しない現行方針は維持する。
4. 7軸scoreは人手アンカーの定義を固定した段階で、annotator間一致度の測定は未実施である。

詳細な生成物は外部artifact runの
`/Users/eightman/dev/data/AgentScope/benchmark-runs/2026-09-02-qwen3-0.6b-interprocedural-local-v5/benchmark-report.md`
と同ディレクトリの`benchmark-report.json`、`results.jsonl`に保存した。

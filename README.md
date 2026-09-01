# AgentScope

GitHub公開リポジトリを、実行時のAgentic AIかどうかという観点から証拠付きで監査するローカルCLIです。
AI-assisted development、Agentic runtime、MCP/tooling、Formal GitHub fork、Derived conceptを分離し、7軸のscoreと`file:line`証拠を出力します。

## 使い方

入力は公開GitHub URLだけです。

```sh
agentscope audit https://github.com/eightman999/autoresearch-naval
```

監査対象のコードは実行しません。浅いread-only snapshot、許可済みGit参照、公開GitHub metadata、内蔵local modelを使います。Python runtimeはlocal/import call graphと限定的なdata-flowを跨いで追跡し、graph builderやtool executorの明示配線もruntime pathとして検査します。

出力先は`~/Library/Application Support/AgentScope/runs/`です。各runに次を保存します。

- `report.md`: 日本語のscore・分類・根拠一覧
- `report.json`: 正規化された機械可読結果
- `audit_trace.jsonl`: modelが選択したaction、tool結果、終了判断
- `provenance/`: GitHub metadataとGit provenanceのmaterialized evidence

## 開発

依存パッケージなしのPython実装です。

```sh
PYTHONPATH=src python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 監査精度ベンチマーク

実在リポジトリ30件を、`clearly_agentic`、`llm_non_agent`、`mcp_tooling_only`、`ai_assisted_only`、`hard_case` の5層（各6件）に分けた初期データセットを [`benchmarks/dataset.jsonl`](benchmarks/dataset.jsonl) に置いています。各行は固定SHAと人手ドラフトラベル、READMEの`file:line`根拠を持ちます。AgentScopeのP0デモ対象は自己評価へのリークを避けるため評価セットから除外しています。

```sh
PYTHONPATH=src python3 -m agentscope.cli benchmark validate benchmarks/dataset.jsonl
PYTHONPATH=src python3 -m agentscope.cli benchmark run benchmarks/dataset.jsonl \
  --output benchmarks/runs/pilot --limit 3
PYTHONPATH=src python3 -m agentscope.cli benchmark score benchmarks/dataset.jsonl \
  --results benchmarks/runs/pilot/results.jsonl
```

`benchmark run` はcaseごとにreportを保存し、完了済みcaseを再実行せず再開できます。clone後のSHAがデータセットと異なる場合は`stale_commit`として評価から外します。`benchmark score` は監査を再実行せず、precision、recall、false positive、false negative、coverage、Unknown棄権率、カテゴリ別混同行列、7軸scoreのMAEを決定論的に集計します。初期ラベルは`draft`であり、公開評価値として固定する前に2名以上の独立注釈とadjudicationが必要です。

P0のlocal modelはQwen3-0.6B GGUFとllama.cppを使います。model weightはGitの通常差分へ含めず、`resources/model-manifest.json`のURL・サイズ・SHA-256で検証します。配布時はrelease bundleが必要です。

## Release bundle

macOS arm64向けbundleは、wheel、Qwen GGUF、llama.cpp実行ファイルと必要なdylib、manifest、LICENSEをchecksum付きで生成します。model weightはGitへ追加されません。

```sh
build_dir="$(mktemp -d)"
uv build --out-dir "$build_dir" --no-sources
python3 scripts/build_release_bundle.py \
  --output "./agentscope-0.1.0-macos-arm64" \
  --wheel "$build_dir/agentscope-0.1.0-py3-none-any.whl"
```

生成後はbundle内のwheelをcleanなPython環境へinstallし、`run.sh audit <GitHub URL>`を実行します。

仕様の正典は[`spec.md`](spec.md)、実行順は[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)です。

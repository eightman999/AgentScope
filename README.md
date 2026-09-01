# AgentScope

GitHub公開リポジトリを、実行時のAgentic AIかどうかという観点から証拠付きで監査するローカルCLIです。
AI-assisted development、Agentic runtime、MCP/tooling、Formal GitHub fork、Derived conceptを分離し、7軸のscoreと`file:line`証拠を出力します。

## 使い方

入力は公開GitHub URLだけです。

```sh
agentscope audit https://github.com/eightman999/autoresearch-naval
```

監査対象のコードは実行しません。浅いread-only snapshot、許可済みGit参照、公開GitHub metadata、内蔵local modelを使います。

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

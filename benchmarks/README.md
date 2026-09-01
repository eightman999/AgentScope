# AgentScope benchmark

このディレクトリは、AgentScopeの監査手法を固定commit上の実在GitHubリポジトリで評価するためのデータ契約と実行成果物を置く。

## ラベルの原則

- `category` は層別抽出用であり、正解ラベルそのものではない。
- `human_labels` が人手のgold labelで、各軸の値と根拠を独立に持つ。
- 人手根拠は必ず固定commitの `file:line` と引用を持つ。GitHub API/Git履歴の根拠も、materializeしたファイルと行番号で記録する。
- `agentic_runtime` は、モデル出力がaction選択へ接続し、tool/environmentの観測後に後続計画へ影響するかを判定する。
- `unknown` は `no` ではない。集計では棄権として、coverage・abstention rateを別に出す。
- `ambiguous` は人手でも境界事例と合意できなかった値で、二値precision/recallから除外する。
- `human_scores` を注釈する場合は、`annotation.score_evidence` に各score軸の固定SHA上の`file:line`根拠を付ける。定義とアンカーは [`annotation-rubric.md`](annotation-rubric.md) に固定する。

## JSONL契約

各行は [`dataset.schema.json`](dataset.schema.json) と `src/agentscope/benchmark/schema.py` で検証する。データセットはURLではなく40桁SHAを保存し、実行器はclone後のHEADがSHAと一致しない場合に `stale_commit` として失敗させる。

## 実行

ソースcheckoutでは `PYTHONPATH=src` を付ける。

```sh
python3 -m agentscope.cli benchmark validate benchmarks/dataset.jsonl
python3 -m agentscope.cli benchmark run benchmarks/dataset.jsonl --output benchmarks/runs/pilot
python3 -m agentscope.cli benchmark score benchmarks/dataset.jsonl \
  --results benchmarks/runs/pilot/results.jsonl \
  --output benchmarks/runs/pilot
```

再実行時は既処理caseを読み飛ばす。`--limit` / `--ids` でスモーク評価を先に回せる。生成物にはdataset digest、モデル識別子、実測commit、各reportへの相対pathを保存する。

同じcheckoutを使って再現する場合は、caseごとに
`<snapshot-base>/<case-id>-<commit-shaの先頭12桁>/snapshot` を配置し、次のように実行する。

```sh
python3 -m agentscope.cli benchmark run benchmarks/dataset.jsonl \
  --snapshot-base /path/to/fixed-snapshots \
  --output benchmarks/runs/replay
```

runnerは各snapshotの`git rev-parse HEAD`をdatasetのSHAと照合し、不一致を監査せず`stale_commit`として記録する。

## 公開前のラベル手順

1. calibration setで定義とannotation formを固定する。
2. evaluation setはSHAを凍結してから、最低2名が独立にラベルする。
3. 不一致はadjudicatorが根拠を追加して解決し、`annotation_status=adjudicated` にする。
4. prompt・threshold・静的解析をevaluation setの結果に合わせて変更した場合、dataset/protocol versionを上げ、同じ結果を無記録で上書きしない。

初期データセットは研究用の完成goldではなく、`draft` と `pending` を含む。公開レポートでは、adjudicated行数と未注釈行数を必ず併記する。1名によるdraftの5分類・7軸scoreは探索的校正値であり、precision/recallやMAEを正式な手法性能として主張しない。

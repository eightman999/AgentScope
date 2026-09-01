# Benchmark annotation rubric

この文書は、`benchmarks/dataset.jsonl` の draft annotation を再現可能にするための注釈プロトコルである。現在の30件は1名による初回注釈であり、`adjudicated` なgoldではない。公開評価値として扱うには、最低2名の独立注釈とadjudicationを行い、データセットのprotocol versionを更新する。

## 固定条件

- 対象コードは各行の `commit_sha` に固定する。現在のHEADやGitHubの表示内容で過去の判定を上書きしない。
- ソース根拠は必ず `file:line` と短い引用を持たせる。Git履歴・GitHub APIの値は、取得結果をmaterializeした `provenance/*` の行を根拠にする。
- READMEの自己説明はスコープの補助根拠に使えるが、runtime AgenticのYesはコード上の実行経路で裏付ける。
- `unknown` は証拠不足、`ambiguous` は固定SHAを見てもrepo全体の単一ラベルへ安全に縮約できない場合に使う。どちらも `no` へ変換しない。
- `human_scores` はAgentScopeの出力を転記せず、先に固定SHAのソースを読み、根拠を記録してから注釈する。

## 5分類

| 軸 | `yes` | `no` | `unknown` / `ambiguous` |
| --- | --- | --- | --- |
| `ai_assisted_development` | commit trailer、session marker、README等にClaude/Codex/Copilot/Cursor等の明示的な開発利用がある | AI利用がないことを対象範囲の一次資料が明示している場合だけ | 履歴に明示信号がないだけなら `unknown`。名前やbotだけではYesにしない |
| `agentic_runtime` | モデル出力→action/tool選択→dispatch→観測→後続制御の同一runtime経路がある | モデル呼び出しはあっても固定workflow、SDK、tool server、外部agent向け設定だけ | package境界や複数runtimeが混在しrepo全体の単一判定が危険なら `ambiguous` |
| `mcp_tooling` | MCPのclient/server、tool登録、tool dispatchなどの実装または公開runtime surfaceがある | 固定SHAの対象範囲を走査して該当surfaceがない | 取得・走査範囲が不十分なら `unknown` |
| `formal_github_fork` | GitHub repository APIの `fork=true` | GitHub repository APIの `fork=false` | API取得不能、または固定SHAとの対応を検証できない場合 |
| `derived_concept` | `karpathy/autoresearch` 等、既知プロジェクトとの派生・着想関係を明示している | 固定SHA全体にその関係の明示根拠がない | 走査がpartial、または表現が単なる一般語で関係を特定できない場合 |

`ai_assisted_development` は「AIを使った証拠」を評価し、`agentic_runtime` は「対象ソフトウェア自身の実行時制御」を評価する。外部Claude/Codexが対象repoを操作するだけのケースは、後者のYes根拠にしない。

## 7軸score

すべて0〜10。小数は使用できるが、根拠の粒度を超えた精密さを避ける。下表は校正用アンカーであり、単語の出現数を点数へ変換しない。

| 軸 | 0 | 3〜4 | 6〜7 | 8〜10 |
| --- | --- | --- | --- | --- |
| Originality / 自作度 | formal forkまたは独自性を確認できない | 既存概念・部品の単純な派生 | 独立実装と独自の統合がある | 明確な独自設計・実装・provenanceがある |
| Agenticity | model-controlled runtime pathなし | model callまたはtool surfaceのみ | model-controlled dispatchはあるがfeedbackが弱い | action選択、dispatch、観測、replanが実行経路で接続 |
| Dynamic tool selection | tool surfaceなし | toolはあるが固定/モデル制御を確認できない | モデル出力によるdispatchを確認 | 複数toolから状況に応じて選び、結果で次手が変わる |
| Feedback adaptation | 観測または再計画なし | 観測・履歴保持のみ | retry/分岐はあるが適応の範囲が限定的 | tool/environment結果が後続model/actionへ明確に戻る |
| Goal-directed loop | goal・loopなし | loopまたはterminationのみ | loopと停止条件がある | goal、loop、termination、replanが接続 |
| Verification | test/CI/assertionの根拠なし | 1種類の検証信号 | tests＋CIまたはassertion | tests、CI、assertion/実行検証が揃う |
| Agent tooling | agent向けtool surfaceなし | tool/APIはあるがagent制御不明 | tool登録または実行経路あり | tool surfaceとmodel-controlled dispatchが接続 |

スコア根拠は少なくとも1件の固定SHA上の `file:line` を持つ。分類根拠と同じ行を再利用してもよいが、`notes` にその軸で何を示すかを書く。scoreが証拠不足なら数値を補完せず、将来はscore evidenceとともに未注釈に戻す。

## 評価の進め方

1. calibration setを先に2名で注釈し、定義のずれを解消する。
2. 残りのevaluation setを独立に注釈する。相手のラベル、AgentScopeのreport、混同行列は先に見ない。
3. 不一致は固定SHAの追加根拠でadjudicateし、`annotation.adjudicator`、`agreement`、protocol versionを記録する。
4. `benchmark score` は軸ごとにprecision、recall、FP、FN、coverage、abstentionを計算し、scoreはMAE/RMSEを計算する。draftの数値は探索的な校正値としてのみ報告する。


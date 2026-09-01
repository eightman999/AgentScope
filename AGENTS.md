# AgentScope エージェント運用メモ

spec.md がこのプロジェクトの唯一の正典である。判断に迷ったら推測せず該当節を読む。

このファイルと spec.md が矛盾した場合は spec.md を正とする。

## プロジェクト固有の要約

- 実装順とチェック項目は IMPLEMENTATION_PLAN.md を参照する。
- P0はGitHub公開URL一つを入力するlocal CLI監査であり、P1/P2を先行実装しない。
- 対象repositoryのコード、test、build、package installを実行しない。
- AI-assisted development、runtime Agentic AI、MCP/tooling、Formal GitHub fork、Derived conceptを別々に判定する。
- scoreと主要判定には、検証済みのfile:line evidenceを必ず付ける。
- score計算、Unknown伝播、evidence検証、finish gateはLLMに任せず決定論的なコードで行う。
- model outputはstrict schema、参照ID検証、range検証、1回限定retryを通す。
- 固定tool sequenceをLLMで説明してagentに見せる実装は禁止する。
- P0の推論は内蔵local modelだけで行い、外部LLM APIへ送信しない。

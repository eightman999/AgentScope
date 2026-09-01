# Fixed-SHA annotation evidence

このファイルは、初回draft注釈で使ったGitHub API、bounded Git provenance、固定SHA scanの結果を行単位でmaterializeした台帳である。各caseの `commit_sha` と、この台帳を作成した時点の取得範囲を対応させる。対象リポジトリのソース根拠は、各行に記録した `file:line` を固定SHA上で再確認する。

## microsoft-autogen
- fixed-snapshot: `027ecf0a379bcc1d09956d46d12d44a3ad9cee14`; runtime=`README.md:16`; tooling=`README.md:67`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## langchain-langgraph
- fixed-snapshot: `11ee185999b86bfea2d8c0e69cef9a5e37acf686`; runtime=`README.md:12`; tooling=`README.md:42`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## crewai
- fixed-snapshot: `48cc5d4e5ea7ec84db148f07f36bb1f4054b5fff`; runtime=`README.md:58`; tooling=`README.md:125`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## huggingface-smolagents
- fixed-snapshot: `30bb1161095dbae2271e6bc3cc4c219cc3897a57`; runtime=`README.md:34`; tooling=`README.md:46`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## pydantic-ai
- fixed-snapshot: `14d54980444d2fef0aa5d0869cf3b1537dd7bd43`; runtime=`README.md:26`; tooling=`README.md:79`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## openhands
- fixed-snapshot: `b4428e1f8529fe726039437c8e54a7e7319986eb`; runtime=`README.md:7`; tooling=`README.md:44`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## karpathy-nanogpt
- fixed-snapshot: `3adf61e154c3fe3fca428ad6bc3818b27a3b8291`; runtime=`README.md:13`; tooling=`README.md:13`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## llama-cpp
- fixed-snapshot: `c845263f8b7d60113e213a3bd2d5cc6472ccf204`; runtime=`README.md:7`; tooling=`README.md:92`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## vllm
- fixed-snapshot: `cdefd9d4997f00da72dc6245cc60678b50761b7e`; runtime=`README.md:24`; tooling=`README.md:48`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: `git-log.txt:7 Co-authored-by: Codex <codex@openai.com>`。

## openai-whisper
- fixed-snapshot: `86098128c0b4f24f0e2aa2994de830614b474227`; runtime=`README.md:8`; tooling=`README.md:32`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: `git-log.txt:17 Claude-Session` および `git-log.txt:19 Co-authored-by: Claude Opus 5`。

## huggingface-transformers
- fixed-snapshot: `ac3244569528944b9d5773cafea525cd8a8b63de`; runtime=`README.md:63`; tooling=`src/transformers/tokenization_utils_base.py:3225`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## openai-python
- fixed-snapshot: `b19c2161b1eac80fbf1f6f67a64a50af99c53356`; runtime=`README.md:6`; tooling=`src/openai/lib/_tools.py:40`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## mcp-python-sdk
- fixed-snapshot: `d2290ca3434731b68ea3e2270bc06a6e6575931b`; runtime=`README.md:31`; tooling=`README.md:33`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## mcp-typescript-sdk
- fixed-snapshot: `dcc01028ff6a499a5728c2b6181c1727d52e2fab`; runtime=`README.md:35`; tooling=`README.md:39`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: `git-log.txt:7 Co-authored-by: Cursor <cursoragent@cursor.com>`。

## mcp-servers
- fixed-snapshot: `579c3903f30044eb702a599a74b3ae77588e722e`; runtime=`README.md:3`; tooling=`README.md:3`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## mcp-go
- fixed-snapshot: `8841bf7bfe8ad14103adaa0794269e57988cd48c`; runtime=`README.md:10`; tooling=`README.md:10`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## fastmcp
- fixed-snapshot: `62ef226b62c7ff7f5181e3b12078369111324eb5`; runtime=`README.md:29`; tooling=`README.md:29`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: `git-log.txt:6 Claude-Session` および `git-log.txt:8 Co-authored-by: Claude Fable 5`。

## mcp-go-sdk
- fixed-snapshot: `cb0de6413682bfbefb300a6c1e4d8046e2627b33`; runtime=`README.md:9`; tooling=`README.md:10`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## dinesh-vibecodeschool
- fixed-snapshot: `a970ce7cd90acdd687beff5cb7b4a6559aaed230`; runtime=`README.md:7`; tooling=`README.md:21`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: `git-log.txt:11 Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

## tmad-vibe-coding-guide
- fixed-snapshot: `8339b8d455a41db315b36e804f53055252947e71`; runtime=`README.md:3`; tooling=`README.md:148`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: `git-log.txt:6 Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

## enzed-vibe-coding
- fixed-snapshot: `8b650568ea41515950f75bee255d03ac96db8e62`; runtime=`README.md:10`; tooling=`README.md:9`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。READMEはClaude Code/Codexを明示。

## vibe-claude
- fixed-snapshot: `8c2e996fd5b37e37393d25dc98ea2d97f44e982f`; runtime=`README.md:9`; tooling=`README.md:21`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。READMEはClaude Code pluginを明示。

## throughstone
- fixed-snapshot: `1ebcc26d7a60ab112b1b0c5027eb949c8e95ef57`; runtime=`README.md:5`; tooling=`README.md:527`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: `git-log.txt:63 Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`。

## vibecode
- fixed-snapshot: `1b3aab1481087850c9e6458001c126ec642ab5cf`; runtime=`README.md:9`; tooling=`README.md:11`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。READMEはClaude Code/Codex向け設定管理を明示。

## langchain
- fixed-snapshot: `b4d46a503e7de6fa3bb9c78d67510e2ee7bf238b`; runtime=`README.md:24`; tooling=`README.md:51`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## llama-index
- fixed-snapshot: `9f42cf0bd45a756f86ca325e343b9be9031d7928`; runtime=`README.md:11`; tooling=`README.md:81`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## haystack
- fixed-snapshot: expected `64d7a1ff030080a82bfe44d3eab3b962d924073e` と取得HEADが不一致。runtime=`README.md:24`; tooling=`README.md:67`; verification=未確定; concept_scan=未確定。
- github-api: 固定SHAに対応するmaterialized API evidenceなし。`fork`はunknownとして扱う。
- git-provenance: 固定SHAに対応するmaterialized git evidenceなし。AI利用はunknownとして扱う。

## dspy
- fixed-snapshot: `59ce7601ec40cd2160ac64f476f9053efdc1599e`; runtime=`README.md:16`; tooling=`README.md:16`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。

## semantic-kernel
- fixed-snapshot: `3438d882147b6e3e19a161a5f0dcb64e23e181db`; runtime=`README.md:17`; tooling=`README.md:29`; verification=tests/CI/assertionsを確認; concept_scan=known autoresearch markerなし。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: `git-log.txt:9 Copilot-Session: 7700cf8b-af34-40cd-945b-f271edb4c6e3`。

## karpathy-autoresearch
- fixed-snapshot: `228791fb499afffb54b46200aca536f79142f117`; runtime=`README.md:14`; tooling=`README.md:14`; verification=tests/CI/assertionsを確認; concept_scan=`README.md:1,7` にautoresearch markerあり。
- github-api: `fork=false`; `parent_full_name=None`; provenance/github-repository-evidence.txtの固定取得結果をmaterialize。
- git-provenance: bounded git-logに明示的なAI co-author/session markerなし。READMEはClaude/Codex等の外部agent利用を明示。

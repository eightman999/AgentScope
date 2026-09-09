# AgentScope Field Note — 2026-09-09

## Observation

A meetup demo of an agent marketplace showed that meaningful agent behavior may be distributed across more than a short description or obvious tool declaration. The demonstrated bot/template structure reportedly included routine-like configuration, memory, skills, and internal agent-creation behavior.

The practical lesson for AgentScope is simple: **do not infer agenticity from README prose or a single manifest surface when executable configuration can live elsewhere.**

## Audit implications

When a repository or exported agent package exposes these surfaces, future AgentScope analysis should consider them as evidence candidates:

- routines / schedules / recurring triggers
- memory or persisted state configuration
- skills / procedural documents
- tool bindings / webhooks / external-action declarations
- internal agent / sub-agent creation paths
- planner / executor / supervisor relationships

These are not automatically positive evidence of an agentic runtime. They become useful only when AgentScope can connect them to an actual execution path or supported runtime configuration.

## Evidence discipline

Preserve the existing distinction between:

- marketing or descriptive claims
- static configuration that suggests capability
- executable wiring
- runtime path evidence

An official template can be a useful specimen for discovering hidden surfaces, but “official” must not be treated as proof that every included capability is active in a given repository.

## Future benchmark consideration

Add hard cases where agent behavior is encoded primarily in configuration / skill / routine files rather than conventional Python or TypeScript orchestration code. This can test whether AgentScope over-focuses on familiar code-level agent patterns.

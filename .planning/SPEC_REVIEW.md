# Spec Review

## Verdict

Approved for staged execution with constraints.

The spec is implementable because it uses MODULAR as the runtime base and limits `ai-agent-interview-guide-main` to design input. The v1 scope is correctly narrowed to a deterministic Agent-RAG-Memory loop instead of trying to ship multi-agent, semantic memory, reflection, dashboard, and LLM judge at once.

## Strengths

- Clear runtime ownership: MODULAR owns execution.
- Clear reference ownership: ai-agent-guide owns conceptual spec only.
- MCP interface is explicit and testable.
- Memory design is scoped and deterministic.
- Eval design is CI-friendly.
- Failure policy is explicit and avoids fake success.

## Required Corrections Before Further Execution

1. Treat current implementation as Phase 0 prototype until full review is complete.
2. Do not expand into semantic memory before v1 gate is stable.
3. Do not add LLM-as-judge until deterministic Agent eval is green.
4. Do not add dashboard work until trace data contract is stable.
5. Ensure any golden fixtures live outside ignored `data/`.

## Architecture Risks

| Risk | Severity | Decision |
|---|---:|---|
| `agent_answer` depends on `query_knowledge_hub` returning JSON citations embedded in text | Medium | Accept for v1; later extract shared structured helper |
| deterministic answer composer may look too simple | Medium | Accept for v1; goal is tool-use reliability, not generation quality |
| SQLite memory lacks semantic recall | Low for v1 | Accept; semantic memory is v2 |
| `main.py` now starts stdio server, making `python main.py` block | Low | Accept; this is correct MCP behavior |
| existing full test suite may expose unrelated fixture/config skips | Medium | Run full suite separately before final commit |

## Test Review

The required targeted gate is sufficient for v1 because it covers:

- MCP tool registration
- Agent orchestration success/failure
- memory isolation
- deterministic eval
- trace type compilation
- existing RAG metric utilities
- MCP tools/list e2e

Missing but recommended before final push:

- full `pytest`
- e2e `agent_answer` call using an injected or fixture-backed deterministic collection
- trace service filtering test for `trace_type=agent`

## Execution Approval

Approved next execution steps:

1. align implementation with this spec
2. add missing review-recommended tests if time allows
3. run targeted gate
4. run full suite
5. prepare commit

Blocked:

- semantic memory
- multi-agent
- reflection
- dashboard page redesign
- Ragas/LLM judge

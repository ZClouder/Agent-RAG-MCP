# Requirements

## R1. MCP Entrypoint And Tool Registry

- Root `main.py` must start the real MCP server path.
- Default MCP tool registration must be idempotent for built-in tools.
- Manual duplicate tool registration must still raise `ValueError`.
- `agent_answer` must appear in MCP `tools/list`.

## R2. Agent Closed Loop

- Add an `AgentOrchestrator` that accepts `query`, `user_id`, `session_id`, `collection`, and `top_k`.
- The orchestrator must always call `query_knowledge_hub` for v1 successful answers.
- RAG zero-result or zero-citation output must fail the Agent turn.
- Successful output must include `answer`, `citations`, `tool_calls`, `memory_events`, and `trace_id`.

## R3. Episodic Memory

- Add SQLite-backed episodic memory scoped by `user_id + session_id`.
- Successful Agent turns write one memory record.
- Failed Agent turns write no memory record.
- Reads must never cross user or session boundaries.

## R4. Agent Trace

- `TraceContext` must support `trace_type="agent"`.
- Every successful Agent turn must persist one agent trace record.
- Required ordered stages: `agent_start`, `memory_retrieve`, `tool_call`, `answer_compose`, `memory_write`, `agent_finish`.

## R5. Deterministic Agent Eval

- Add a deterministic Agent evaluation runner.
- Metrics: `tool_success_rate`, `citation_presence_rate`, `answer_contains_rate`, `memory_write_success_rate`, `trace_completeness_rate`.
- No Ragas or LLM-as-judge dependency in v1.

## R6. Test Gate

- New and existing targeted tests must pass.
- Recall tests must not use `0.0` thresholds as a quality pass.
- Missing deterministic fixtures must fail, not skip.

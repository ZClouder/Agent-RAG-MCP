# Agent-RAG-Memory Engineering Spec

## 1. Goal

Build a runnable Agent-RAG-Memory MCP system on top of `MODULAR-RAG-MCP-SERVER`.

The target system must prove this closed loop:

```text
MCP client
 -> agent_answer
 -> AgentOrchestrator
 -> scoped episodic memory read
 -> query_knowledge_hub RAG tool
 -> citation-backed answer
 -> scoped episodic memory write
 -> agent trace
 -> deterministic agent eval
```

This project uses `ai-agent-interview-guide-main` as the design source for Agent orchestration, tool use, and memory concepts. It does not use that project as the runtime base.

## 2. Source Projects

### Runtime Base

```text
D:\zjq\mianshi\项目\MODULAR-RAG-MCP-SERVER
```

Role:

- MCP stdio server
- RAG ingestion
- hybrid retrieval
- rerank
- response/citation builder
- trace persistence
- deterministic evaluation infrastructure
- existing tests

### Spec Reference

```text
D:\zjq\mianshi\项目\ai-agent-interview-guide-main
```

Role:

- Agent orchestration concepts: ReAct / Plan-Execute / Reflection
- tool registry concept
- short-term and long-term memory design
- engineering practice documentation

Runtime decision:

- v1 does not port the full `ai-agent-interview-guide-main` code.
- v1 extracts concepts and lands them inside MODULAR with tests.

## 3. Scope

### In Scope

- Fix stale MCP entrypoint.
- Fix MCP default tool registration stability.
- Add `agent_answer` MCP tool.
- Add deterministic single-agent orchestration.
- Add SQLite episodic memory.
- Add agent trace stages.
- Add deterministic Agent eval runner.
- Add unit and MCP e2e tests.

### Out Of Scope For v1

- multi-agent collaboration
- semantic memory
- vector memory recall
- reflection loop
- LLM-as-judge
- Ragas integration for Agent eval
- dashboard page redesign
- UI work

## 4. Public MCP Interface

### Tool: `agent_answer`

Input schema:

```json
{
  "query": "string, required",
  "user_id": "string, required",
  "session_id": "string, required",
  "collection": "string, required",
  "top_k": "integer, required, 1-20"
}
```

Success output:

```json
{
  "answer": "string",
  "citations": [],
  "tool_calls": [],
  "memory_events": [],
  "trace_id": "string"
}
```

Failure behavior:

- Return MCP `CallToolResult(isError=true)`.
- Do not write memory on failure.
- Persist an agent trace with failure metadata when execution reaches the orchestrator.

Fail-fast cases:

- empty `query`
- missing `user_id`
- missing `session_id`
- missing `collection`
- invalid `top_k`
- RAG tool error
- zero citations
- memory write failure

## 5. Agent Orchestration

### Class

```text
src/agent/orchestrator.py
```

Core class:

```python
AgentOrchestrator
```

Required injected dependencies:

- `query_tool_handler`
- `memory_manager`
- `trace_collector`

Required execution stages:

```text
agent_start
memory_retrieve
tool_call
answer_compose
memory_write
agent_finish
```

Design decisions:

- v1 always calls `query_knowledge_hub` for successful answers.
- v1 does not perform complex planning.
- v1 answer composition is deterministic and citation-grounded.
- Tool-use reliability matters more than open-ended reasoning.

## 6. Memory System

### Class

```text
src/memory/
```

Required types:

- `MemoryRecord`
- `MemoryEvent`
- `EpisodicMemoryStore`
- `MemoryManager`

Storage:

```text
SQLite
default db path: data/db/episodic_memory.db
```

Scope key:

```text
user_id + session_id
```

Rules:

- Successful turns write one episodic memory record.
- Failed turns write no memory.
- Reads must not cross user/session boundaries.
- JSON payloads must be strictly serializable.
- Same memory id + same payload is idempotent.
- Same memory id + different payload fails.

v1 intentionally excludes semantic memory because semantic extraction quality is hard to test deterministically.

## 7. Trace

### Existing Base

```text
src/core/trace/trace_context.py
src/core/trace/trace_collector.py
```

Required trace types:

```text
query | ingestion | agent | evaluation
```

Agent trace requirements:

- one trace per Agent turn
- ordered stages
- every stage records `success`, `error`, `input_count`, `output_count`
- final response returns `trace_id`

Dashboard decision:

- No v1 dashboard redesign.
- Existing trace JSONL and trace service can read `agent` traces.

## 8. Evaluation

### Class

```text
src/observability/evaluation/agent_eval_runner.py
```

Runner style:

- deterministic
- injectable `agent_runner(case) -> dict`
- no external LLM
- no Ragas
- fail-fast

Metrics:

```text
tool_success_rate
citation_presence_rate
answer_contains_rate
memory_write_success_rate
trace_completeness_rate
```

Default threshold:

```text
all metrics >= 1.0 unless fixture overrides
```

Golden fixture path:

```text
tests/fixtures/eval/agent_golden.json
```

## 9. Test Gate

Required targeted gate:

```bash
python -m pytest tests/unit/test_agent_answer_tool.py tests/unit/test_agent_orchestrator.py tests/unit/test_memory_manager.py tests/unit/test_agent_eval_runner.py tests/unit/test_protocol_handler.py tests/unit/test_trace_service.py tests/unit/test_custom_evaluator.py tests/unit/test_fusion_rrf.py tests/e2e/test_mcp_client.py -q
python -m compileall src -q
```

Expected:

- all pass
- no skipped quality gate for the new Agent path

Full-suite run is recommended before commit/push, but targeted gate defines v1 acceptance for this spec.

## 10. Execution Policy

Future execution must follow:

1. update this spec or linked phase plan first
2. review spec impact
3. implement only reviewed scope
4. run targeted gate
5. update `.planning/STATE.md`

No unreviewed large-scope execution.

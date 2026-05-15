# Agent-RAG-MCP Project Context

## Goal

Turn the existing Modular RAG MCP Server into a runnable Agent-RAG-Memory system suitable for real engineering demonstration and testing.

The project must prove a complete closed loop:

```text
user query -> agent orchestration -> memory read -> RAG tool call -> answer with citations -> memory write -> trace -> deterministic eval
```

## Source Of Truth

- Runtime base: this repository, `MODULAR-RAG-MCP-SERVER`.
- Design spec source: `ai-agent-interview-guide-main`, especially Agent orchestration, tool use, and memory-system docs.
- Final implementation target: this worktree branch `feature/agent-rag-memory-sdd`.

## Non-Negotiables

- No fallback-as-success behavior.
- Missing config, missing collection, empty query, zero retrieved results, empty citations, failed tool calls, or incomplete trace must fail tests.
- v1 implements a single Agent, not multi-agent.
- v1 implements episodic memory only, not semantic memory.
- v1 uses deterministic tests and does not require external LLM judges.

## Current Known Baseline

- `query_knowledge_hub`, hybrid retrieval, rerank, trace, dashboard, and evaluation modules exist.
- `main.py` is stale and still reports MCP as future work.
- `tests/unit/test_protocol_handler.py` has one failing test caused by default tool duplicate registration.
- `tests/e2e/test_recall.py` has zero quality thresholds and weak skip behavior.
- No `src/agent` or `src/memory` module exists yet.

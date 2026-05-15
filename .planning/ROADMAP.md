# Roadmap

## Phase 1 - Baseline Repair

Goal: make the existing MCP baseline honest and stable.

- Fix stale root `main.py`.
- Fix default MCP tool duplicate registration.
- Preserve manual duplicate registration error behavior.
- Confirm targeted MCP/unit tests pass.

## Phase 2 - Agent And Tool Use

Goal: add a minimal deterministic Agent loop over existing RAG MCP tooling.

- Add `src/agent`.
- Add `agent_answer` MCP tool.
- Route through `query_knowledge_hub`.
- Fail on bad input, failed tool call, zero results, or zero citations.
- Add unit and MCP e2e tests.

## Phase 3 - Episodic Memory

Goal: add scoped persistent turn memory with hard test isolation.

- Add `src/memory`.
- Use SQLite episodic memory store.
- Add read/write/event APIs.
- Test successful writes, failed non-writes, and user/session isolation.

## Phase 4 - Agent Trace And Evaluation

Goal: make Agent behavior observable and measurable.

- Extend trace type to `agent`.
- Persist ordered Agent stages.
- Add deterministic `AgentEvalRunner`.
- Add golden fixture and metric threshold tests.

## Phase 5 - Quality Gate And Remote Readiness

Goal: produce a clean branch ready to push to `Agent-RAG-MCP`.

- Run targeted unit/e2e gate.
- Remove weak recall threshold behavior or replace with deterministic fixture checks.
- Ensure branch status is clean except intended changes.
- Prepare push command to `origin feature/agent-rag-memory-sdd`.

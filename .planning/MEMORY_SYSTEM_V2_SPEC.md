# Memory System V2 Spec

## 1. Review Verdict

Approved as a business-scoped upgrade, not a generic memory-platform rewrite.

The current project is a Modular RAG MCP Server for a consumer-brand content operations knowledge retrieval system.

Business background:

- Users are content operations teammates.
- High-frequency workflows include product information verification, content topic ideation, script compliance checks, and post-campaign review optimization.
- The knowledge base integrates 300+ internal documents: product materials, brand guidelines, script templates, and historical review documents.
- The evaluation loop uses 200+ business queries to reduce manual cross-document checking cost and content compliance risk.

Memory should improve this workflow:

```text
operator query -> agent_answer -> relevant workflow context -> RAG retrieval -> cited answer -> durable learning
```

V2 must focus on useful, auditable operational context:

- user preferences: answer style, language, preferred evidence format
- workflow context: recurring operational scenarios such as product checks, topic ideation, compliance review, and post-campaign review
- compliance focus: stable high-level risk concerns explicitly supplied by the user
- evaluation feedback: durable feedback about offline business query coverage

V2 must not store arbitrary chat details just because a memory framework can.

Important boundary:

- Product facts, brand rules, script templates, and historical review contents remain in the RAG document store.
- Memory cards store how the operator uses the system and what stable retrieval preferences or review focus should influence future answers.

## 2. Design Sources

- AI Agent memory fundamentals: short-term vs long-term memory, episodic vs semantic memory, summary/compression, recency + relevance + importance retrieval.
- Claude-style memory system: session memory, project memory, auto extraction, limited top-N memory injection, and periodic distillation from logs into structured cards.

Runtime decisions:

- Use deterministic rules in V2. Do not call an LLM to extract memories yet.
- Keep SQLite as the source of truth.
- Keep existing episodic memory as the raw event log.
- Add structured memory cards as curated long-term context.

## 3. In Scope

- Add `MemoryCard` as structured long-term memory.
- Add SQLite-backed `MemoryCardStore`.
- Add deterministic `MemoryExtractor` for explicit and high-confidence memories.
- Extend `MemoryManager` to:
  - write episodic memory for successful turns
  - extract and upsert memory cards from successful turns
  - retrieve a small mixed memory context for Agent injection
- Update Agent answer composition to surface relevant memory context.
- Add unit tests for card CRUD, extraction safety, retrieval ranking, and Agent integration behavior.

## 4. Out Of Scope

- vector memory recall
- LLM-based memory extraction
- background distillation job
- dashboard redesign
- user-facing memory editing UI
- multi-agent memory sharing
- graph memory
- automatic project-wide memory file generation

These are valid later phases after V2 is stable.

## 5. Memory Types

### episodic

Existing durable event log:

- query
- answer
- tool calls
- citations
- trace id
- timestamps

Purpose: audit trail and future distillation input.

### preference

User-level preference that affects future answers.

Examples:

- "The operator prefers Chinese answers."
- "The operator wants conclusions first, then evidence."
- "The operator wants compliance answers to include cited source documents."

### workflow

Stable content-operations workflow context.

Examples:

- "The operator often searches across product verification, topic ideation, script compliance, and review optimization workflows."
- "For script compliance questions, prefer risk points, supporting documents, and suggested revisions."

### compliance

Stable high-level compliance focus explicitly provided by the user.

Examples:

- "Script compliance answers should focus on brand guidelines and content compliance risk."
- "Product verification must cite sources and avoid unsupported claims."

### evaluation

Durable feedback about offline business query coverage or retrieval quality.

Examples:

- "The offline evaluation set covers 200+ business queries."
- "Review-optimization queries should validate recall from historical review documents."

## 6. Storage

New table:

```text
memory_cards
```

Required fields:

- `id`
- `user_id`
- `session_id`
- `project_id`
- `card_type`
- `title`
- `description`
- `content`
- `importance`
- `confidence`
- `source`
- `evidence_ids_json`
- `created_at`
- `updated_at`
- `last_accessed_at`
- `pinned`
- `status`

Allowed `card_type` values:

```text
preference | workflow | compliance | evaluation
```

Allowed `status` values:

```text
active | archived | needs_review
```

## 7. Extraction Rules

V2 extraction is intentionally conservative.

Write a card when:

- the user explicitly says "remember", "记住", "请记住", "以后", or "下次"
- the content describes a stable preference, workflow context, compliance focus, or evaluation feedback
- the content does not match secret/credential patterns

Do not write a card when:

- the content contains passwords, tokens, API keys, private keys, or secrets
- the content is a temporary experiment
- the content is an unverified guess
- the content is only a normal knowledge question

Every extracted card must include evidence pointing back to the episodic memory record id.

## 8. Retrieval Rules

`MemoryManager.retrieve()` returns a small context set for the Agent:

- retrieve active cards scoped by `user_id`
- prefer matching `session_id` or project-level cards
- score by lexical relevance, importance, confidence, pinned status, and recency
- inject at most 5 total memory items

This follows the Claude-style small high-signal memory injection principle.

## 9. Agent Integration

The Agent orchestration stages remain stable:

```text
agent_start
memory_retrieve
tool_call
answer_compose
memory_write
agent_finish
```

The `memory_retrieve` stage may now return structured memory cards in addition to episodic records.

The answer composer may include a short "Relevant memory" section only when memory contexts exist. It must not invent or overstate memory content.

## 10. Acceptance Criteria

- Existing Agent and episodic memory tests still pass.
- Memory cards can be written, listed, searched, and updated idempotently.
- Secret-like inputs are not written as cards.
- Explicit user preferences are written as preference cards.
- Workflow/compliance/evaluation constraints can be written as structured cards.
- Agent memory write events include both episodic write and card upsert events when extraction succeeds.
- Retrieval returns no more than 5 contexts.

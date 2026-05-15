# Task Query Router And Lightweight Business Graph Spec

## 1. Research Review

Verdict: suitable, but the first implementation should be a lightweight business graph and deterministic task router, not a full graph database.

Why:

- The business has stable task types: brief generation, content topic ideation, script compliance, product information verification, and post-campaign review optimization.
- The document set has natural semantic groups: product materials, brand guidelines, script templates, and historical review documents.
- The main retrieval risk is not only vector similarity. It is choosing the right operational context and evidence type before retrieval.
- Knowledge graph ideas fit because task nodes can connect to document-type nodes, evidence requirements, compliance risks, and rewrite terms.

Additional open-source research:

- Microsoft GraphRAG is useful for extracting structured data from unstructured text and improving reasoning over private data, but its own README warns that indexing can be expensive and recommends starting small.
- LightRAG validates the value of combining graph structures with vector retrieval, especially for comprehensiveness and diversity, but it is still a full graph-enhanced RAG stack rather than a small routing layer.
- HippoRAG shows graph-based retrieval can help multi-hop question answering, but its target is deeper long-term knowledge integration rather than content-operations query classification.
- OpenSPG/KAG is closer to professional-domain reasoning. It emphasizes schema-constrained construction and logical-form-guided hybrid retrieval, which is directionally relevant but too heavy for v1.
- Neo4j GraphRAG provides mature graph/vector/full-text retrieval patterns, but it adds an external database and operational dependency that should wait until the lightweight graph proves value on the 200+ business Query set.
- LangGraph is suitable later for explicit workflow orchestration and conditional edges, but v1 can implement the same deterministic routing contract without adding runtime orchestration complexity.

Boundary:

- Do not replace the existing Hybrid Search.
- Do not introduce Neo4j or a heavy GraphRAG stack in v1.
- Do not hard-filter by doc type unless metadata is known to be complete.
- Use graph expansion to guide query rewriting and trace/debug metadata.

## 2. Business Goal

Improve retrieval for a consumer-brand content operations knowledge system serving:

- product information verification
- brief generation
- content topic ideation
- script compliance
- post-campaign review optimization

The system should automatically identify query intent and rewrite the query with business-specific terms before running existing hybrid retrieval.

## 3. In Scope

- Add a deterministic `TaskQueryRouter`.
- Add a lightweight in-code business graph.
- Support intents:
  - `product_verification`
  - `brief_generation`
  - `topic_ideation`
  - `script_compliance`
  - `review_optimization`
  - `general`
- Generate rewritten queries for retrieval.
- Attach retrieval profile metadata:
  - preferred document types
  - evidence requirements
  - dense/sparse/fusion top-k suggestions
  - rerank preference
- Integrate routing into `query_knowledge_hub` before Hybrid Search.
- Add trace metadata for route decisions.
- Add unit tests.

## 4. Out Of Scope

- LangGraph runtime orchestration
- Neo4j / external graph database
- entity extraction from all documents
- multi-hop GraphRAG
- strict metadata filtering by doc type
- LLM-based routing

These can be later phases after offline evaluation confirms routing helps.

## 5. Routing Logic

Route scoring uses deterministic keyword overlap.

Examples:

- `产品参数是否准确` -> `product_verification`
- `生成小红书投放 brief` -> `brief_generation`
- `下周新品内容选题` -> `topic_ideation`
- `这段脚本是否违反品牌规范` -> `script_compliance`
- `复盘上次活动转化差的原因` -> `review_optimization`

If no intent score is strong enough, route to `general`.

## 6. Lightweight Business Graph

Graph node types:

- task nodes
- document type nodes
- evidence nodes
- risk/focus nodes
- rewrite term nodes

Example relations:

```text
script_compliance -> brand_guideline
script_compliance -> script_template
script_compliance -> compliance_risk
product_verification -> product_material
brief_generation -> product_material
brief_generation -> brand_guideline
topic_ideation -> historical_review
topic_ideation -> script_template
review_optimization -> historical_review
```

The graph contributes rewrite terms and evidence expectations. It does not replace the document index.

## 7. Query Rewrite

A routed query becomes:

```text
{original query}
业务场景:{intent label}
优先资料:{preferred doc types}
关注点:{focus terms}
证据要求:{evidence requirements}
```

Only compact terms are appended. The rewrite must not invent product facts or brand rules.

## 8. Acceptance Criteria

- `TaskQueryRouter` classifies the five business task intents.
- The router produces deterministic rewritten queries.
- `query_knowledge_hub` uses the rewritten query for Hybrid Search.
- Route-specific retrieval profiles adjust dense/sparse initial recall sizes before Hybrid Search runs.
- Route decisions are recorded in query trace metadata.
- Existing query tests and MCP tool tests still pass.
- The implementation is dependency-free and does not require LangGraph or graph DB setup.

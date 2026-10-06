---
type: concept
origin: ai
knowledge_status: processed
domain:
- ai
- memory-systems
- nlp
created: '2026-10-06'
updated: '2026-10-06'
sources:
- '[[A-MEM]]'
human_verified: true
verified_by: ai
---

# Retrieve Relative Memory

> AI-generated knowledge. Verify against original sources before treating as understood.

## Definition

A context-aware retrieval mechanism that identifies and selects the most relevant historical memory notes for a current interaction query to enrich the agent's reasoning process.

## Core Idea

Using dense vector representations and cosine similarity to retrieve k most relevant memories from storage based on the current query.

## Mechanism

The process begins by computing a dense vector representation of the current query text using a text encoder. It then calculates cosine similarity scores between this query embedding and all existing memory notes in the storage M. Finally, it selects the k memories with the highest similarity scores to construct a contextually appropriate prompt.

## Key Points

- Computes dense vector representation of the query using a text encoder.
- Calculates cosine similarity between query embedding and memory notes.
- Retrieves the k most relevant memories from historical storage.
- Constructs a contextually appropriate prompt using retrieved memories.
- Connects current interaction with related past experiences.

## Related Concepts

- Dense vector representation (suggested)
- Cosine similarity (suggested)
- Memory notes (suggested)
- Text encoder (suggested)
- Contextual prompt (suggested)

## Evidence

### Evidence 1
- Claim: The system computes dense vector representations of queries using a text encoder.
- Source: [[A-MEM]]
- Excerpt: we first compute its dense vector representation using the same text encoder used for memory notes
- Chunk: `subsection-009e7175-3f046882756f3dd4`

### Evidence 2
- Claim: Similarity scores are computed between query embeddings and memory notes using cosine similarity.
- Source: [[A-MEM]]
- Excerpt: computes similarity scores between the query embedding and all existing memory notes in M using cosine similarity
- Chunk: `subsection-009e7175-3f046882756f3dd4`

### Evidence 3
- Claim: The k most relevant memories are retrieved to construct a prompt.
- Source: [[A-MEM]]
- Excerpt: retrieve the k most relevant memories from the historical memory storage to construct a contextually appropriate prompt
- Chunk: `subsection-009e7175-3f046882756f3dd4`

## Sources

- [[A-MEM]]

## Open Questions

- What is the specific value of k used for retrieval?
- How does the text encoder handle varying query lengths?
- Are there any filtering criteria applied before similarity computation?

## Provenance

- Backend: `ollama`
- Model: `qwen3.5:27b`
- Evidence sources: [[A-MEM]]
- Verification: reviewed by Claude Code (AI) on 2026-10-06; 3 of 3 evidence excerpts found verbatim in the Source.

---
type: concept
origin: ai
knowledge_status: processed
domain:
- ai
- knowledge-management
- large-language-models
created: '2026-10-06'
updated: '2026-10-06'
sources:
- '[[A-MEM]]'
human_verified: true
verified_by: ai
---

# Agentic Memory

> AI-generated knowledge. Verify against original sources before treating as understood.

## Definition

A dynamic memory system for LLM agents that organizes memories into interconnected knowledge networks by generating structured notes with contextual attributes and establishing links based on meaningful similarities, allowing the network to evolve as new memories are integrated.

## Core Idea

To overcome the rigidity of predefined schemas in existing memory systems by using agent-driven decision-making to dynamically index, link, and update memories following Zettelkasten principles.

## Mechanism

When a new memory is added, the system generates a comprehensive note containing structured attributes such as contextual descriptions, keywords, and tags. It then analyzes historical memories to identify relevant connections and establishes links where meaningful similarities exist. This process enables memory evolution, where integrating new memories triggers updates to the contextual representations and attributes of existing historical memories.

## Key Points

- Dynamically organizes memories in an agentic way rather than using fixed operations.
- Follows Zettelkasten principles to create interconnected knowledge networks.
- Generates comprehensive notes with structured attributes including context, keywords, and tags.
- Establishes links between memories based on meaningful similarities identified through analysis.
- Enables memory evolution by updating existing historical memories when new information is integrated.

## Related Concepts

- Zettelkasten method (suggested)
- Graph databases (suggested)
- Retrieval-Augmented Generation (RAG) (suggested)
- LLM Agents (suggested)
- Knowledge networks (suggested)

## Evidence

### Evidence 1
- Claim: The system creates interconnected knowledge networks through dynamic indexing and linking following Zettelkasten principles.
- Source: [[A-MEM]]
- Excerpt: Following the basic principles of the Zettelkasten method, we designed our memory system to create interconnected knowledge networks through dynamic indexing and linking.
- Chunk: `chunk-0001-621f107f4505597a`

### Evidence 2
- Claim: New memories trigger updates to existing historical memories, allowing the network to refine its understanding.
- Source: [[A-MEM]]
- Excerpt: as new memories are integrated, they can trigger updates to the contextual representations and attributes of existing historical memories, allowing the memory network to continuously refine its understanding.
- Chunk: `chunk-0001-621f107f4505597a`

### Evidence 3
- Claim: The system generates comprehensive notes with structured attributes including contextual descriptions, keywords, and tags.
- Source: [[A-MEM]]
- Excerpt: When a new memory is added, we generate a comprehensive note containing multiple structured attributes, including contextual descriptions, keywords, and tags.
- Chunk: `chunk-0001-621f107f4505597a`

## Sources

- [[A-MEM]]

## Open Questions

- How does the system quantify 'meaningful similarities' to establish links between memories?
- What specific criteria determine when an existing historical memory should be updated versus left unchanged?
- How does the dynamic linking process scale with large volumes of historical memories?

## Provenance

- Backend: `ollama`
- Model: `qwen3.5:27b`
- Evidence sources: [[A-MEM]]
- Verification: reviewed by Claude Code (AI) on 2026-10-06; 3 of 3 evidence excerpts found verbatim in the Source.

---
type: concept
origin: ai
knowledge_status: processed
domain:
- machine-learning-architecture
- nlp
- sequence-to-sequence-models
created: '2026-09-27'
updated: '2026-09-27'
sources:
- '[[attention_is_all_you_need]]'
human_verified: true
verified_by: ai
---

# Multi-Head Attention

> AI-generated knowledge. Verify against original sources before treating as understood.

## Definition

A mechanism allowing a model to jointly attend to information from different representation subspaces at different positions.

## Core Idea

Parallel attention heads with reduced dimensionality enable the model to capture diverse relationships while maintaining computational efficiency comparable to single-head full-dimensionality attention.

## Mechanism

Concatenating outputs of multiple parallel attention layers (head_i = Attention(QW_Qi, KW_Ki, VW_Vi)) projected by a weight matrix W_O.

## Key Points

- Multi-head attention allows joint attention to information from different representation subspaces.
- Single attention heads inhibit attending to information from different subspaces due to averaging.
- Parallel heads use reduced dimensionality (d_k = d_model / h) to keep total computational cost similar to single-head full dimensionality.
- The model employs 8 parallel attention layers with a dimension of 64 per head.
- Dot products in attention can grow large due to the summation of independent random variables.

## Related Concepts

- Self-attention (suggested)
- Encoder-decoder attention (suggested)
- Positional encoding (suggested)
- Feed-forward networks (suggested)
- [[Scaled Dot-Product Attention]]

## Evidence

### Evidence 1
- Claim: Multi-head attention allows the model to jointly attend to information from different representation subspaces at different positions.
- Source: [[attention_is_all_you_need]]
- Excerpt: Multi-head attention allows the model to jointly attend to information from different representation subspaces at different positions.
- Chunk: `chunk-0004-c49a25f4c4191793`

### Evidence 2
- Claim: With a single attention head, averaging inhibits this.
- Source: [[attention_is_all_you_need]]
- Excerpt: With a single attention head, averaging inhibits this.
- Chunk: `chunk-0004-c49a25f4c4191793`

### Evidence 3
- Claim: The model employs h = 8 parallel attention layers, or heads, with dk = dv = dmodel/h = 64.
- Source: [[attention_is_all_you_need]]
- Excerpt: In this work we employ h = 8 parallel attention layers, or heads. For each of these we use dk=dv=dmodel/h=64.
- Chunk: `chunk-0004-c49a25f4c4191793`

## Sources

- [[attention_is_all_you_need]]

## Open Questions

- How does the specific choice of 8 heads impact performance compared to other configurations?
- What is the optimal balance between head count and dimensionality for different sequence lengths?
- Does the parallel structure improve robustness against noise in input representations?

## Provenance

- Backend: `ollama`
- Model: `qwen3.5:4b`
- Evidence sources: [[attention_is_all_you_need]]
- Verification: reviewed by Claude Code (AI) on 2026-10-06; 2 of 3 evidence excerpts found verbatim in the Source.

---
type: concept
origin: ai
knowledge_status: processed
domain:
- deep-learning-architecture
- nlp
- transformer-models
created: '2026-09-27'
updated: '2026-09-27'
sources:
- '[[attention_is_all_you_need]]'
human_verified: false
---

# Scaled Dot-Product Attention

> AI-generated knowledge. Verify against original sources before treating as understood.

## Definition

An attention mechanism mapping a query and key-value pairs to an output via a weighted sum of values, computed using dot products scaled by the square root of the key dimension.

## Core Idea

The attention function computes weights as softmax(QK^T / sqrt(d_k)) applied to values V, enabling parallel computation on matrix inputs Q, K, and V.

## Mechanism

Compute dot products between queries and keys, scale by 1/sqrt(d_k), apply softmax to generate weights, and multiply weights by values.

## Key Points

- Attention computes a weighted sum of values based on query-key compatibility.
- The scaling factor 1/sqrt(d_k) prevents large dot products from pushing softmax into regions with small gradients.
- Dot-product attention is faster and more space-efficient than additive attention due to optimized matrix multiplication.
- Scaled dot-product attention is identical to standard dot-product attention except for the normalization scaling factor.
- The mechanism allows simultaneous computation on multiple queries packed into a matrix.

## Related Concepts

- [[Multi-Head Attention]]
- Additive Attention (suggested)
- Layer Normalization (suggested)
- Residual Connections (suggested)
- Softmax Function (suggested)

## Evidence

### Evidence 1
- Claim: The output is computed as a weighted sum of values where the weight is a compatibility function of the query with the corresponding key.
- Source: [[attention_is_all_you_need]]
- Excerpt: An attention function can be described as mapping a query and a set of key-value pairs to an output, where the query, keys, values, and output are all vectors. The output is computed as a weighted sum of the values, where the weight assigned to each value is computed by a compatibility function of
- Chunk: `chunk-0003-392d6b685d3b4aa3`

### Evidence 2
- Claim: We compute the dot products of the query with all keys, divide each by sqrt(d_k), and apply a softmax function to obtain the weights on the values.
- Source: [[attention_is_all_you_need]]
- Excerpt: We call our particular attention "Scaled Dot-Product Attention". The input consists of queries and keys of dimension d_k, and values of dimension d_v. We compute the dot products of the query with all keys, divide each by sqrt(d_k), and apply a softmax function to obtain the weights on the values.
- Chunk: `chunk-0003-392d6b685d3b4aa3`

### Evidence 3
- Claim: Dot-product attention is much faster and more space-efficient in practice since it can be implemented using highly optimized matrix multiplication code.
- Source: [[attention_is_all_you_need]]
- Excerpt: While the two are similar in theoretical complexity, dot-product attention is much faster and more space-efﬁcient in practice, since it can be implemented using highly optimized matrix multiplication code.
- Chunk: `chunk-0003-392d6b685d3b4aa3`

## Sources

- [[attention_is_all_you_need]]

## Open Questions

- How does the scaling factor specifically impact gradient magnitude for very large d_k values?
- Are there alternative scaling factors that could further improve training stability without sacrificing speed?
- What is the optimal relationship between d_k and model performance across different sequence lengths?

## Provenance

- Backend: `ollama`
- Model: `qwen3.5:4b`
- Evidence sources: [[attention_is_all_you_need]]

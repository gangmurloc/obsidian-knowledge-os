---
type: concept
origin: ai
knowledge_status: processed
domain:
- deep-learning-architecture
- machine-translation
- nlp
created: '2026-09-27'
updated: '2026-09-27'
sources:
- '[[attention_is_all_you_need]]'
human_verified: false
---

# Transformer Model Performance and Training Efficiency

> AI-generated knowledge. Verify against original sources before treating as understood.

## Definition

The Transformer architecture achieves state-of-the-art machine translation results with significantly reduced training costs compared to prior ensemble methods.

## Core Idea

A single large-scale Transformer model outperforms complex ensembles of previous architectures in both BLEU score and computational efficiency, establishing a new standard for neural machine translation.

## Mechanism

Training utilizes multiple GPUs over several days with specific hyperparameters including dropout, label smoothing, and beam search to optimize perplexity and accuracy while minimizing floating-point operations.

## Key Points

- The big Transformer model achieves a BLEU score of 28.4 on English-to-German translation, surpassing all previous models by more than 2.0 points.
- Training the big model required 3.5 days on 8 P100 GPUs but operates at a fraction of the training cost of competitive ensembles.
- On the English-to-French task, the big model reaches a BLEU score of 41.0 with less than 1/4 the training cost of the previous state-of-the-art.
- Base models trained by averaging checkpoints outperform all previously published single models and ensembles.
- Label smoothing (epsilon=0.1) during training improves accuracy and BLEU scores despite increasing perplexity during training.

## Related Concepts

- Attention Is All You Need (suggested)
- Neural Machine Translation (suggested)
- Deep Learning Ensembles (suggested)
- GPU Training Optimization (suggested)
- Perplexity Reduction (suggested)

## Evidence

### Evidence 1
- Claim: The big transformer model outperforms the best previously reported models by more than 2.0 BLEU, establishing a new state-of-the-art score of 28.4.
- Source: [[attention_is_all_you_need]]
- Excerpt: On the WMT 2014 English-to-German translation task, the big transformer model (Transformer (big) in Table 2) outperforms the best previously reported models (including ensembles) by more than 2.0 BLEU, establishing a new state-of-the-art BLEU score of 28.4.
- Chunk: `chunk-0007-68aa0865fe1d978f`

### Evidence 2
- Claim: The Transformer (big) model trained for English-to-French used dropout rate Pdrop = 0.1, instead of 0.3.
- Source: [[attention_is_all_you_need]]
- Excerpt: On the WMT 2014 English-to-French translation task, our big model achieves a BLEU score of 41.0, outperforming all of the previously published single models, at less than 1/4 the training cost of the previous state-of-the-art model. The Transformer (big) model trained for English-to-French used droo
- Chunk: `chunk-0007-68aa0865fe1d978f`

### Evidence 3
- Claim: Training took 3.5 days on 8 P100 GPUs to achieve the new state-of-the-art BLEU score.
- Source: [[attention_is_all_you_need]]
- Excerpt: The conﬁguration of this model is listed in the bottom line of Table 3. Training took 3.5 days on 8 P100 GPUs.
- Chunk: `chunk-0007-68aa0865fe1d978f`

## Sources

- [[attention_is_all_you_need]]

## Open Questions

- How does varying the number of attention heads impact performance when computation is kept constant?
- What is the optimal ratio of training cost to BLEU score for different language pairs?
- Does averaging multiple checkpoints provide diminishing returns compared to single checkpoint selection?

## Provenance

- Backend: `ollama`
- Model: `qwen3.5:4b`
- Evidence sources: [[attention_is_all_you_need]]

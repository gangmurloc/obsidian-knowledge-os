---
type: system
origin: ai
knowledge_status: processed
domain:
  - knowledge-management
created: 2026-09-22
updated: 2026-10-06
human_verified: false
---

# Knowledge OS Architecture

## Purpose

The vault separates captured material, external evidence, AI-derived synthesis, and human-owned knowledge while connecting them through Wikilinks and properties. Folder location communicates ownership; metadata communicates type, provenance, state, and relationships.

## Information Flow

```text
PDF / HTML
    |
    v
Normalization to Markdown
    |
    +--> original PDF --------> _assets/PDF/
    +--> source Markdown -----> 30_Resources/Sources/
                                  |
                                  v
                   loopback endpoint (SSH tunnel)
                                  |
                                  v
                    user-owned lab-server Ollama
                                  |
                                  v
                         30_Resources/AI-Wiki/
                                  |
                           human review only
                                  |
                                  v
                         30_Resources/Knowledge/

Projects and Areas provide context at every stage.
Wikilinks + Properties form the graph.
Bases + Graph View provide visualization.
```

## Layers

### Input

- PDF files are immutable source artifacts after ingestion.
- HTML includes saved pages and Web Clipper output.
- New, unclassified captures enter `00_Inbox/`; automation must not infer their PARA destination.

### Normalization

- PDF becomes a Markdown source note, while the original remains in `_assets/PDF/`.
- The default PDF normalizer is the local, layout-aware PyMuPDF4LLM extractor. The previous pypdf path remains an explicit legacy option for comparison and fallback.
- HTML becomes Markdown with the canonical URL preserved in `source_url`.
- Normalization should preserve headings, quotations, page references, links, and available publication metadata.
- Extracted PDF page text is treated as untrusted plain text. Before insertion into the `Content` body, literal angle brackets are HTML-entity encoded; generated frontmatter and Markdown structure are outside this post-processing boundary.
- Every ingested PDF Source records its extraction method, quality state, and warning codes. Existing Sources are compared in dry-run and may be replaced only through an explicit atomic operation that preserves user-owned sections and custom properties.
- A normalized note is not yet human knowledge. It belongs under `30_Resources/Sources/`.

### Storage

- `30_Resources/Sources/Papers/`: Markdown normalized from academic papers.
- `30_Resources/Sources/Web/`: Markdown normalized from web pages or HTML.
- `_assets/PDF/`: original PDF files.
- `_assets/Images/`: images referenced by Markdown notes.
- Source notes are evidence records. AI reads them but does not silently rewrite them.

### Processing

- The default AI backend is Ollama on the user's own lab GPU server, running `qwen3.5:27b`. The server binds Ollama to `127.0.0.1`; the desktop reaches it only through a user-opened SSH local port forward at `localhost:11435`, so the pipeline still accepts loopback endpoints only and never opens the tunnel itself.
- PDF ingestion, preprocessing, chunking, deduplication, role assignment, the quality gate, and all file writes run on the desktop. Only LLM requests cross the tunnel: Source chunks for extraction, the model's own malformed response for JSON repair, and candidate summaries for curation.
- The limits designed for a 4B model are retained with the larger model: 1,024 output tokens, `think: false`, `temperature: 0`, one JSON repair, one concept per chunk, and 12 concepts per Source.
- The lab GPU is shared. Each request carries a bounded `keep_alive`, and a run that made at least one LLM call sends exactly one unload request after any write and state update. An unload failure is a warning and never changes the exit code. A failed connection is a technical failure with no fallback to another endpoint or port.
- Processing reads source notes, identifies concepts and relationships, and writes derived notes only to `30_Resources/AI-Wiki/`.
- PDF Sources are filtered into an in-memory AI processing view before chunking. References, paper checklists, and standalone contents pages are excluded; appendices, prose, headings, figure captions, and valid Markdown tables are retained. Low-confidence tables, raw figure/OCR text, and malformed or missing formulas are represented by PDF page markers without changing the Source.
- Chunk candidates are merged only by deterministic identity. Candidate roles keep reusable concepts, mechanisms, and components by default while normally filtering incidental datasets, metrics, baselines, and analyses; a dataset or metric derived from the Source title can remain when it is the Source contribution. Core method-section subsections provide weak supervision but never create concepts from headings alone. One localhost curator selects from candidate summaries when a Source has more than 12 candidates, contextual wrapper/source-title-alias heuristics identify duplicate risk, Source entities dominate, or explicit method coverage is missing. These aliases are comparison-only, and the heuristic is a trigger only, never a rename or automatic merge. The curator cannot create, rewrite, or semantically merge concepts, and its failure fails that Source without positional fallback.
- A post-curation semantic quality gate is separate from provider/schema failures. It rejects unresolved duplicate risk, excessive Source-entity dominance, multiple primary Source entities, generic Source-name-only output, and missing mechanism coverage when the document structure explicitly signals multiple named method subsections. A failed gate atomically blocks the entire AI-Wiki write and state update.
- Each derived note links to its evidence using the `sources` property and a visible `## Provenance` section.
- Version 1 must not send vault content to an external LLM API.

### Derived Knowledge

- `30_Resources/AI-Wiki/` is machine-maintained synthesis.
- AI may revise these notes when evidence changes, but it must preserve provenance and avoid unsupported claims.
- `human_verified: false` is the default until the note is reviewed against its Sources. A person may set it to `true`, and so may an AI reviewer under the Delegated Verification rules in [[AI_BOUNDARIES]]; an AI review is recorded as `verified_by: ai`.

### Human Review

- `30_Resources/Knowledge/` contains human-owned understanding, ideas, decisions, and applied knowledge.
- Promotion from AI-Wiki to Knowledge is a human decision, not an automated move or copy operation.
- AI may suggest edits, but suggestions must be delivered separately and never merged automatically into protected note bodies.

### Context

- `10_Projects/` connects knowledge to finite outcomes.
- `20_Areas/` connects knowledge to ongoing responsibilities.
- Projects and Areas may link to Sources, AI-Wiki, and Knowledge, but do not absorb or duplicate their contents.
- `40_Archives/` stores inactive material without deleting its graph history.

### Graph and Visualization

- Wikilinks express semantic relationships between notes.
- Properties provide queryable metadata governed by [[DATA_CONTRACT]].
- Obsidian Bases supplies structured tables and filtered views.
- Graph View supports relationship exploration; it is not the source of truth.

## System Layout

- `90_System/Templates/`: note templates
- `90_System/Prompts/`: reviewed prompts used by local automation
- `90_System/Bases/`: Base definitions and saved structured views
- `90_System/Docs/`: architecture and governance
- `90_System/Reports/`: dry-run output, audits, and AI suggestions
- `.automation/`: scripts, configuration examples, and local tooling; secrets are excluded

## Migration Rule

The target layout is adopted incrementally. Existing `templates/`, `attachment/`, periodic-note folders, root notes, Excalidraw content, and plugin data remain in place until the user approves a specific migration plan. Folder creation alone must not trigger file movement or property backfilling.

## Provenance

Generated by Codex from the user's "Gangil Obsidian Knowledge OS" PROMPT 1 on 2026-09-22 and updated through the layout-aware PDF and AI processing-view boundary on 2026-09-28. The LLM runtime description was updated by Claude Code on 2026-10-04 for the lab-server runtime (Stage S). Human review is pending.

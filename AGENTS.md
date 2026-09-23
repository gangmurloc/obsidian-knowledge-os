# Ganggil Knowledge OS

## Purpose

This vault is a long-lived Personal Knowledge OS integrating PARA, a personal knowledge graph, external sources, an AI-maintained wiki, human-owned knowledge, research projects, and a local AI agent.

## Map

- `00_Inbox/`: unprocessed capture
- `10_Projects/`: outcome-oriented work
- `20_Areas/`: ongoing responsibilities
- `30_Resources/Sources/`: normalized external source notes
- `30_Resources/AI-Wiki/`: AI-maintained derived knowledge
- `30_Resources/Knowledge/`: human-owned knowledge
- `40_Archives/`: inactive material
- `90_System/`: templates, prompts, Bases, documentation, and reports
- `_assets/`: preserved PDFs and images
- `.automation/`: local automation code and dry-run output

Detailed design: [[90_System/Docs/ARCHITECTURE]], [[90_System/Docs/DATA_CONTRACT]], and [[90_System/Docs/AI_BOUNDARIES]].

## Invariants

1. Treat `30_Resources/Sources/` as the external-knowledge source of truth.
2. AI may create and update `30_Resources/AI-Wiki/` only within the boundaries document.
3. Treat `30_Resources/Knowledge/` as human-owned. Never automatically edit its note bodies.
4. Never automatically edit the body of a note with `origin: me`.
5. Keep external knowledge, AI synthesis, and user knowledge in separate notes and folders.
6. Every AI-written claim must retain provenance through `sources` and the note's provenance section.
7. Preserve original PDFs in `_assets/PDF/`. Normalize PDF and HTML inputs to Markdown.
8. New automation must support dry-run by default. Never automate deletion.
9. Do not perform bulk rename, bulk move, or inferred PARA classification without explicit approval.
10. Never store API keys or credentials in Markdown. Use environment variables or an ignored local secret store.
11. Version 1 uses localhost-based local models only; do not call external LLM APIs.
12. Preserve unknown properties, existing links, and user-authored content unless the user explicitly requests a change.

Before writing, inspect the target note's path, `origin`, and ownership. When uncertain, produce a suggestion or report instead of changing the note.

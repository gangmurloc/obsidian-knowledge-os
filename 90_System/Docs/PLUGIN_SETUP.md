---
type: system
origin: ai
knowledge_status: processed
domain:
  - knowledge-management
created: 2026-09-22
updated: 2026-09-22
human_verified: false
---

# Plugin Setup

This audit reflects `.obsidian/` on 2026-09-22. No plugin was installed, enabled, disabled, or reconfigured during the audit.

## Current State

| Feature | Required/Optional | Installed | Enabled | Configuration Needed | Risk |
| --- | --- | --- | --- | --- | --- |
| Properties | Required | Yes, Core | Yes | No immediate change | Low; property types still require consistent templates |
| Templates | Required | Yes, Core | Yes | Current folder is `templates`; manually switch only after deciding what to do with the existing reading template | Medium; switching now would hide the existing template from the command |
| Backlinks | Required | Yes, Core | Yes | In-document backlinks are enabled | Low |
| Graph View | Required | Yes, Core | Yes | Attachments are hidden; keep Graph as a view, not a source of truth | Low |
| Bases | Required | Yes, Core | Yes | No `.base` files exist yet | Low; create views only after metadata stabilizes |
| Obsidian Web Clipper | Required external workflow | Not determinable from Vault | Not determinable from Vault | Install/configure in the browser and select this Vault; see [[WEB_INGEST]] | Medium; browser-side settings are outside Vault and Interpreter can call external models |
| PDF to Markdown | Required workflow | No converter plugin found | No | Use the local pipeline under `.automation/`; no plugin is required for v1 | Low for text PDFs; scanned PDFs require OCR |
| Smart Connections (`smart-connections`) | Optional | Yes, 4.7.2 | Yes | Verify Ollama remains the chat adapter and remove/disable stale external-provider settings manually | Medium; legacy `open_router` metadata is present even though the active chat adapter is Ollama |
| Local AI Wiki plugin | Optional | No matching plugin found | No | None for v1; local automation can write only to AI-Wiki | High if an autonomous plugin is granted broad write access |
| Readwise Official (`readwise-official`) | Optional | Yes, 3.0.4 | No | Leave disabled unless a deliberate Readwise workflow is approved | Medium; it introduces another external ingest path |

## MUST HAVE

- Core Properties, Templates, Backlinks, Graph View, and Bases. They are already enabled.
- Official Obsidian Web Clipper as a browser-side capture tool, configured manually according to [[WEB_INGEST]].
- The local PDF pipeline documented in `.automation/README.md`.
- A localhost model for AI generation. External fallback is prohibited in v1.

## LATER

- Bases dashboards after the property contract has been used on real notes.
- Smart Connections after confirming all chat and embedding traffic stays local.
- A dedicated local AI-Wiki plugin only if the file-based automation becomes insufficient and its exact write scope can be audited.
- Readwise only if its source ownership and duplicate-capture behavior are documented first.

## DO NOT INSTALL YET

- a separate vector database
- GraphRAG infrastructure
- MCP integrations
- automatic tagging plugins
- complex autonomous-agent plugins
- overlapping PDF conversion plugins

These add operational state and write paths before the basic Markdown contract has been validated.

## Manual Setup Notes

### Templates

The verified Core Templates schema currently contains `{"folder":"templates"}`. The new templates are in `90_System/Templates/`, but this setting was deliberately not changed because `templates/독서 노트 템플릿.md` already exists. After reviewing that file, either migrate it with link checks or keep both folders and select templates manually.

### Smart Connections

The current Smart Environment uses `TaylorAI/bge-micro-v2` through the local Transformers adapter and uses Ollama for chat. A legacy `chat_completion_platform: open_router` field also exists. Do not add an OpenRouter key or enable an external fallback. Confirm the effective adapter in the plugin UI before using chat on private notes.

### Web Clipper

Web Clipper is a browser extension, so `.obsidian/` cannot prove whether it is installed. Configure it manually and keep Interpreter disabled in v1. The capture template uses only official preset variables and does not require an LLM.

## Provenance

Generated from a read-only audit of this Vault and the user's PROMPT 4 on 2026-09-22. Web Clipper behavior was checked against the official Obsidian Help pages. Human review is pending.

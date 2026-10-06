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

# Data Contract

## Scope

This contract applies to newly created or deliberately migrated managed notes. Existing notes without these properties remain valid. Automation must preserve unknown or legacy properties and must not bulk-backfill metadata without approval.

Use YAML frontmatter, lowercase property names, and snake_case values. Dates use ISO 8601. Empty values must not be fabricated.

## Properties

| Property | Type | Allowed values / format | Meaning |
| --- | --- | --- | --- |
| `type` | text | `inbox`, `project`, `area`, `source`, `concept`, `knowledge`, `idea`, `question`, `decision`, `archive`, `system`, `prompt`, `report` | Functional note class. Folder and type should agree after an approved migration. |
| `origin` | text | `me`, `external`, `ai` | Content owner and authority. Do not use a mixed value; separate different origins into linked notes. |
| `knowledge_status` | text | `raw`, `processed`, `review`, `understood`, `applied` | Knowledge maturity. Only a human may assign `understood` or `applied`. |
| `domain` | list of text | Stable lowercase terms, preferably kebab-case | Subject taxonomy, for example `[ai, knowledge-management]`. This is not a note-ownership field. |
| `created` | date | `YYYY-MM-DD` | Date the note was first created. Immutable after creation. |
| `updated` | date | `YYYY-MM-DD` | Date of the last substantive content change. Link suggestions alone do not update it. |
| `source_type` | text | `pdf`, `html`, `web`, `paper`, `book`, `video`, `dataset`, `other` | Original media or publication type for an external source. |
| `source_url` | text | Absolute `https://` or `http://` URL | Canonical source URL. Omit when no URL exists; never invent one. |
| `source_file` | text | Vault-relative path or Wikilink under `_assets/` | Preserved local source artifact, usually a PDF. Never store an absolute machine path. |
| `extraction_method` | text | `pymupdf4llm`, `pypdf` | Local extractor used to create the current PDF Source body. |
| `extraction_quality` | text | `good`, `review` | Machine quality signal. `review` means at least one extraction warning exists; it is not a human verification result. |
| `extraction_warnings` | list of text | Stable warning codes | Deduplicated quality codes such as `reading_order`, `table_layout`, `formula_layout`, `word_joining`, or `rotated_text`. Empty is valid. |
| `sources` | list of Wikilinks | Links to notes under `30_Resources/Sources/` | Evidence used by a derived or human-authored note. Link to source notes, not merely assets. |
| `human_verified` | checkbox | `true` or `false` | Whether the note's factual content and provenance were reviewed against its Sources. A person sets it by hand. Since the vault owner's decision of 2026-10-06, an AI reviewer may also set it on AI-Wiki notes, but only through `ai-wiki verify --write` and only together with `verified_by: ai`. Ingestion, scan, and apply never set it. |
| `verified_by` | text | `ai` | Present only when an AI reviewer set `human_verified: true`. Absent means a person set it. The note's `## Provenance` section names the reviewer and the date. |
| `status` | text | `active`, `paused`, `completed`, `cancelled`, `archived` | Lifecycle state for a Project or Area. This is separate from knowledge maturity. |
| `area` | Wikilink | A link to one note under `20_Areas/` | Area responsible for a Project. Leave blank when no Area applies. |
| `deadline` | date | `YYYY-MM-DD` | Optional Project deadline. Leave blank when no deadline exists. |
| `title` | text | Source title as published | Explicit title used by ingest workflows when the filename is not authoritative. |
| `author` | text or list of text | Author name or names | Source authors when known. Leave blank rather than guessing. |
| `published` | date | `YYYY-MM-DD` when known | Original publication date, distinct from capture date in `created`. |

## Required Sets

| Note class | Required properties |
| --- | --- |
| External source | `type: source`, `origin: external`, `knowledge_status: raw`, `domain`, `created`, `updated`, `source_type`, `human_verified` |
| AI Concept / AI-Wiki | `type: concept`, `origin: ai`, `knowledge_status: processed`, `domain`, `created`, `updated`, `sources`, `human_verified` |
| Human Concept / Knowledge | `type`, `origin: me`, `knowledge_status`, `domain`, `created`, `updated`, `sources`, `human_verified` |
| Project | `type: project`, `origin: me`, `status`, `area`, `created`, `updated`, `deadline` |
| Area | `type: area`, `origin: me`, `status`, `created`, `updated` |

`source_url` and `source_file` are conditionally required when those artifacts exist. `sources` may be empty only for an original human note that makes no external factual claims.

## Status Authority

- Ingestion automation may assign `raw`.
- AI processing may assign `processed` only to AI-owned notes.
- `review` means that a human-owned note awaits human review; it is not proof of understanding.
- `understood` and `applied` are human judgments.
- AI may recommend a status change in a report, but may not apply it.

## Provenance

Every AI-Wiki note must contain:

1. `origin: ai`
2. `sources` linking to the normalized source notes
3. `human_verified: false` until review. When an AI reviewer sets it to `true`, the note also carries `verified_by: ai` and a `Verification` line under `## Provenance`
4. A visible `## Provenance` section summarizing which sources support the note and identifying the local model/backend used

If a claim cannot be traced to a source, mark it explicitly as an inference in the note body or omit it.

## Example

```yaml
---
type: concept
origin: ai
knowledge_status: processed
domain:
  - knowledge-management
created: 2026-09-22
updated: 2026-09-22
sources:
  - "[[Example Source]]"
human_verified: false
---
```

## Provenance

Generated by Codex from the user's "Gangil Obsidian Knowledge OS" prompts and updated with extraction provenance on 2026-09-28. Allowed values not fixed by the prompts are initial design decisions and require human review. The `human_verified` rule and the `verified_by` property were changed by Claude Code on 2026-10-06 at the vault owner's explicit decision.

# Obsidian Knowledge OS

A personal, local-first knowledge system built on an Obsidian vault. PDFs and web pages are normalized into Markdown source notes, a self-hosted LLM turns those sources into an AI-maintained concept wiki, and a human decides what becomes their own knowledge.

The repository is the vault itself: the automation code, the governance documents that every AI agent must follow, the note templates, and a small sample of generated wiki notes.

## How it works

```text
PDF / HTML
    |
    v
Normalization to Markdown ------> 30_Resources/Sources/     external evidence, read-only for AI
    |
    v
In-memory processing view        references, checklists, broken tables, and OCR noise filtered out
    |
    v
Section-aware chunks
    |
    v
Structured extraction            self-hosted Ollama model, strict JSON schema, one concept per chunk
    |
    v
Deterministic deduplication      identity rules only; no semantic auto-merge
    |
    v
Source-level curator             may only select among existing candidates
    |
    v
Semantic quality gate            a failure blocks the whole write
    |
    v
Dry-run plan or explicit write -> 30_Resources/AI-Wiki/     AI-maintained, provenance on every claim
                                        |
                                  human review only
                                        v
                                  30_Resources/Knowledge/   human-owned
```

## Design rules

- **Ownership is separated by folder.** Sources are evidence, AI-Wiki is machine-maintained synthesis, and Knowledge belongs to the human. AI never edits Source notes, Knowledge notes, or any note with `origin: me`.
- **Dry-run is the default.** Every command plans first and writes only with an explicit flag. Nothing is ever deleted automatically.
- **Fail closed.** One technical failure or one quality-gate failure blocks the entire write and the state update. There is no partial commit, no positional fallback, and no automatic retry.
- **Loopback-only LLM.** The pipeline accepts only `localhost` endpoints. External LLM APIs, remote hosts, proxies, redirects, and cloud model names are rejected.
- **Provenance is kept.** Every AI-written note records its Source, chunk, evidence excerpt, and the model that produced it.
- **Rules before models.** Concept identity and merging are deterministic. The LLM curator can select candidates but cannot create, rename, merge, or rewrite them.

The full rule set is in [AGENTS.md](AGENTS.md) and [AI_BOUNDARIES.md](90_System/Docs/AI_BOUNDARIES.md).

## Repository layout

| Path | Contents |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Vault constitution: the invariants every agent must follow |
| [.automation/](.automation/) | Python automation: PDF ingestion, LLM provider, AI-Wiki pipeline |
| [.automation/tests/](.automation/tests/) | Unit tests; they use fake providers and never call a real model |
| [.automation/README.md](.automation/README.md) | Full specification of the pipeline and its commands |
| [90_System/Docs/](90_System/Docs/) | Architecture, data contract, AI boundaries, PARA rules, handoff notes |
| [90_System/Templates/](90_System/Templates/) | Note templates |
| [30_Resources/AI-Wiki/](30_Resources/AI-Wiki/) | Sample output: concept notes generated from "Attention Is All You Need" |
| `.obsidian/` | Obsidian settings and theme |
| `Claude outputs/` | Task prompt drafts written during design review |

### What is not in this repository

- **Source notes and PDFs.** `30_Resources/Sources/` and `_assets/PDF/` hold the full text of papers and are kept local, so they are not redistributed here. The sample AI-Wiki notes link to Sources that exist only in the local vault.
- **Processing state and diagnostics.** `.automation/state/` is local.
- **Personal notes.** The PARA folders (`00_Inbox/`, `10_Projects/`, `20_Areas/`, `40_Archives/`) and `30_Resources/Knowledge/` are part of the vault layout but contain nothing tracked.

## Quick start

Developed and tested on Windows 11 with Python 3.11. Commands run from the vault root in PowerShell.

```powershell
py -3.11 -m venv "$env:LOCALAPPDATA\GangilKnowledgeOS\.venv"
& "$env:LOCALAPPDATA\GangilKnowledgeOS\.venv\Scripts\python.exe" -m pip install -r ".automation\requirements.txt"
python -m unittest discover -s ".automation\tests"
```

Ingest a PDF into a Source note:

```powershell
python ".automation\run.py" ingest-paper "_assets\PDF\example.pdf"            # dry run
python ".automation\run.py" ingest-paper "_assets\PDF\example.pdf" --write
```

Check the model, then build wiki notes from a Source:

```powershell
python ".automation\run.py" llm-status
python ".automation\run.py" llm-test
python ".automation\run.py" ai-wiki scan --source "example.md"                # dry run
python ".automation\run.py" ai-wiki scan --source "example.md" --save-plan    # dry run, saved for review
python ".automation\run.py" ai-wiki apply --plan ".automation\state\plans\<plan>.json"           # print the notes
python ".automation\run.py" ai-wiki apply --plan ".automation\state\plans\<plan>.json" --write   # write exactly those notes
```

`scan --write` also exists; it plans and writes in one run, calling the model again.

Exit codes: `0` success, `2` ingestion or unexpected error, `3` OCR required, `4` LLM error, `5` AI-Wiki technical failure, `6` quality-gate failure.

## LLM runtime

The model endpoint is configured in [.automation/config/local_llm.json](.automation/config/local_llm.json). The committed configuration matches the author's setup:

- Ollama runs `qwen3.5:27b` on the author's own GPU server and is bound to `127.0.0.1` there.
- The desktop reaches it through an SSH local port forward at `localhost:11435`, so the pipeline still talks only to a loopback address.
- Only LLM requests cross the tunnel. Ingestion, preprocessing, chunking, deduplication, the quality gate, and file writes run on the desktop.
- The GPU is shared, so each request carries a bounded `keep_alive` and a run sends one unload request when it ends.

To use an Ollama instance on the same machine instead, set `base_url` to `http://localhost:11434`, set `model` to a model shown by `ollama list`, and remove `keep_alive` and `unload_after_run` if you do not need them. Details are in the [automation README](.automation/README.md#local-llm-provider).

## Status

This is a personal project in active development. The pipeline runs end to end, and the test suite passes without network access. When a paper describes several named mechanisms in one section, the one-concept-per-chunk limit can leave some of them without a candidate, so a recovery pass now gives each uncovered method subsection one targeted extraction call. That pass has been verified on a single paper so far. Open problems are the quality gate's title-based coverage rule, the narrow detection of method sections, and validation on more papers. The current state, the latest real dry-run, and the next planned stage are tracked in [CLAUDE_CODE_HANDOFF.md](90_System/Docs/CLAUDE_CODE_HANDOFF.md) (in Korean).

## Documentation

- [ARCHITECTURE.md](90_System/Docs/ARCHITECTURE.md): layers and information flow
- [DATA_CONTRACT.md](90_System/Docs/DATA_CONTRACT.md): note properties and their meaning
- [AI_BOUNDARIES.md](90_System/Docs/AI_BOUNDARIES.md): what AI may read, write, and suggest
- [PARA_RULES.md](90_System/Docs/PARA_RULES.md): folder semantics
- [WEB_INGEST.md](90_System/Docs/WEB_INGEST.md) and [PLUGIN_SETUP.md](90_System/Docs/PLUGIN_SETUP.md): web capture and Obsidian plugins

Most documents are in English. The handoff notes and task prompts are in Korean.

## How this project is built

The code is written by AI coding agents working under [AGENTS.md](AGENTS.md). The human owner decides what is written. The owner may delegate running the model, applying a reviewed plan, and verifying notes against their Sources to the coding agent; a note verified that way says so with `verified_by: ai`.

## License

No license has been chosen yet, so the default copyright rules apply. Note that the PDF extraction dependencies, PyMuPDF and PyMuPDF4LLM, are dual-licensed under AGPL-3.0 or a commercial license.

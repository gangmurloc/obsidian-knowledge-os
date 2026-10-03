# Knowledge OS Local Automation

This package provides local-first automation for the Vault. It currently includes PDF-to-Markdown ingestion and a localhost-only Local LLM provider layer. It does not call an external AI API.

## Environment Audit

- OS: Windows 11 Enterprise, 64-bit
- Default Python: 3.11.9
- Also installed: Python 3.14
- Initial PDF extractor: `pypdf 6.19.0`
- Current layout-aware default: `pymupdf4llm 1.28.2`
- Initial audit on 2026-09-23: Ollama was not installed or reachable.
- User-confirmed state on 2026-09-26: localhost Ollama, configured model, `llm-status`, and `llm-test` are working.

`PyMuPDF4LLM 1.28.2` is the default local extractor because it preserves page chunks, headings, multi-column reading order, and Markdown tables more reliably than plain `pypdf`. `pypdf 6.19.0` remains available as the explicit legacy extractor. `PyYAML 6.0.3` parses Obsidian frontmatter with `safe_load` so malformed YAML and property types can be rejected before Source content reaches the LLM. No extractor sends PDF content to a cloud service.

PyMuPDF4LLM installs its compatible PyMuPDF and PyMuPDF Layout dependencies. These packages are dual-licensed under AGPL-3.0 or a commercial license; review that license before distributing this automation outside personal use. Layout/OCR processing is local and can require substantially more disk space and compute than the legacy path.

## Paths

- Input: `_assets/PDF/`
- Output: `30_Resources/Sources/Papers/`
- Code: `.automation/knowledge_os/`

The output filename is a Windows-safe version of the PDF filename. Korean filenames are preserved.

## Markdown Safety Normalization

PDF extraction output is treated as untrusted plain text. Immediately before a page is inserted under `## Content`, the pipeline:

1. normalizes extractor artifacts `\<` and `\>` back to their angle-bracket characters
2. encodes `<` as `&lt;` and `>` as `&gt;`

This keeps comparisons such as `k < n` readable after Markdown rendering while preventing extracted text such as `<script>` or `<unknown` from being interpreted as raw HTML. The normalization applies only to extracted page text. YAML frontmatter, generated headings, links, and other pipeline-owned Markdown are not globally replaced.

## Install

Run these commands from the Vault root in PowerShell. The recommended virtual environment stays under local AppData so Google Drive does not sync installed packages.

```powershell
$knowledgeOsPython = "$env:LOCALAPPDATA\GangilKnowledgeOS\.venv\Scripts\python.exe"
py -3.11 -m venv "$env:LOCALAPPDATA\GangilKnowledgeOS\.venv"
& $knowledgeOsPython -m pip install --upgrade pip
& $knowledgeOsPython -m pip install -r ".automation\requirements.txt"
```

## Run

```powershell
$knowledgeOsPython = "$env:LOCALAPPDATA\GangilKnowledgeOS\.venv\Scripts\python.exe"
& $knowledgeOsPython ".automation\run.py" ingest-paper "_assets\PDF\example.pdf" --extractor pymupdf4llm --write
```

## Dry Run

Dry-run is the default. It opens and extracts the PDF, runs quality checks, and writes nothing. If the Source note already exists, dry-run compares the candidate against it and reports whether content would change. The explicit `--dry-run` flag is accepted for clarity.

```powershell
$knowledgeOsPython = "$env:LOCALAPPDATA\GangilKnowledgeOS\.venv\Scripts\python.exe"
& $knowledgeOsPython ".automation\run.py" ingest-paper "_assets\PDF\example.pdf" --extractor pymupdf4llm --dry-run
```

Use the legacy extractor only for regression comparison or a document that works better with it:

```powershell
& $knowledgeOsPython ".automation\run.py" ingest-paper "_assets\PDF\example.pdf" --extractor pypdf --dry-run
```

`--write` creates a new Source and never overwrites an existing note. After reviewing a changed dry-run, `--replace` atomically updates the matching Source while preserving custom frontmatter plus `My Highlights` and `Related`:

```powershell
& $knowledgeOsPython ".automation\run.py" ingest-paper "_assets\PDF\example.pdf" --extractor pymupdf4llm --replace
```

## Expected Output

```text
DRY RUN: G:\...\example.md (extractor=pymupdf4llm, pages=12, extracted_chars=28431, warnings=0)
```

On a real run:

```text
CREATED: G:\...\example.md (extractor=pymupdf4llm, pages=12, extracted_chars=28431, warnings=0)
```

Running the same source again does not overwrite the Markdown note:

```text
UNCHANGED: G:\...\example.md (extractor=pymupdf4llm, pages=0, extracted_chars=0, warnings=0)
```

## Failure Behavior

- Missing or invalid input exits with code `2` and logs the reason.
- Encrypted or unreadable PDFs exit with code `2` and create no note.
- Image-only or low-text PDFs exit with code `3`, log `OCR required`, and create no note.
- Filename collisions never overwrite an existing note.
- Existing matching Sources require the explicit `--replace` flag and are replaced atomically.
- Writes use a temporary file followed by an atomic replace in the destination directory.
- Extracted angle brackets are encoded only inside the PDF Content body to avoid raw-HTML parsing.
- Extraction warnings identify suspected reading-order, joined-word, table, formula, rotated-text, or extractor problems by PDF page. They request review; they do not silently discard Source content.

## Test

The tests use mocks and tiny synthetic fixtures; no user paper or large PDF fixture is read.

```powershell
python -m unittest discover -s ".automation\tests" -v
```

## Scope

Version 1 prioritizes local layout-aware extraction. PyMuPDF4LLM may use its local OCR path when available; low-text output still fails instead of creating an empty Source. Ingestion does not summarize papers, infer domains, or send content to an external API.

## Local LLM Provider

### Architecture

The provider interface is under `.automation/knowledge_os/llm/` and exposes:

- `health_check()`
- `list_models()`
- `generate()`

`OllamaProvider` is the only runtime provider in v1. `FakeLLMProvider` is deterministic and test-only, so unit tests never require Ollama or network access. Requests and responses use typed dataclasses in `llm/base.py`.

The runtime uses Python's standard-library HTTP client. No new package is required beyond the existing PDF dependency.

### Configuration

Configuration is stored at `.automation/config/local_llm.json`:

```json
{
  "provider": "ollama",
  "base_url": "http://localhost:11434",
  "model": null,
  "temperature": 0.2,
  "timeout": 60.0
}
```

Set `model` to the exact name shown by `ollama list`, including its tag. A missing model is an intentional blocking state: the CLI reports installed models and does not select or download one automatically.

Configuration contains no API key or credential. Future programmatic config writes use a same-directory temporary file, flush and sync it, then atomically replace the destination so Google Drive cannot observe a partially written file.

### Network Policy

- Only `localhost`, `127.0.0.0/8`, and `::1` endpoints are accepted.
- OpenAI, Anthropic, Gemini, OpenRouter, LAN addresses, and arbitrary internet hosts are rejected during config parsing.
- HTTP proxy use and HTTP redirects are disabled in the Ollama transport.
- Ollama model identifiers containing a `cloud` token are blocked.
- Generation first verifies that the exact model appears in the local `/api/tags` result.
- The local Ollama API requires no API key; this project does not support Ollama cloud endpoints or cloud fallback.

### Install Ollama Manually on Windows

Ollama is not currently installed. Do not install it from this automation. To enable the provider:

1. Download and run the Windows installer from [Ollama's official Windows download page](https://ollama.com/download/windows).
2. Open a new PowerShell window and confirm the executable:

   ```powershell
   ollama --version
   ```

3. Confirm the local server. If the Windows application has not started it, run it manually in a terminal:

   ```powershell
   ollama serve
   ```

4. In another terminal, inspect local models:

   ```powershell
   ollama list
   ```

5. Choose a local model deliberately from the [official Ollama model library](https://ollama.com/search), then download that exact model yourself:

   ```powershell
   ollama pull <model-name>
   ```

6. Put the exact installed name in `.automation/config/local_llm.json` under `model`.

No model is recommended or downloaded automatically by this project.

### Check Status

This command performs only local version and model-list requests. It never generates text:

```powershell
$knowledgeOsPython = "$env:LOCALAPPDATA\GangilKnowledgeOS\.venv\Scripts\python.exe"
& $knowledgeOsPython ".automation\run.py" llm-status
```

Output includes config path, provider, endpoint, reachability, server version, configured model, and installed models.

### Explicit Generation Test

`llm-test` is the only command in this phase that calls `generate()`. Run it explicitly after selecting a model:

```powershell
& $knowledgeOsPython ".automation\run.py" llm-test
```

Use an installed model once without changing config:

```powershell
& $knowledgeOsPython ".automation\run.py" llm-test --model "<installed-model-name>"
```

The response is printed to the terminal only. This command does not create AI-Wiki notes or write under `30_Resources/`.

## AI-Wiki Knowledge Processing

### Processing Boundary

The v1 processing path is:

```text
30_Resources/Sources/{Papers,Web}/*.md
  -> frontmatter validation
  -> non-destructive AI processing view
  -> section/paragraph-aware chunks
  -> localhost LLM structured JSON
  -> deterministic identity and merge plan
  -> dry-run or explicit atomic write
  -> 30_Resources/AI-Wiki/*.md
```

The processor reads normalized Markdown only. It does not reopen PDF or HTML originals. Before chunking, it builds an in-memory processing view that excludes References/Bibliography, the NeurIPS Paper Checklist, and Contents/Table of Contents sections. Section names are compared after inline Markdown, HTML entities/tags, punctuation, case, and whitespace normalization. Exclusion ends only at the next heading of the same or higher level. Appendices, Related Work, Limitations, Experiment, Methodology, normal prose, figure captions, and structurally valid GFM tables remain available.

Malformed tables, excessive numeric-density rows, raw picture/OCR text, probable joined-word OCR blocks, flattened formulas, and a missing formula after an explicit formula-introducing sentence become page-linked omission markers. These markers tell the LLM not to reconstruct missing content. Filtering never writes the processing view back to the Source Markdown.

It never writes Sources, Knowledge, Projects, Areas, Ideas, Decisions, or notes with `origin: me`. It never assigns `understood`, `applied`, or `human_verified: true`.

Each AI-Wiki note uses `origin: ai`, `knowledge_status: processed`, `human_verified: false`, a `sources` Wikilink list, visible `## Sources`, and visible `## Provenance`. Existing valid provenance is retained when another Source supports or extends a concept.

### Structured Extraction

Concept extraction passes a strict JSON schema through Ollama's `format` field and sends `think: false` with `temperature: 0`, regardless of the global generation temperature. Each extraction and repair request also sets Ollama `num_predict` to 1,024 through the provider's `max_output_tokens` option so a runaway structured response cannot consume the entire timeout indefinitely. Reasoning output is neither requested nor stored. Unknown fields, missing fields, invalid titles, and oversized values are rejected. Raw model values cannot directly control filenames, YAML, or Wikilinks.

If the first response is syntactically invalid JSON, the same localhost model receives one syntax-only repair request. The repair prompt prohibits adding, removing, summarizing, or reinterpreting content and also uses `think: false`, `temperature: 0`, and the original JSON schema. The repaired value must pass the complete existing schema validator. There is no second retry.

An initial JSON syntax failure writes one diagnostic JSON artifact under `.automation/state/diagnostics/`, whether repair succeeds or fails. It contains a UTC timestamp, Vault-relative Source path, chunk ID, model, parse error, and the raw structured responses. It does not contain the Source body, credentials, absolute paths, or Ollama's separate thinking field. Any embedded `<think>` block is redacted before storage. Normal successful responses and valid-but-schema-invalid responses create no diagnostic.

The processing view is split at section and paragraph boundaries before sentence or fixed-length fallback splitting. The default maximum is 4,000 characters with up to 200 characters of whole-paragraph overlap. Chunk size and overlap are defined once in `ai_wiki/source.py`. State stores the processing-view version, Source SHA-256 hashes, chunk identifiers, and normalized concept identities under `.automation/state/ai_wiki.json`; Source Markdown remains authoritative.

Each chunk returns at most one central concept candidate. This keeps the structured record within the 1,024-token output budget on small local models. Each candidate also has one selection-only `role`: `core_concept`, `mechanism`, `component`, `method_entity`, `dataset`, `metric`, `baseline`, or `analysis`. The role is not persisted to AI-Wiki Markdown. Per concept, v1 permits at most 5 key points, 5 related concepts, 3 evidence items, 3 open questions, and 3 domains. Deterministic identity deduplication followed by source-level selection keeps at most 12 final concepts. The configured 180-second timeout is retained; timeout does not trigger an automatic retry. An Ollama `done_reason` of `length` is reported as truncation and does not trigger syntax repair because missing content cannot be repaired safely.

### Source-Level Concept Selection

Chunk extraction prioritizes explicitly named mechanisms, architecture components, and reusable concepts with their own definition or process. `core_concept`, `mechanism`, and `component` are kept by default; `method_entity` is conservative. `dataset`, `metric`, `baseline`, and `analysis` are normally excluded before curation. A dataset or metric is retained when its identity is clearly derived from the Source title, allowing papers that introduce those artifacts to represent their actual contribution. An exact or near-exact Source-title alias can be marked internally as the primary Source entity; this flag is not a Markdown property. A branded title with additional meaningful mechanism content is not collapsed into that entity.

The processing view detects named subsections below core Method, Methodology, Approach, or Architecture sections using Markdown and numbered-heading hierarchy. These names are weak supervision: only a candidate supported by matching chunk content can receive mechanism priority. Experiment, dataset, evaluation, implementation, result, ablation, analysis, and hyperparameter subsections are not method signals, and headings never create concepts by themselves.

After deterministic identity deduplication, a Source invokes the curator when it has more than 12 candidates, a deterministic duplicate-risk group, excessive Source-entity dominance, or explicit-method coverage failure. Duplicate risk is a review signal based on coexisting titles that become equal only after contextual wrapper comparison or comparison with aliases derived from the Source title. Wrapper words are never removed from stored identities or singleton candidates, and aliases are never used for renaming or automatic merging. A triggered Source makes exactly one curator request with `think: false` and `temperature: 0`. The request contains only candidate titles, roles, the primary-entity flag, shortened definitions and core ideas, supporting chunk IDs, available section names, evidence counts, method subsection signals, and duplicate-risk groups; it does not resend the Source body.

The curator may select up to 12 exact identities and provide a short reason. For a clear contextual alias group it should retain one representative, but when identity is uncertain it may keep candidates separate. A broad concept and a named subprocess, a base mechanism and a qualified variant, or mechanisms sharing only a domain word remain distinct. The curator cannot create, rename, merge, or modify concepts. Unknown identities, duplicate selections, more than 12 selections, malformed JSON, schema violations, truncation, and timeout fail that Source without selecting the first 12 or applying another fallback. Existing deterministic identity normalization remains the only automatic merge rule, and selected Concept objects retain their original evidence and provenance.

### Semantic Quality Gate

Technical failures and semantic quality failures are reported separately. After curation, the quality gate checks excessive Source-entity dominance, multiple selected primary entities, unresolved duplicate-risk groups, explicit method structures with no matching mechanism/component selected, and selections containing only generic Source-name entities. Mechanism coverage is required only when at least two named subsections were detected under a core method section; surveys, benchmark papers, dataset papers, and empirical analyses do not fail merely because they contain no mechanism.

The report prints `quality_gate.status` as `pass`, `warning`, or `failed` plus Source-scoped reasons. A failed gate blocks the entire `--write` operation before any AI-Wiki note or processing state is written and exits with code `6`. Provider, timeout, malformed JSON, and curator errors remain technical failures, exit with code `5`, and also block the entire write rather than allowing a partial multi-Source commit.

### Ontology Normalization

Concept identity is deterministic and local. It applies Unicode NFKC normalization, case folding, punctuation and hyphen normalization, repeated-whitespace normalization, and conservative removal of a leading English article (`a`, `an`, or `the`). Exact normalized identities merge; lexical overlap alone never merges concepts.

Canonical titles remove a leading English article and normalize established forms such as `Self-Attention`, `Multi-Head Attention`, `Scaled Dot-Product Attention`, and `Feed-Forward`. No additional LLM call is used. A candidate is excluded when its complete normalized title matches the Source title or is a generic document heading such as `Introduction`, `Results`, `Discussion`, `Conclusion`, `Table N`, `Figure N`, or `Section N`. Partial Source-title overlap is not sufficient for exclusion.

Distinct candidates with conservative title overlap remain separate. The dry-run may report `narrower_than` or `related_to` under `relation_suggestions`, but these suggestions do not create Wikilinks, modify note bodies, or persist ontology edges.

### Dry-Run Commands

Dry-run is the default and writes neither AI-Wiki notes nor processing state. A JSON syntax failure is the sole exception: it writes a diagnostic artifact under `.automation/state/diagnostics/` so the malformed local response can be inspected.

```powershell
python ".automation\run.py" ai-wiki scan --source "attention_is_all_you_need.md"
python ".automation\run.py" ai-wiki scan --papers
python ".automation\run.py" ai-wiki scan --web
python ".automation\run.py" ai-wiki scan --all
python ".automation\run.py" ai-wiki scan --changed
```

The plan reports processed and skipped Sources, new concepts, updates with `supports`, `extends`, or `contradicts` relation, unchanged concepts, non-writing ontology relation suggestions, removed Sources, warnings, and failures. Processing diagnostics list included and excluded sections, named methodology subsections, included block count, excluded tables, excluded figure text, formula warnings, Source and processing character counts, and chunk count. Concept-selection diagnostics list all candidates, selected and dropped concepts, duplicate-risk groups, curator trigger reasons, selected representatives, dropped aliases, curator call count, and quality-gate status. An unchanged Source still receives local preprocessing diagnostics but does not call the LLM. Removed Sources are report-only and never cause AI-Wiki deletion.

### Explicit Write

Add `--write` only after reviewing the dry-run:

```powershell
python ".automation\run.py" ai-wiki scan --source "attention_is_all_you_need.md" --write
```

AI-Wiki and state files use a same-directory temporary file, flush, `fsync`, and atomic replace. A failure cannot expose partial Markdown and does not delete the previous note.

Related concepts link only when the target concept already exists or is part of the current accepted plan. Other names remain plain `(suggested)` text and do not trigger recursive generation.

### Known Limitations

- Concept identity handles deterministic article, case, punctuation, whitespace, and hyphen variants; it does not perform semantic ontology matching.
- `supports`, `extends`, and `contradicts` comparison is conservative and lexical. Subtle contradictions remain warnings for human review rather than triggering automatic replacement.
- Extraction is limited to 1 concept per chunk and 12 selected concepts per Source; Sources with more candidates depend on one local curator call.
- The schema asks each concept for ten fields, including the selection role and nested evidence. Small local models can still produce malformed JSON as output length and string escaping complexity increase; v1 uses one syntax-only repair attempt.
- Layout heuristics are conservative but cannot guarantee correct reading order, tables, or formulas for every publisher PDF. Review extraction warnings and the dry-run before replacement.
- v1 does not write the optional processing report, classify PARA notes, or delete stale AI-Wiki content.

## Ollama API References

- [Ollama API](https://docs.ollama.com/api)
- [Ollama API source documentation](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [Ollama Windows download](https://ollama.com/download/windows)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama thinking controls](https://docs.ollama.com/capabilities/thinking)

## References

- [pypdf installation](https://pypdf.readthedocs.io/en/stable/user/installation.html)
- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)
- [pypdf on PyPI](https://pypi.org/project/pypdf/)
- [PyMuPDF4LLM documentation](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/)
- [PyMuPDF4LLM on PyPI](https://pypi.org/project/pymupdf4llm/)
- [PyYAML on PyPI](https://pypi.org/project/PyYAML/)

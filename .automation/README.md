# Knowledge OS Local Automation

This package provides local-first automation for the Vault. It currently includes PDF-to-Markdown ingestion and a localhost-only Local LLM provider layer. It does not call an external AI API.

## Environment Audit

- OS: Windows 11 Enterprise, 64-bit
- Default Python: 3.11.9
- Also installed: Python 3.14
- Existing PDF extraction package: none found before implementation
- Existing PDF-to-Markdown plugin or script: none found
- Initial audit on 2026-09-23: Ollama was not installed or reachable.
- User-confirmed state on 2026-09-26: localhost Ollama, configured model, `llm-status`, and `llm-test` are working.

`pypdf 6.19.0` handles local PDF text extraction. `PyYAML 6.0.3` parses Obsidian frontmatter with `safe_load` so malformed YAML and property types can be rejected before Source content reaches the LLM. Neither package uses a cloud service. Image-only PDFs stop with `OCR required` and do not create an empty note.

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
& $knowledgeOsPython ".automation\run.py" ingest-paper "_assets\PDF\example.pdf" --write
```

## Dry Run

Dry-run is the default. It still opens and extracts the PDF so it can detect image-only files, but it writes nothing. The explicit `--dry-run` flag is accepted for clarity.

```powershell
$knowledgeOsPython = "$env:LOCALAPPDATA\GangilKnowledgeOS\.venv\Scripts\python.exe"
& $knowledgeOsPython ".automation\run.py" ingest-paper "_assets\PDF\example.pdf" --dry-run
```

## Expected Output

```text
DRY RUN: G:\...\30_Resources\Sources\Papers\example.md (pages=12, extracted_chars=28431)
```

On a real run:

```text
CREATED: G:\...\30_Resources\Sources\Papers\example.md (pages=12, extracted_chars=28431)
```

Running the same source again does not overwrite the Markdown note:

```text
UNCHANGED: G:\...\30_Resources\Sources\Papers\example.md (pages=0, extracted_chars=0)
```

## Failure Behavior

- Missing or invalid input exits with code `2` and logs the reason.
- Encrypted or unreadable PDFs exit with code `2` and create no note.
- Image-only or low-text PDFs exit with code `3`, log `OCR required`, and create no note.
- Filename collisions never overwrite an existing note.
- Writes use a temporary file followed by an atomic replace in the destination directory.
- Extracted angle brackets are encoded only inside the PDF Content body to avoid raw-HTML parsing.

## Test

The tests use mocks and a tiny fake PDF marker; no large PDF fixture is stored.

```powershell
python -m unittest discover -s ".automation\tests" -v
```

## Scope

Version 1 supports PDFs with an existing text layer. It does not perform OCR, summarize papers, infer domains, or send content to an external API.

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
  -> section/paragraph-aware chunks
  -> localhost LLM structured JSON
  -> deterministic identity and merge plan
  -> dry-run or explicit atomic write
  -> 30_Resources/AI-Wiki/*.md
```

The processor reads normalized Markdown only. It does not reopen PDF or HTML originals. It never writes Sources, Knowledge, Projects, Areas, Ideas, Decisions, or notes with `origin: me`. It never assigns `understood`, `applied`, or `human_verified: true`.

Each AI-Wiki note uses `origin: ai`, `knowledge_status: processed`, `human_verified: false`, a `sources` Wikilink list, visible `## Sources`, and visible `## Provenance`. Existing valid provenance is retained when another Source supports or extends a concept.

### Structured Extraction

Concept extraction passes a strict JSON schema through Ollama's `format` field and sends `think: false` with `temperature: 0`, regardless of the global generation temperature. Each extraction and repair request also sets Ollama `num_predict` to 1,024 through the provider's `max_output_tokens` option so a runaway structured response cannot consume the entire timeout indefinitely. Reasoning output is neither requested nor stored. Unknown fields, missing fields, invalid titles, and oversized values are rejected. Raw model values cannot directly control filenames, YAML, or Wikilinks.

If the first response is syntactically invalid JSON, the same localhost model receives one syntax-only repair request. The repair prompt prohibits adding, removing, summarizing, or reinterpreting content and also uses `think: false`, `temperature: 0`, and the original JSON schema. The repaired value must pass the complete existing schema validator. There is no second retry.

An initial JSON syntax failure writes one diagnostic JSON artifact under `.automation/state/diagnostics/`, whether repair succeeds or fails. It contains a UTC timestamp, Vault-relative Source path, chunk ID, model, parse error, and the raw structured responses. It does not contain the Source body, credentials, absolute paths, or Ollama's separate thinking field. Any embedded `<think>` block is redacted before storage. Normal successful responses and valid-but-schema-invalid responses create no diagnostic.

Source content is split at section and paragraph boundaries before sentence or fixed-length fallback splitting. The default maximum is 4,000 characters with up to 200 characters of whole-paragraph overlap. Chunk size and overlap are defined once in `ai_wiki/source.py`. State stores only Source SHA-256 hashes, chunk identifiers, and normalized concept identities under `.automation/state/ai_wiki.json`; Source Markdown remains authoritative.

Each chunk returns at most one central concept candidate. This keeps the nine-field structured record within the 1,024-token output budget on small local models. Per concept, v1 permits at most 5 key points, 5 related concepts, 3 evidence items, 3 open questions, and 3 domains. Source-level merge and deduplication still enforce at most 12 unique concepts. The configured 180-second timeout is retained; timeout does not trigger an automatic retry. An Ollama `done_reason` of `length` is reported as truncation and does not trigger syntax repair because missing content cannot be repaired safely.

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

The plan reports processed and skipped Sources, new concepts, updates with `supports`, `extends`, or `contradicts` relation, unchanged concepts, non-writing ontology relation suggestions, removed Sources, warnings, and failures. It also prints Source characters, chunk count, average and maximum chunk size, LLM calls, JSON repairs, and timeout failures. Removed Sources are report-only and never cause AI-Wiki deletion.

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
- Extraction is limited to 1 concept per chunk and 12 unique concepts per Source.
- The schema asks each concept for nine fields, including nested evidence. Small local models can still produce malformed JSON as output length and string escaping complexity increase; v1 keeps the schema unchanged and uses one syntax-only repair attempt.
- v1 does not write the optional processing report, perform OCR, classify PARA notes, or delete stale AI-Wiki content.

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
- [PyYAML on PyPI](https://pypi.org/project/PyYAML/)

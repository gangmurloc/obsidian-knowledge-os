# Knowledge OS Local Automation

This package provides local-first automation for the Vault. It currently includes PDF-to-Markdown ingestion and a localhost-only Local LLM provider layer. It does not call an external AI API.

## Environment Audit

- OS: Windows 11 Enterprise, 64-bit
- Default Python: 3.11.9
- Also installed: Python 3.14
- Existing PDF extraction package: none found before implementation
- Existing PDF-to-Markdown plugin or script: none found
- Ollama executable: not found on 2026-09-23
- Ollama server at `http://localhost:11434`: not reachable on 2026-09-23
- Installed Ollama models: unavailable because Ollama is not installed/running

`pypdf 6.19.0` was selected because it is a maintained, production-stable, pure-Python package, supports Python 3.11, and can extract text and metadata without a cloud service. It is not OCR software. Image-only PDFs stop with `OCR required` and do not create an empty note.

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

### Ollama API References

- [Ollama API](https://docs.ollama.com/api)
- [Ollama API source documentation](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [Ollama Windows download](https://ollama.com/download/windows)

## References

- [pypdf installation](https://pypdf.readthedocs.io/en/stable/user/installation.html)
- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)
- [pypdf on PyPI](https://pypi.org/project/pypdf/)

# Local PDF to Markdown Pipeline

This pipeline converts text-layer academic PDFs into Obsidian-friendly Markdown without modifying the original PDF or calling an external service.

## Environment Audit

- OS: Windows 11 Enterprise, 64-bit
- Default Python: 3.11.9
- Also installed: Python 3.14
- Existing PDF extraction package: none found before implementation
- Existing PDF-to-Markdown plugin or script: none found

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

## References

- [pypdf installation](https://pypdf.readthedocs.io/en/stable/user/installation.html)
- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)
- [pypdf on PyPI](https://pypi.org/project/pypdf/)

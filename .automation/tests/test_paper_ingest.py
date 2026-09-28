from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from html import unescape
from pathlib import Path
from unittest.mock import patch

import yaml
import pymupdf

AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))

from knowledge_os.paper_ingest import (  # noqa: E402
    FRONTMATTER_PATTERN,
    OCRRequiredError,
    OutputCollisionError,
    ingest_paper,
    normalize_extracted_text_for_markdown,
    sanitize_filename,
)
from knowledge_os.pdf_extractors import (  # noqa: E402
    ExtractedPaper,
    ExtractionWarning,
    extract_pdf,
)


class FakeMetadata:
    title = "Test Paper"


class FakePage:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self, **_kwargs):
        return self.text


class FakeReader:
    is_encrypted = False
    metadata = FakeMetadata()

    def __init__(self, texts: list[str]):
        self.pages = [FakePage(text) for text in texts]


class PaperIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_directory.name)
        self.pdf_directory = self.vault / "_assets" / "PDF"
        self.output_directory = self.vault / "30_Resources" / "Sources" / "Papers"
        self.pdf_directory.mkdir(parents=True)
        self.output_directory.mkdir(parents=True)
        self.pdf = self.pdf_directory / "test-paper.pdf"
        self.pdf.write_bytes(b"%PDF-test-fixture")

    def tearDown(self):
        self.temp_directory.cleanup()

    def _paper(
        self,
        text: str = "Extracted paper text. " * 20,
        *,
        extractor: str = "pymupdf4llm",
        warnings: tuple[ExtractionWarning, ...] = (),
    ) -> ExtractedPaper:
        return ExtractedPaper(
            title="Test Paper",
            page_texts=(text,),
            extracted_chars=len(text.replace(" ", "")),
            extractor=extractor,
            warnings=warnings,
        )

    def _metadata(self, path: Path) -> dict:
        text = path.read_text(encoding="utf-8")
        match = FRONTMATTER_PATTERN.match(text)
        self.assertIsNotNone(match)
        return yaml.safe_load(match.group("yaml"))

    def test_sanitize_filename_preserves_korean_and_removes_invalid_characters(self):
        self.assertEqual(sanitize_filename(' 한국어 논문:* '), "한국어 논문")
        self.assertEqual(sanitize_filename("CON"), "_CON")

    def test_normalize_extracted_text_handles_comparisons_and_edge_cases(self):
        source = "\n".join(
            ["a < b", "x > y", "O(n/k)", r"\<unknown", "normal English paragraph"]
        )
        normalized = normalize_extracted_text_for_markdown(source)
        self.assertEqual(
            normalized,
            "\n".join(
                ["a &lt; b", "x &gt; y", "O(n/k)", "&lt;unknown", "normal English paragraph"]
            ),
        )

    @patch("knowledge_os.paper_ingest.extract_pdf")
    def test_dry_run_extracts_but_does_not_write(self, extract):
        extract.return_value = self._paper()
        result = ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=True)
        self.assertEqual(result.status, "dry-run")
        self.assertEqual(result.extractor, "pymupdf4llm")
        self.assertFalse(result.output_path.exists())

    @patch("knowledge_os.paper_ingest.extract_pdf")
    def test_create_records_extractor_pages_table_and_quality(self, extract):
        extract.return_value = ExtractedPaper(
            title="Test Paper",
            page_texts=(
                "# Introduction\n\n| Method | Score |\n| --- | --- |\n| A | 1 |",
                "Second page text. " * 10,
            ),
            extracted_chars=180,
            extractor="pymupdf4llm",
            warnings=(ExtractionWarning("reading_order", 2, "review this page"),),
        )
        result = ingest_paper(
            pdf_argument=self.pdf,
            vault_root=self.vault,
            dry_run=False,
            today=date(2026, 9, 28),
        )
        content = result.output_path.read_text(encoding="utf-8")
        metadata = self._metadata(result.output_path)
        self.assertEqual(result.status, "created")
        self.assertEqual(metadata["extraction_method"], "pymupdf4llm")
        self.assertEqual(metadata["extraction_quality"], "review")
        self.assertEqual(metadata["extraction_warnings"], ["reading_order"])
        self.assertIn("### Page 1", content)
        self.assertIn("### Page 2", content)
        self.assertIn("| Method | Score |", content)
        self.assertIn("#### Introduction", content)

    @patch("knowledge_os.paper_ingest.extract_pdf")
    def test_write_never_overwrites_existing_source(self, extract):
        extract.return_value = self._paper("Original extraction. " * 20)
        first = ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=False)
        before = first.output_path.read_text(encoding="utf-8")
        extract.return_value = self._paper("Changed extraction. " * 20)
        second = ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=False)
        self.assertEqual(second.status, "exists")
        self.assertEqual(first.output_path.read_text(encoding="utf-8"), before)
        self.assertEqual(extract.call_count, 1)

    @patch("knowledge_os.paper_ingest.extract_pdf")
    def test_existing_dry_run_compares_without_writing(self, extract):
        extract.return_value = self._paper("Original extraction. " * 20)
        created = ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=False)
        before = created.output_path.read_text(encoding="utf-8")
        extract.return_value = self._paper("Improved extraction. " * 20)
        compared = ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=True)
        self.assertEqual(compared.status, "dry-run-change")
        self.assertTrue(compared.content_changed)
        self.assertEqual(created.output_path.read_text(encoding="utf-8"), before)

    @patch("knowledge_os.paper_ingest.extract_pdf")
    def test_replace_preserves_human_sections_and_custom_metadata(self, extract):
        extract.return_value = self._paper("Original extraction. " * 20)
        created = ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=False)
        text = created.output_path.read_text(encoding="utf-8")
        text = text.replace("human_verified: false", "human_verified: true\nreviewer: Gil")
        text = text.replace("## My Highlights\n\n", "## My Highlights\n\nKeep this insight.\n\n")
        text = text.replace("## Related\n\n", "## Related\n\n[[Human Note]]\n")
        created.output_path.write_text(text, encoding="utf-8")

        extract.return_value = self._paper("Improved extraction. " * 20)
        result = ingest_paper(
            pdf_argument=self.pdf,
            vault_root=self.vault,
            dry_run=False,
            replace=True,
            today=date(2026, 9, 28),
        )
        replaced = result.output_path.read_text(encoding="utf-8")
        metadata = self._metadata(result.output_path)
        self.assertEqual(result.status, "replaced")
        self.assertIn("Improved extraction", replaced)
        self.assertIn("Keep this insight.", replaced)
        self.assertIn("[[Human Note]]", replaced)
        self.assertEqual(metadata["reviewer"], "Gil")
        self.assertTrue(metadata["human_verified"])

    @patch("knowledge_os.paper_ingest.extract_pdf")
    def test_extracted_comparison_cannot_be_parsed_as_html(self, extract):
        text = (
            r"A single convolutional layer with kernel width k\<n does not connect all pairs. "
            + "normal English paragraph " * 4
        )
        extract.return_value = self._paper(text)
        result = ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=False)
        markdown = result.output_path.read_text(encoding="utf-8")
        self.assertIn("kernel width k&lt;n does not connect", markdown)
        self.assertIn("kernel width k<n does not connect", unescape(markdown))

    @patch("knowledge_os.paper_ingest.extract_pdf")
    def test_low_text_pdf_reports_ocr_required_without_output(self, extract):
        extract.return_value = ExtractedPaper(
            title=None, page_texts=(" ",), extracted_chars=0, extractor="pymupdf4llm"
        )
        with self.assertRaises(OCRRequiredError):
            ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=False)
        self.assertEqual(list(self.output_directory.glob("*.md")), [])

    def test_existing_note_for_another_source_is_not_overwritten(self):
        output = self.output_directory / "test-paper.md"
        original = "---\nsource_file: _assets/PDF/another.pdf\n---\n"
        output.write_text(original, encoding="utf-8")
        with self.assertRaises(OutputCollisionError):
            ingest_paper(pdf_argument=self.pdf, vault_root=self.vault)
        self.assertEqual(output.read_text(encoding="utf-8"), original)

    def test_legacy_pypdf_extractor_remains_available(self):
        reader = FakeReader(["Legacy text extraction. " * 10])
        with patch("knowledge_os.pdf_extractors._open_pypdf_reader", return_value=reader):
            paper = extract_pdf(self.pdf, extractor="pypdf")
        self.assertEqual(paper.extractor, "pypdf")
        self.assertEqual(len(paper.page_texts), 1)
        self.assertIn("Legacy text extraction", paper.page_texts[0])

    def test_pymupdf4llm_page_chunks_preserve_layout_order(self):
        chunks = [
            {
                "metadata": {"page_number": 1, "title": "Layout Paper"},
                "text": "Left column first.\n\nRight column second.\n\n| A | B |\n| --- | --- |\n| 1 | 2 |",
            },
            {"metadata": {"page_number": 2}, "text": "Second page."},
        ]
        with patch("knowledge_os.pdf_extractors._load_pymupdf4llm") as load:
            load.return_value.to_markdown.return_value = chunks
            paper = extract_pdf(self.pdf, extractor="pymupdf4llm")
        self.assertEqual(paper.title, "Layout Paper")
        self.assertEqual(len(paper.page_texts), 2)
        self.assertLess(paper.page_texts[0].index("Left column"), paper.page_texts[0].index("Right column"))
        self.assertIn("| --- | --- |", paper.page_texts[0])

    def test_real_layout_fixture_reads_left_column_before_right_column(self):
        fixture = self.pdf_directory / "two-columns.pdf"
        document = pymupdf.open()
        page = document.new_page(width=612, height=792)
        left = "LEFT COLUMN START\n" + "\n".join(
            f"Left sentence {index} has enough words for layout analysis."
            for index in range(1, 12)
        )
        right = "RIGHT COLUMN START\n" + "\n".join(
            f"Right sentence {index} has enough words for layout analysis."
            for index in range(1, 12)
        )
        page.insert_textbox(pymupdf.Rect(36, 72, 286, 700), left, fontsize=9)
        page.insert_textbox(pymupdf.Rect(326, 72, 576, 700), right, fontsize=9)
        document.save(fixture)
        document.close()

        paper = extract_pdf(fixture, extractor="pymupdf4llm")
        self.assertEqual(len(paper.page_texts), 1)
        self.assertLess(
            paper.page_texts[0].index("LEFT COLUMN START"),
            paper.page_texts[0].index("RIGHT COLUMN START"),
        )


if __name__ == "__main__":
    unittest.main()

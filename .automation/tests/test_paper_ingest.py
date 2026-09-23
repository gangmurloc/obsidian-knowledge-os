from __future__ import annotations

import sys
import tempfile
import unittest
from html import unescape
from datetime import date
from pathlib import Path
from unittest.mock import patch


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))

from knowledge_os.paper_ingest import (  # noqa: E402
    OCRRequiredError,
    OutputCollisionError,
    ingest_paper,
    normalize_extracted_text_for_markdown,
    sanitize_filename,
)


class FakeMetadata:
    title = "한국어 테스트 논문"


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
        self.pdf = self.pdf_directory / "한국어 논문.pdf"
        self.pdf.write_bytes(b"%PDF-test-fixture")

    def tearDown(self):
        self.temp_directory.cleanup()

    def _reader(self, text: str = "충분한 텍스트 " * 30) -> FakeReader:
        return FakeReader([text])

    def test_sanitize_filename_preserves_korean_and_removes_invalid_characters(self):
        self.assertEqual(sanitize_filename(' 한국어: 논문?* '), "한국어 논문")
        self.assertEqual(sanitize_filename("CON"), "_CON")

    def test_normalize_extracted_text_handles_comparisons_and_edge_cases(self):
        source = "\n".join(
            [
                "a < b",
                "x > y",
                "O(n/k)",
                r"\<unknown",
                "normal English paragraph",
            ]
        )
        normalized = normalize_extracted_text_for_markdown(source)
        self.assertEqual(
            normalized,
            "\n".join(
                [
                    "a &lt; b",
                    "x &gt; y",
                    "O(n/k)",
                    "&lt;unknown",
                    "normal English paragraph",
                ]
            ),
        )

    def test_normalize_extracted_text_encodes_raw_html_only(self):
        source = "# Heading\n**bold** and [link](https://example.com)\n<script>alert(1)</script>"
        normalized = normalize_extracted_text_for_markdown(source)
        self.assertIn("# Heading", normalized)
        self.assertIn("**bold** and [link](https://example.com)", normalized)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", normalized)
        self.assertNotIn("<script>", normalized)

    @patch("knowledge_os.paper_ingest._open_reader")
    def test_dry_run_extracts_but_does_not_write(self, open_reader):
        open_reader.return_value = self._reader()
        result = ingest_paper(
            pdf_argument=Path("_assets/PDF/한국어 논문.pdf"),
            vault_root=self.vault,
            dry_run=True,
            today=date(2026, 9, 22),
        )
        self.assertEqual(result.status, "dry-run")
        self.assertFalse(result.output_path.exists())

    @patch("knowledge_os.paper_ingest._open_reader")
    def test_create_is_utf8_and_second_run_is_idempotent(self, open_reader):
        open_reader.return_value = self._reader()
        first = ingest_paper(
            pdf_argument=self.pdf,
            vault_root=self.vault,
            dry_run=False,
            today=date(2026, 9, 22),
        )
        self.assertEqual(first.status, "created")
        content = first.output_path.read_text(encoding="utf-8")
        self.assertIn("# 한국어 테스트 논문", content)
        self.assertIn('source_file: "_assets/PDF/한국어 논문.pdf"', content)
        self.assertIn("knowledge_status: raw", content)

        second = ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=False)
        self.assertEqual(second.status, "exists")
        self.assertEqual(first.output_path.read_text(encoding="utf-8"), content)

    @patch("knowledge_os.paper_ingest._open_reader")
    def test_extracted_comparison_cannot_be_parsed_as_html(self, open_reader):
        regression_text = (
            r"A single convolutional layer with kernel width k\<n does not connect all pairs. "
            + "normal English paragraph " * 4
        )
        open_reader.return_value = self._reader(regression_text)

        result = ingest_paper(
            pdf_argument=self.pdf,
            vault_root=self.vault,
            dry_run=False,
            today=date(2026, 9, 23),
        )
        markdown = result.output_path.read_text(encoding="utf-8")

        self.assertIn("kernel width k&lt;n does not connect", markdown)
        self.assertNotIn(r"k\&lt;n", markdown)
        self.assertNotIn("k<n", markdown)
        self.assertIn("kernel width k<n does not connect", unescape(markdown))
        self.assertIn("---\ntype: source", markdown)
        self.assertIn("## Content\n\n### Page 1", markdown)

    @patch("knowledge_os.paper_ingest._open_reader")
    def test_image_only_pdf_reports_ocr_required_without_output(self, open_reader):
        open_reader.return_value = self._reader("  ")
        with self.assertRaises(OCRRequiredError):
            ingest_paper(pdf_argument=self.pdf, vault_root=self.vault, dry_run=False)
        self.assertEqual(list(self.output_directory.glob("*.md")), [])

    def test_existing_note_for_another_source_is_not_overwritten(self):
        output = self.output_directory / "한국어 논문.md"
        original = '---\nsource_file: "_assets/PDF/다른 논문.pdf"\n---\n'
        output.write_text(original, encoding="utf-8")
        with self.assertRaises(OutputCollisionError):
            ingest_paper(pdf_argument=self.pdf, vault_root=self.vault)
        self.assertEqual(output.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()

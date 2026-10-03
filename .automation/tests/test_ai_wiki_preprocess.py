from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))

from knowledge_os.ai_wiki.preprocess import (  # noqa: E402
    build_ai_processing_view,
    canonicalize_heading_text,
    detect_methodology_subsections,
)
from knowledge_os.ai_wiki.models import ProcessingPlan  # noqa: E402
from knowledge_os.cli import _print_ai_wiki_plan  # noqa: E402


class AIWikiPreprocessTests(unittest.TestCase):
    def test_named_methodology_subsections_are_detected(self):
        content = (
            "### Page 1\n\n#### 3 Methodology\n\n"
            "##### 3.1 State Construction\n\nDefined mechanism.\n\n"
            "##### 3.2 Dynamic Routing\n\nDefined mechanism.\n\n"
            "#### 4 Results\n\nResult text."
        )
        self.assertEqual(
            detect_methodology_subsections(content),
            ("state construction", "dynamic routing"),
        )

    def test_flattened_numbered_methodology_hierarchy_is_detected(self):
        content = (
            "### Page 1\n\n#### 3 Methodolodgy\n\n"
            "#### 3.1 State Construction\n\nDefined mechanism.\n\n"
            "#### 3.2 Dynamic Routing\n\nDefined mechanism.\n\n"
            "#### 4 Experiment\n\nExperiment text."
        )
        self.assertEqual(
            detect_methodology_subsections(content),
            ("state construction", "dynamic routing"),
        )

    def test_experiment_subsections_are_not_methodology_signals(self):
        content = (
            "### Page 1\n\n#### 4 Experiment\n\n"
            "##### 4.1 Dataset and Evaluation\n\nDataset text.\n\n"
            "##### 4.2 Implementation Details\n\nImplementation text."
        )
        self.assertEqual(detect_methodology_subsections(content), ())

    def test_heading_canonicalization_removes_inline_formatting(self):
        cases = {
            "**References**": "references",
            "__References__": "references",
            "*References*": "references",
            "_References_": "references",
            "`NeurIPS Paper Checklist`": "neurips paper checklist",
            "&lt;strong&gt;Table of Contents&lt;/strong&gt;": "table of contents",
            "6. References:": "references",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(canonicalize_heading_text(value), expected)

    def test_formatted_reference_headings_are_excluded(self):
        for heading in (
            "**References**",
            "__References__",
            "`References`",
            "&lt;strong&gt;References&lt;/strong&gt;",
        ):
            with self.subTest(heading=heading):
                content = (
                    f"### Page 1\n\n#### {heading}\n\n[1] Citation.\n\n"
                    "#### Related Work\n\nKept material."
                )
                view = build_ai_processing_view(content)
                self.assertNotIn("[1] Citation.", view.content)
                self.assertIn("Related Work", view.content)
                self.assertIn("Kept material.", view.content)
                self.assertTrue(any("references" in item for item in view.excluded_sections))

    def test_formatted_contents_heading_is_excluded(self):
        content = (
            "### Page 2\n\n#### **Contents**\n\nIntroduction 1\nMethod 2\n\n"
            "#### Appendix\n\nAppendix content."
        )
        view = build_ai_processing_view(content)
        self.assertNotIn("Introduction 1", view.content)
        self.assertIn("Appendix content.", view.content)
        self.assertTrue(any("contents" in item for item in view.excluded_sections))

    def test_formatted_checklist_heading_is_excluded(self):
        content = (
            "### Page 3\n\n#### **NeurIPS Paper Checklist**\n\nQuestion and answer.\n\n"
            "#### Appendix\n\nTechnical appendix."
        )
        view = build_ai_processing_view(content)
        self.assertNotIn("Question and answer.", view.content)
        self.assertIn("Technical appendix.", view.content)
        self.assertTrue(any("paper checklist" in item for item in view.excluded_sections))

    def test_nonexcluded_canonical_sections_are_retained(self):
        headings = ("Related Work", "Limitations", "Appendix", "Experiment", "Methodology")
        content = "### Page 4\n\n" + "\n\n".join(
            f"#### **{heading}**\n\n{heading} body." for heading in headings
        )
        view = build_ai_processing_view(content)
        for heading in headings:
            with self.subTest(heading=heading):
                self.assertIn(f"{heading} body.", view.content)
        self.assertEqual(view.excluded_sections, ())

    def test_exclusion_ends_at_same_or_higher_heading_only(self):
        content = (
            "### Page 5\n\n#### **References**\n\nReference root.\n\n"
            "##### Reference Notes\n\nNested reference content.\n\n"
            "#### Related Work\n\nSame-level content.\n\n"
            "### Main Result\n\nHigher-level content."
        )
        view = build_ai_processing_view(content)
        self.assertNotIn("Reference root.", view.content)
        self.assertNotIn("Nested reference content.", view.content)
        self.assertIn("Same-level content.", view.content)
        self.assertIn("Higher-level content.", view.content)

    def test_references_are_excluded_but_appendix_is_preserved(self):
        content = (
            "### Page 1\n\nMain findings.\n\n#### References\n\n[1] Citation only.\n\n"
            "### Page 2\n\n#### Appendix A\n\nImportant ablation details."
        )
        view = build_ai_processing_view(content)
        self.assertIn("Main findings", view.content)
        self.assertNotIn("Citation only", view.content)
        self.assertIn("Appendix A", view.content)
        self.assertIn("Important ablation", view.content)
        self.assertIn("### Page 2", view.content)
        self.assertTrue(any("references" in item for item in view.excluded_sections))

    def test_neurips_checklist_is_excluded(self):
        content = "### Page 8\n\n#### NeurIPS Paper Checklist\n\nQuestion 1: yes"
        view = build_ai_processing_view(content)
        self.assertNotIn("Question 1", view.content)
        self.assertTrue(any("checklist" in item for item in view.excluded_sections))

    def test_standalone_table_of_contents_page_is_excluded(self):
        content = (
            "### Page 1\n\n# Contents\nIntroduction ........ 1\nMethods ........ 2\nResults ........ 4\n"
            "### Page 2\n\nActual introduction."
        )
        view = build_ai_processing_view(content)
        self.assertNotIn("Methods ........ 2", view.content)
        self.assertIn("Table of contents omitted", view.content)
        self.assertIn("Actual introduction", view.content)

    def test_valid_gfm_table_is_preserved(self):
        table = "| Model | Score |\n| --- | --- |\n| A | 0.9 |"
        view = build_ai_processing_view(f"### Page 3\n\n{table}")
        self.assertIn(table, view.content)
        self.assertEqual(view.warnings, ())

    def test_malformed_table_is_replaced_with_page_provenance(self):
        content = "### Page 4\n\n| Model | Score |\n| A | 0.9 | extra |"
        view = build_ai_processing_view(content)
        self.assertNotIn("| A | 0.9 | extra |", view.content)
        self.assertIn("Table omitted from AI extraction", view.content)
        self.assertIn("PDF p.4", view.content)
        self.assertTrue(any("table" in item for item in view.warnings))

    def test_flattened_formula_is_replaced_with_page_provenance(self):
        formula = "attention = softmax(Q * K^T / sqrt(d_k)) * V (1)"
        view = build_ai_processing_view(f"### Page 5\n\n{formula}")
        self.assertNotIn(formula, view.content)
        self.assertIn("Formula omitted from AI extraction", view.content)
        self.assertIn("PDF p.5", view.content)
        self.assertEqual(view.formula_warnings, ("malformed formula (PDF p.5)",))

    def test_figure_ocr_text_is_excluded_but_caption_is_preserved(self):
        content = (
            "### Page 7\n\n[Picture text]\nNODEMEMORYEDGE 12 94 51\n"
            "Figure 2: Overview of the memory graph.\n\nFollowing prose."
        )
        view = build_ai_processing_view(content)
        self.assertNotIn("NODEMEMORYEDGE", view.content)
        self.assertIn("Figure text omitted from AI extraction", view.content)
        self.assertIn("Figure 2: Overview of the memory graph.", view.content)
        self.assertIn("Following prose.", view.content)
        self.assertEqual(
            view.excluded_figure_text,
            ("picture-text block (PDF p.7)",),
        )

    def test_markdown_image_is_excluded_without_removing_caption(self):
        content = (
            "### Page 8\n\n![diagram](images/diagram.png)\n\n"
            "Fig. 3: System components and data flow."
        )
        view = build_ai_processing_view(content)
        self.assertNotIn("images/diagram.png", view.content)
        self.assertIn("Fig. 3: System components and data flow.", view.content)

    def test_missing_formula_after_introduction_is_reported(self):
        content = (
            "### Page 9\n\nThe attention equation is defined as:\n\n"
            "#### Training\n\nTraining continues here."
        )
        view = build_ai_processing_view(content)
        self.assertIn("The attention equation is defined as:", view.content)
        self.assertIn("expected formula is empty or missing", view.content)
        self.assertEqual(
            view.formula_warnings,
            ("missing formula after introduction (PDF p.9)",),
        )

    def test_excessive_numeric_density_table_is_excluded(self):
        row = "Results " + " 0.91 0.82 0.73 0.64 0.55 0.46 0.37 0.28" * 3
        view = build_ai_processing_view(f"### Page 10\n\n{row}\n{row}")
        self.assertNotIn(row, view.content)
        self.assertIn("excessive numeric density", view.content)
        self.assertEqual(
            view.excluded_tables,
            ("numeric-density table (PDF p.10)",),
        )

    def test_joined_word_ocr_block_is_excluded(self):
        content = (
            "### Page 11\n\nMEMORYNodeEdgeText\nAgentSTATEGraphValue\n"
            "ResultTABLEScoreValue\nPromptTEMPLATEOutputText"
        )
        view = build_ai_processing_view(content)
        self.assertNotIn("MEMORYNodeEdgeText", view.content)
        self.assertIn("probable joined-word OCR text", view.content)
        self.assertTrue(any("joined-word" in item for item in view.warnings))

    def test_headings_and_prose_are_included_and_reported(self):
        content = "### Page 12\n\n#### Method\n\nNormal prose explains the method."
        view = build_ai_processing_view(content)
        self.assertIn("#### Method", view.content)
        self.assertIn("Normal prose", view.content)
        self.assertEqual(view.included_sections, ("Method (PDF p.12)",))
        self.assertEqual(view.included_blocks, 2)

    def test_processing_never_modifies_source_text(self):
        source = (
            "### Page 13\n\n#### **References**\n\n[1] Original citation.\n\n"
            "### Page 14\n\n#### Appendix A\n\nOriginal appendix."
        )
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.md"
            source_path.write_text(source, encoding="utf-8")
            before = source_path.read_bytes()
            view = build_ai_processing_view(source_path.read_text(encoding="utf-8"))
            self.assertEqual(source_path.read_bytes(), before)
            self.assertNotEqual(view.content, source)
            self.assertIn("PDF p.14", " ".join(view.included_sections))

    def test_dry_run_report_exposes_processing_metrics(self):
        plan = ProcessingPlan()
        plan.stats.source_characters = 200
        plan.stats.processing_characters = 120
        plan.stats.chunk_count = 2
        plan.stats.included_blocks = 4
        plan.included_sections.append("source.md: Method (PDF p.2)")
        plan.excluded_sections.append("source.md: references (PDF p.8)")
        plan.excluded_tables.append("source.md: malformed Markdown table (PDF p.4)")
        plan.excluded_figure_text.append("source.md: picture-text block (PDF p.5)")
        plan.formula_warnings.append("source.md: malformed formula (PDF p.6)")
        plan.methodology_subsections.append("source.md: state construction")
        plan.quality_gate_status = "failed"
        plan.quality_gate_reasons.append("source.md: test quality reason")
        output = StringIO()
        with redirect_stdout(output):
            _print_ai_wiki_plan(plan, Path.cwd(), write=False)
        report = output.getvalue()
        for expected in (
            "mode: dry-run",
            "processing_characters: 120",
            "chunk_count: 2",
            "included_blocks: 4",
            "included_sections:",
            "excluded_sections:",
            "excluded_tables:",
            "excluded_figure_text:",
            "formula_warnings:",
            "methodology_subsections:",
            "quality_gate:",
            "status: failed",
            "test quality reason",
            "curator_calls: 0",
            "candidate_concepts:",
            "selected_concepts:",
            "dropped_concepts:",
            "duplicate_risk_groups:",
            "curator_trigger_reason:",
            "selected_representatives:",
            "dropped_aliases:",
        ):
            self.assertIn(expected, report)

    def test_normal_prose_is_unchanged(self):
        content = "### Page 6\n\nA normal English paragraph explains the method."
        view = build_ai_processing_view(content)
        self.assertEqual(view.content, content)
        self.assertEqual(view.excluded_sections, ())
        self.assertEqual(view.warnings, ())


if __name__ == "__main__":
    unittest.main()

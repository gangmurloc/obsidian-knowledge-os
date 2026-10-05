from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))

from knowledge_os.ai_wiki import ScanScope, process_ai_wiki  # noqa: E402
from knowledge_os.ai_wiki.coverage import locate_excerpt  # noqa: E402
from knowledge_os.ai_wiki.models import SourceNote  # noqa: E402
from knowledge_os.ai_wiki.ontology import concept_identity  # noqa: E402
from knowledge_os.ai_wiki.preprocess import (  # noqa: E402
    AI_PROCESSING_VIEW_VERSION,
    build_ai_processing_view,
    detect_methodology_subsections,
)
from knowledge_os.ai_wiki.source import chunk_source  # noqa: E402
from knowledge_os.cli import _print_ai_wiki_plan, main  # noqa: E402
from knowledge_os.llm import FakeLLMProvider  # noqa: E402


SOURCE_RELATIVE = "30_Resources/Sources/Papers/source-one.md"
SOURCE_TITLE = "Structured Reasoning Study"
FAKE_MODEL = "fake-local:latest"
FILLER = "Neutral filler sentence keeps this paragraph long enough for chunk sizing. "
P1_LEAD = "State construction builds normalized records from raw events."
P2_LEAD = "The record assembler merges partial states into one canonical record."
Q1_LEAD = "Dynamic routing selects a handler for every canonical record."
E1_LEAD = "The experiment measures routing accuracy on held out traffic."


def paragraph(lead: str) -> str:
    return f"{lead} {(FILLER * 7).strip()}"


# With max_chunk_chars=1000 this body yields four chunks:
#   1: root heading, 3.1 heading, P1      2: P2, 3.2 heading
#   3: 3.2 heading (overlap), Q1, 4 heading   4: 4 heading (overlap), E1
# The 3.1 body continues into chunk 2, which has no 3.1 heading line.
METHOD_BODY = "\n\n".join(
    [
        "#### 3 Methodology",
        "##### 3.1 State Construction",
        paragraph(P1_LEAD),
        paragraph(P2_LEAD),
        "##### 3.2 Dynamic Routing",
        paragraph(Q1_LEAD),
        "#### 4 Experiment",
        paragraph(E1_LEAD),
    ]
)


def concept(title: str, *, role: str = "mechanism", excerpts: tuple[str, ...]) -> dict:
    return {
        "title": title,
        "definition": f"{title} definition",
        "core_idea": f"{title} core idea",
        "mechanism": f"{title} mechanism",
        "role": role,
        "key_points": [f"{title} key point"],
        "related_concepts": ["Future Concept"],
        "evidence": [
            {"claim": f"{title} claim {index}", "source_excerpt": excerpt}
            for index, excerpt in enumerate(excerpts, start=1)
        ],
        "open_questions": [f"How should {title} be verified?"],
        "domain": ["Natural Language Processing"],
    }


def response(*concepts: dict) -> str:
    return json.dumps({"concepts": list(concepts)}, ensure_ascii=False)


def curator_response(*titles: str) -> str:
    return json.dumps(
        {
            "selected": [
                {"identity": concept_identity(title), "reason": "kept"}
                for title in titles
            ]
        }
    )


def span_ids(body: str) -> dict[str, str]:
    view = build_ai_processing_view(body)
    return {span.canonical_heading: span.subsection_id for span in view.method_subsection_spans}


def legacy_chunk_texts(content: str, max_chars: int, overlap_chars: int = 200) -> list[str]:
    """Frozen copy of the chunk text assembly as it was before offsets were added."""

    def split_block(block: str) -> list[str]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        pieces: list[str] = []
        for line in lines or [block.strip()]:
            if len(line) <= max_chars:
                pieces.append(line)
                continue
            for sentence in re.split(r"(?<=[.!?。！？])\s+", line):
                sentence = sentence.strip()
                if not sentence:
                    continue
                if len(sentence) <= max_chars:
                    pieces.append(sentence)
                else:
                    pieces.extend(
                        sentence[index : index + max_chars]
                        for index in range(0, len(sentence), max_chars)
                    )
        return pieces

    blocks: list[str] = []
    for block in (item.strip() for item in re.split(r"\n[ \t]*\n", content)):
        if block:
            blocks.extend(split_block(block))

    texts: list[str] = []
    current: list[str] = []
    current_length = 0
    for block in blocks:
        separator_length = 2 if current else 0
        if current and current_length + separator_length + len(block) > max_chars:
            texts.append("\n\n".join(current))
            overlap: list[str] = []
            overlap_length = 0
            for previous in reversed(current):
                added = len(previous) + (2 if overlap else 0)
                if overlap_length + added > overlap_chars:
                    break
                overlap.insert(0, previous)
                overlap_length += added
            current = overlap
            current_length = len("\n\n".join(current))
            if current and current_length + 2 + len(block) > max_chars:
                current = []
                current_length = 0
        if current:
            current_length += 2
        current.append(block)
        current_length += len(block)
    if current:
        text = "\n\n".join(current)
        if not texts or text != texts[-1]:
            texts.append(text)
    return texts


def source_note(content: str) -> SourceNote:
    return SourceNote(
        path=Path("source-one.md"),
        relative_path=SOURCE_RELATIVE,
        note_name="source-one",
        metadata={},
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


class MethodSubsectionSpanTests(unittest.TestCase):
    def test_three_subsections_get_adjacent_non_overlapping_spans(self):
        content = (
            "### Page 1\n\n#### 3 Methodology\n\nOverview of the method.\n\n"
            "##### 3.1 State Construction\n\nState construction builds records.\n\n"
            "##### 3.2 Dynamic Routing\n\nDynamic routing selects handlers.\n\n"
            "##### 3.3 Memory Consolidation\n\nConsolidation merges records.\n\n"
            "#### 4 Experiment\n\n##### 4.1 Dataset and Evaluation\n\nDataset text."
        )
        view = build_ai_processing_view(content)
        spans = view.method_subsection_spans

        self.assertEqual(
            [span.canonical_heading for span in spans],
            ["state construction", "dynamic routing", "memory consolidation"],
        )
        self.assertEqual(
            [span.original_heading for span in spans],
            ["3.1 State Construction", "3.2 Dynamic Routing", "3.3 Memory Consolidation"],
        )
        for span in spans:
            self.assertTrue(
                view.content[span.start :].startswith(f"##### {span.original_heading}")
            )
            self.assertTrue(span.start == 0 or view.content[span.start - 1] == "\n")
            self.assertEqual(span.pages, (1,))
        self.assertEqual(spans[0].end, spans[1].start)
        self.assertEqual(spans[1].end, spans[2].start)
        self.assertEqual(spans[2].end, view.content.index("#### 4 Experiment"))
        self.assertIn("State construction builds records.", view.content[spans[0].start : spans[0].end])
        self.assertNotIn("Dynamic routing", view.content[spans[0].start : spans[0].end])

    def test_non_method_subsections_are_not_span_targets_but_end_siblings(self):
        content = (
            "#### 3 Methodology\n\n"
            "##### 3.1 State Construction\n\nBuilds records.\n\n"
            "##### 3.2 Implementation Details\n\nUses a small cache.\n\n"
            "#### 4 Experiment\n\n"
            "##### 4.1 Dataset and Evaluation\n\nDataset text.\n\n"
            "##### 4.2 Ablation Study\n\nAblation text."
        )
        view = build_ai_processing_view(content)
        spans = view.method_subsection_spans

        self.assertEqual([span.canonical_heading for span in spans], ["state construction"])
        self.assertEqual(spans[0].end, view.content.index("##### 3.2 Implementation Details"))

    def test_page_markers_do_not_end_a_span_and_are_recorded(self):
        content = (
            "### Page 4\n\n#### 3 Methodology\n\n"
            "##### 3.1 State Construction\n\nFirst part of the description.\n\n"
            "### Page 5\n\nSecond part continues on the next page.\n\n"
            "##### 3.2 Dynamic Routing\n\nRouting text.\n\n"
            "### Page 6\n\n#### 4 Results\n\nResult text."
        )
        view = build_ai_processing_view(content)
        first, second = view.method_subsection_spans

        self.assertIn(
            "Second part continues on the next page.",
            view.content[first.start : first.end],
        )
        self.assertEqual(first.pages, (4, 5))
        self.assertEqual(first.end, second.start)
        self.assertEqual(second.pages, (5, 6))
        self.assertEqual(second.end, view.content.index("#### 4 Results"))

    def test_numbering_decides_boundaries_when_markdown_levels_are_flattened(self):
        content = (
            "#### 3 Methodolodgy\n\n"
            "#### 3.1 State Construction\n\nA text.\n\n"
            "#### 3.1.1 Record Schema\n\nB text.\n\n"
            "###### Field Notes\n\nC text.\n\n"
            "#### 3.2 Dynamic Routing\n\nD text.\n\n"
            "#### 4 Experiment\n\nE text."
        )
        view = build_ai_processing_view(content)
        spans = {span.canonical_heading: span for span in view.method_subsection_spans}
        next_sibling = view.content.index("#### 3.2 Dynamic Routing")
        root_end = view.content.index("#### 4 Experiment")

        self.assertEqual(
            list(spans),
            ["state construction", "record schema", "field notes", "dynamic routing"],
        )
        self.assertEqual(spans["state construction"].end, next_sibling)
        self.assertEqual(spans["record schema"].end, next_sibling)
        self.assertEqual(spans["field notes"].end, next_sibling)
        self.assertEqual(spans["dynamic routing"].end, root_end)
        parent, child = spans["state construction"], spans["record schema"]
        self.assertTrue(parent.start < child.start and child.end <= parent.end)

    def test_markdown_levels_decide_boundaries_without_numbers(self):
        content = (
            "## Method\n\n"
            "### State Construction\n\nA text.\n\n"
            "#### Record Schema\n\nB text.\n\n"
            "### Dynamic Routing\n\nC text.\n\n"
            "## Results\n\nD text."
        )
        view = build_ai_processing_view(content)
        spans = {span.canonical_heading: span for span in view.method_subsection_spans}

        self.assertEqual(
            spans["state construction"].end,
            view.content.index("### Dynamic Routing"),
        )
        self.assertEqual(spans["record schema"].end, view.content.index("### Dynamic Routing"))
        self.assertEqual(spans["dynamic routing"].end, view.content.index("## Results"))

    def test_last_span_ends_at_content_end_when_the_root_never_closes(self):
        content = "## Approach\n\n### State Construction\n\nA text.\n\n### Dynamic Routing\n\nB text."
        view = build_ai_processing_view(content)
        self.assertEqual(view.method_subsection_spans[-1].end, len(view.content))

    def test_subsection_id_is_stable_and_depends_on_the_heading(self):
        content = (
            "## Method\n\n### State Construction\n\nA text.\n\n"
            "### Dynamic Routing\n\nB text.\n\n### State Construction\n\nC text."
        )
        first = build_ai_processing_view(content).method_subsection_spans
        second = build_ai_processing_view(content).method_subsection_spans
        renamed = build_ai_processing_view(
            content.replace("### Dynamic Routing", "### Dynamic Dispatch")
        ).method_subsection_spans

        self.assertEqual([span.subsection_id for span in first], [span.subsection_id for span in second])
        for span in first:
            self.assertRegex(span.subsection_id, r"^ms-[0-9a-f]{8}$")
        self.assertEqual(len({span.subsection_id for span in first}), 3)
        self.assertEqual(first[0].subsection_id, renamed[0].subsection_id)
        self.assertNotEqual(first[1].subsection_id, renamed[1].subsection_id)

    def test_methodology_subsections_stay_backward_compatible(self):
        content = (
            "## Method\n\n### State Construction\n\nA text.\n\n"
            "### Dynamic Routing\n\nB text.\n\n### State Construction\n\nC text."
        )
        view = build_ai_processing_view(content)

        self.assertEqual(view.methodology_subsections, ("state construction", "dynamic routing"))
        self.assertEqual(
            view.methodology_subsections,
            tuple(dict.fromkeys(span.canonical_heading for span in view.method_subsection_spans)),
        )
        self.assertEqual(detect_methodology_subsections(view.content), view.methodology_subsections)
        self.assertEqual(build_ai_processing_view("Plain text only.").method_subsection_spans, ())

    def test_processing_view_content_and_version_are_unchanged(self):
        content = (
            "### Page 1\n\n#### 3 Methodology\n\n"
            "##### 3.1 State Construction\n\nBuilds **records** from events.\n\n"
            "| a | b |\n| broken row\n\n"
            "### Page 2\n\n#### References\n\n[1] Some cited work.\n\n"
            "#### A Appendix\n\nAppendix text."
        )
        self.assertEqual(AI_PROCESSING_VIEW_VERSION, 6)
        self.assertEqual(build_ai_processing_view(content).content, GOLDEN_VIEW_CONTENT)


class ChunkOffsetTests(unittest.TestCase):
    CONTENTS = (
        METHOD_BODY,
        "### Page 1\n\nFirst line of a block\nsecond line of the same block\n\n"
        + ("Sentence one is here. " * 80).strip()
        + "\n\n"
        + ("가나다라마바사 문장입니다。 " * 120).strip()
        + "\n\n"
        + ("x" * 2_600)
        + "\n\nTail paragraph.",
        "Only one short paragraph.",
        "  Leading spaces paragraph.  \n \t \nSecond paragraph\twith tab.\n\n\n\nThird paragraph.",
    )

    def test_chunk_text_and_identifier_match_the_previous_algorithm(self):
        for content in self.CONTENTS:
            for max_chars in (1_000, 4_000):
                with self.subTest(length=len(content), max_chars=max_chars):
                    source = source_note(content)
                    chunks = chunk_source(source, content=content, max_chars=max_chars)
                    expected = legacy_chunk_texts(content, max_chars)
                    self.assertEqual([chunk.text for chunk in chunks], expected)
                    for index, (chunk, text) in enumerate(zip(chunks, expected), start=1):
                        digest = hashlib.sha256(
                            f"{source.content_hash}:{index}:{text}".encode("utf-8")
                        ).hexdigest()[:16]
                        self.assertEqual(chunk.identifier, f"chunk-{index:04d}-{digest}")

    def test_chunk_offsets_address_the_processing_content(self):
        for content in self.CONTENTS:
            for max_chars in (1_000, 4_000):
                with self.subTest(length=len(content), max_chars=max_chars):
                    chunks = chunk_source(source_note(content), content=content, max_chars=max_chars)
                    for chunk in chunks:
                        self.assertIsNotNone(chunk.start)
                        self.assertIsNotNone(chunk.end)
                        self.assertTrue(0 <= chunk.start < chunk.end <= len(content))
                        self.assertEqual(
                            "".join(content[chunk.start : chunk.end].split()),
                            "".join(chunk.text.split()),
                        )
                    starts = [chunk.start for chunk in chunks]
                    self.assertEqual(starts, sorted(starts))
                    self.assertEqual(chunks[-1].end, len(content.rstrip()))

    def test_chunk_offsets_follow_overlap_blocks(self):
        chunks = chunk_source(source_note(METHOD_BODY), content=METHOD_BODY, max_chars=1_000)
        heading = METHOD_BODY.index("##### 3.2 Dynamic Routing")

        self.assertEqual(len(chunks), 4)
        self.assertEqual(chunks[0].start, 0)
        self.assertEqual(chunks[1].start, METHOD_BODY.index(P2_LEAD))
        self.assertEqual(chunks[1].end, heading + len("##### 3.2 Dynamic Routing"))
        self.assertEqual(chunks[2].start, heading)


class LocateExcerptTests(unittest.TestCase):
    CONTENT = (
        "### Page 1\n\n#### 3 Methodology\n\n"
        "The **Record Assembler** merges partial\nstates into `one` canonical record.\n\n"
        "> [Table omitted from AI extraction: layout confidence low. See PDF p.1.]\n\n"
        "Repeated sentence about routing.\n\nThe model uses ﬁne-tuning on Ｈ２ data.\n\n"
        "Repeated sentence about routing."
    )

    def test_case_whitespace_and_emphasis_differences_are_located(self):
        located = locate_excerpt(
            "the record assembler merges   partial states\ninto *one* canonical RECORD.",
            self.CONTENT,
        )
        self.assertIsNotNone(located)
        start, end = located
        self.assertEqual(
            self.CONTENT[start:end],
            "The **Record Assembler** merges partial\nstates into `one` canonical record.",
        )

    def test_compatibility_characters_are_located_at_original_offsets(self):
        located = locate_excerpt("uses fine-tuning on H2 data", self.CONTENT)
        self.assertIsNotNone(located)
        start, end = located
        self.assertEqual(self.CONTENT[start:end], "uses ﬁne-tuning on Ｈ２ data")

    def test_paraphrase_and_empty_excerpts_are_not_located(self):
        self.assertIsNone(
            locate_excerpt("An assembler combines several states into a record.", self.CONTENT)
        )
        for empty in ("", "   \n\t ", "**", "_`*_"):
            with self.subTest(excerpt=empty):
                self.assertIsNone(locate_excerpt(empty, self.CONTENT))

    def test_text_found_only_inside_an_omission_marker_is_not_located(self):
        self.assertIsNone(locate_excerpt("layout confidence low", self.CONTENT))
        self.assertIsNone(locate_excerpt("Table omitted from AI extraction", self.CONTENT))

    def test_repeated_text_prefers_the_given_range_then_the_first_match(self):
        first = self.CONTENT.index("Repeated sentence about routing.")
        second = self.CONTENT.rindex("Repeated sentence about routing.")
        length = len("Repeated sentence about routing.")
        self.assertNotEqual(first, second)

        self.assertEqual(
            locate_excerpt("repeated sentence about routing.", self.CONTENT),
            (first, first + length),
        )
        self.assertEqual(
            locate_excerpt(
                "repeated sentence about routing.",
                self.CONTENT,
                preferred_range=(second - 10, len(self.CONTENT)),
            ),
            (second, second + length),
        )
        self.assertEqual(
            locate_excerpt(
                "repeated sentence about routing.",
                self.CONTENT,
                preferred_range=(0, 5),
            ),
            (first, first + length),
        )


class MethodCoverageTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_directory.name)
        self.papers = self.vault / "30_Resources" / "Sources" / "Papers"
        self.ai_wiki = self.vault / "30_Resources" / "AI-Wiki"
        self.knowledge = self.vault / "30_Resources" / "Knowledge"
        for directory in (self.papers, self.ai_wiki, self.knowledge):
            directory.mkdir(parents=True)

    def tearDown(self):
        self.temp_directory.cleanup()

    def _source(self, body: str, *, title: str = SOURCE_TITLE) -> Path:
        path = self.papers / "source-one.md"
        path.write_text(
            "---\n"
            "type: source\n"
            "origin: external\n"
            "source_type: pdf\n"
            "knowledge_status: raw\n"
            f"title: {json.dumps(title)}\n"
            "created: 2026-09-26\n"
            "updated: 2026-09-26\n"
            "source_file: _assets/PDF/test.pdf\n"
            "domain: []\n"
            "human_verified: false\n"
            "---\n\n"
            f"# {title}\n\n"
            "## Content\n\n"
            f"{body}\n\n"
            "## My Highlights\n\nUser-owned highlight.\n",
            encoding="utf-8",
        )
        return path

    def _run(self, responses: tuple[str, ...], *, max_chunk_chars: int = 1_000, write: bool = False):
        provider = FakeLLMProvider(response_texts=responses)
        plan = process_ai_wiki(
            vault_root=self.vault,
            provider=provider,
            model_name=FAKE_MODEL,
            scope=ScanScope("all"),
            write=write,
            max_chunk_chars=max_chunk_chars,
        )
        return plan, provider

    def _rows(self, plan) -> dict[str, str]:
        rows: dict[str, str] = {}
        for line in plan.method_coverage:
            match = re.match(r"^.+?: \[ms-[0-9a-f]{8}\] (?P<heading>.+?) pages=", line)
            if match:
                rows[match["heading"]] = line
        return rows

    def _report(self, plan) -> str:
        output = StringIO()
        with redirect_stdout(output):
            _print_ai_wiki_plan(plan, self.vault, write=False)
        return output.getvalue()


SCENARIO_TITLE_COVER = (
    response(concept("State Construction", excerpts=(P1_LEAD,))),
    response(concept("Record Assembler", excerpts=(P2_LEAD,))),
    response(concept("Dynamic Routing", excerpts=(Q1_LEAD,))),
    response(),
)
SCENARIO_PARAPHRASE = (
    response(concept("Record Normalization Pipeline", excerpts=(P1_LEAD,))),
    response(),
    response(concept("Handler Selection Policy", excerpts=(Q1_LEAD,))),
    response(),
    curator_response("Record Normalization Pipeline", "Handler Selection Policy"),
)


class MethodCoverageReportTests(MethodCoverageTestCase):
    def test_body_continuing_into_a_headingless_chunk_is_linked_by_offset(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(SCENARIO_TITLE_COVER)
        ids = span_ids(METHOD_BODY)

        self.assertEqual(plan.stats.chunk_count, 4)
        self.assertEqual(
            plan.method_coverage,
            [
                f"{SOURCE_RELATIVE}: [{ids['state construction']}] state construction "
                "pages=- heading_chunks=1 offset_chunks=1,2 "
                "| candidates: title_cover=y evidence_cover=y "
                "| selected: title_cover=y evidence_cover=y "
                "| in_span: Record Assembler(mechanism, located 1/1), "
                "State Construction(mechanism, located 1/1)",
                f"{SOURCE_RELATIVE}: [{ids['dynamic routing']}] dynamic routing "
                "pages=- heading_chunks=2,3 offset_chunks=2,3 "
                "| candidates: title_cover=y evidence_cover=y "
                "| selected: title_cover=y evidence_cover=y "
                "| in_span: Dynamic Routing(mechanism, located 1/1)",
            ],
        )
        self.assertEqual(
            plan.evidence_locatability,
            [f"{SOURCE_RELATIVE}: located 3/3 evidence across 3 candidates"],
        )

    def test_paraphrased_mechanism_is_evidence_covered_but_not_title_covered(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(SCENARIO_PARAPHRASE)
        rows = self._rows(plan)

        self.assertEqual(plan.quality_gate_status, "failed")
        for heading, title in (
            ("state construction", "Record Normalization Pipeline"),
            ("dynamic routing", "Handler Selection Policy"),
        ):
            with self.subTest(heading=heading):
                self.assertIn(
                    "| candidates: title_cover=n evidence_cover=y "
                    "| selected: title_cover=n evidence_cover=y "
                    f"| in_span: {title}(mechanism, located 1/1)",
                    rows[heading],
                )

    def test_method_entity_evidence_in_span_does_not_count_as_cover(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(
            (
                response(
                    concept(
                        "Record Normalization Pipeline",
                        role="method_entity",
                        excerpts=(P1_LEAD, "A sentence that never appears in the source."),
                    )
                ),
                response(),
                response(concept("Handler Selection Policy", excerpts=(Q1_LEAD,))),
                response(),
                curator_response("Record Normalization Pipeline", "Handler Selection Policy"),
            )
        )
        rows = self._rows(plan)

        self.assertIn("role=method_entity", plan.candidate_concepts[1])
        self.assertIn(
            "| candidates: title_cover=n evidence_cover=n "
            "| selected: title_cover=n evidence_cover=n "
            "| in_span: Record Normalization Pipeline(method_entity, located 1/2)",
            rows["state construction"],
        )
        self.assertIn("| candidates: title_cover=n evidence_cover=y ", rows["dynamic routing"])
        self.assertEqual(
            plan.evidence_locatability,
            [f"{SOURCE_RELATIVE}: located 2/3 evidence across 2 candidates"],
        )

    def test_evidence_in_another_span_covers_only_that_subsection(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(
            (
                response(concept("Handler Selection Policy", excerpts=(Q1_LEAD,))),
                response(),
                response(),
                response(),
                curator_response("Handler Selection Policy"),
            )
        )
        rows = self._rows(plan)

        self.assertTrue(
            rows["state construction"].endswith(
                "| candidates: title_cover=n evidence_cover=n "
                "| selected: title_cover=n evidence_cover=n | in_span: (none)"
            )
        )
        self.assertTrue(
            rows["dynamic routing"].endswith(
                "| candidates: title_cover=n evidence_cover=y "
                "| selected: title_cover=n evidence_cover=y "
                "| in_span: Handler Selection Policy(mechanism, located 1/1)"
            )
        )

    def test_selected_cover_reflects_the_curator_choice(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(
            SCENARIO_PARAPHRASE[:4] + (curator_response("Handler Selection Policy"),)
        )
        rows = self._rows(plan)

        self.assertIn(
            "| candidates: title_cover=n evidence_cover=y "
            "| selected: title_cover=n evidence_cover=n ",
            rows["state construction"],
        )

    def test_source_without_methodology_subsections_is_reported(self):
        self._source("#### Survey Taxonomy\n\nThis survey organizes prior work.")
        plan, _provider = self._run(
            (response(concept("Retrieval Taxonomy", excerpts=("Not in the source.",))),)
        )

        self.assertEqual(plan.processed_sources, [SOURCE_RELATIVE])
        self.assertEqual(
            plan.method_coverage,
            [f"{SOURCE_RELATIVE}: no methodology subsections detected"],
        )
        self.assertEqual(
            plan.evidence_locatability,
            [f"{SOURCE_RELATIVE}: located 0/1 evidence across 1 candidates"],
        )
        report = self._report(plan)
        self.assertIn(
            "method_coverage:\n"
            f"  - {SOURCE_RELATIVE}: no methodology subsections detected\n",
            report,
        )
        self.assertIn(
            "evidence_locatability:\n"
            f"  - {SOURCE_RELATIVE}: located 0/1 evidence across 1 candidates\n",
            report,
        )

    def test_report_never_contains_excerpt_or_body_text(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(SCENARIO_TITLE_COVER)
        report = self._report(plan)

        self.assertIn("method_coverage:", report)
        self.assertIn("evidence_locatability:", report)
        for text in (P1_LEAD, P2_LEAD, Q1_LEAD, E1_LEAD, FILLER.strip()):
            with self.subTest(text=text):
                self.assertNotIn(text, report)
                self.assertNotIn(text.casefold(), "\n".join(plan.method_coverage).casefold())

    def test_subsection_rows_are_capped_at_twenty(self):
        names = (
            "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliet Kilo Lima Mike "
            "November Oscar Papa Quebec Romeo Sierra Tango Uniform Victor Whiskey Xray Yankee"
        ).split()
        body = "#### 3 Methodology\n\n" + "\n\n".join(
            f"##### 3.{index} {name} Module\n\n{name} module handles one step."
            for index, name in enumerate(names, start=1)
        )
        self._source(body)
        plan, _provider = self._run(
            (
                response(concept("Stepwise Controller", excerpts=("Alpha module handles one step.",))),
                curator_response("Stepwise Controller"),
            ),
            max_chunk_chars=4_000,
        )

        self.assertEqual(len(names), 25)
        self.assertEqual(plan.stats.chunk_count, 1)
        self.assertEqual(len(plan.method_coverage), 21)
        self.assertEqual(plan.method_coverage[-1], f"{SOURCE_RELATIVE}: ... (+5 more)")
        self.assertIn("alpha module", plan.method_coverage[0])
        self.assertIn("tango module", plan.method_coverage[19])

    def test_in_span_candidates_are_capped_at_five(self):
        leads = [f"Step {word} of the pipeline transforms the record." for word in
                 ("one", "two", "three", "four", "five", "six", "seven")]
        body = "\n\n".join(
            ["#### 3 Methodology", "##### 3.1 State Construction"]
            + [paragraph(lead) for lead in leads]
        )
        titles = (
            "Alpha Planner", "Beta Router", "Gamma Indexer", "Delta Ranker",
            "Epsilon Merger", "Zeta Filter", "Eta Scheduler",
        )
        self._source(body)
        plan, _provider = self._run(
            tuple(response(concept(title, excerpts=(leads[0],))) for title in titles)
        )
        rows = self._rows(plan)

        self.assertEqual(plan.stats.chunk_count, 7)
        self.assertEqual(plan.stats.curator_calls, 0)
        row = rows["state construction"]
        self.assertEqual(row.count("(mechanism, located 1/1)"), 5)
        self.assertTrue(row.endswith(", +2 more"))


class ReportOnlyRegressionTests(MethodCoverageTestCase):
    def _summary(self, plan) -> dict:
        return {
            "quality_gate_status": plan.quality_gate_status,
            "quality_gate_reasons": plan.quality_gate_reasons,
            "curator_trigger_reason": plan.curator_trigger_reason,
            "candidate_concepts": plan.candidate_concepts,
            "selected_concepts": plan.selected_concepts,
            "llm_calls": plan.stats.llm_calls,
        }

    def test_existing_decisions_are_unchanged_by_the_diagnostics(self):
        self._source(METHOD_BODY)
        for name, responses in (
            ("title_cover", SCENARIO_TITLE_COVER),
            ("paraphrase", SCENARIO_PARAPHRASE),
        ):
            with self.subTest(scenario=name):
                plan, provider = self._run(responses)
                self.assertEqual(self._summary(plan), GOLDEN_DECISIONS[name])
                self.assertEqual(len(provider.requests), GOLDEN_DECISIONS[name]["llm_calls"])

    def test_diagnostics_failure_becomes_a_warning_and_changes_no_decision(self):
        self._source(METHOD_BODY)
        with patch(
            "knowledge_os.ai_wiki.engine.build_method_coverage",
            side_effect=RuntimeError("boom"),
        ):
            plan, _provider = self._run(SCENARIO_PARAPHRASE)

        self.assertEqual(self._summary(plan), GOLDEN_DECISIONS["paraphrase"])
        self.assertEqual(plan.failures, [])
        self.assertEqual(plan.method_coverage, [])
        self.assertEqual(plan.evidence_locatability, [])
        self.assertEqual(
            [warning for warning in plan.warnings if "diagnostics failed" in warning],
            [f"{SOURCE_RELATIVE}: method coverage diagnostics failed: RuntimeError: boom"],
        )

    def _main(self, provider: FakeLLMProvider) -> tuple[int, str]:
        config = self.vault / ".automation" / "config" / "local_llm.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            json.dumps({"provider": "ollama", "model": FAKE_MODEL}),
            encoding="utf-8",
        )
        output = StringIO()
        with (
            patch("knowledge_os.cli.create_provider", return_value=provider),
            patch("knowledge_os.cli.logging.basicConfig"),
            redirect_stdout(output),
        ):
            code = main(["--vault", str(self.vault), "ai-wiki", "scan", "--all"])
        return code, output.getvalue()

    def test_exit_codes_are_unchanged_and_the_cli_prints_the_diagnostics(self):
        body = (
            "#### 3 Methodology\n\n"
            "##### 3.1 State Construction\n\n" + ("A" * 3_400) + "\n\n"
            "##### 3.2 Dynamic Routing\n\n" + ("B" * 3_400)
        )
        self._source(body)
        cases = (
            (
                6,
                (
                    response(concept("General Design One", role="core_concept", excerpts=("x",))),
                    response(concept("General Design Two", role="core_concept", excerpts=("y",))),
                    curator_response("General Design One"),
                ),
            ),
            (
                0,
                (
                    response(concept("State Construction", excerpts=("x",))),
                    response(concept("Dynamic Routing", excerpts=("y",))),
                ),
            ),
        )
        for expected_code, responses in cases:
            with self.subTest(expected_code=expected_code):
                code, report = self._main(FakeLLMProvider(response_texts=responses))
                self.assertEqual(code, expected_code)
                self.assertIn("method_coverage:\n  - ", report)
                self.assertIn("evidence_locatability:\n  - ", report)
                self.assertEqual(report.count("] state construction pages="), 1)

    def test_dry_run_writes_nothing_and_leaves_owned_notes_untouched(self):
        source = self._source(METHOD_BODY)
        knowledge = self.knowledge / "Human Note.md"
        knowledge.write_text("Human-owned content.\n", encoding="utf-8")

        def snapshot() -> dict[str, str]:
            return {
                path.relative_to(self.vault).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self.vault.rglob("*"))
                if path.is_file()
            }

        before = snapshot()
        plan, _provider = self._run(SCENARIO_PARAPHRASE)

        self.assertTrue(plan.method_coverage)
        self.assertEqual(snapshot(), before)
        self.assertIn(source.relative_to(self.vault).as_posix(), before)
        self.assertIn(knowledge.relative_to(self.vault).as_posix(), before)


# Recorded from the pipeline before the Stage 1 diagnostics were added.
GOLDEN_VIEW_CONTENT = (
    "### Page 1\n"
    "\n"
    "#### 3 Methodology\n"
    "\n"
    "##### 3.1 State Construction\n"
    "\n"
    "Builds **records** from events.\n"
    "\n"
    "> [Table omitted from AI extraction: layout confidence low. See PDF p.1.]\n"
    "\n"
    "### Page 2\n"
    "\n"
    "#### A Appendix\n"
    "\n"
    "Appendix text."
)
GOLDEN_DECISIONS: dict[str, dict] = {
    "title_cover": {
        "quality_gate_status": "pass",
        "quality_gate_reasons": [],
        "curator_trigger_reason": [],
        "candidate_concepts": [
            f"{SOURCE_RELATIVE}: Dynamic Routing [dynamic routing] role=mechanism",
            f"{SOURCE_RELATIVE}: Record Assembler [record assembler] role=mechanism",
            f"{SOURCE_RELATIVE}: State Construction [state construction] role=mechanism",
        ],
        "selected_concepts": [
            f"{SOURCE_RELATIVE}: State Construction [state construction] "
            "(within source limit; curator not required; role=mechanism)",
            f"{SOURCE_RELATIVE}: Record Assembler [record assembler] "
            "(within source limit; curator not required; role=mechanism)",
            f"{SOURCE_RELATIVE}: Dynamic Routing [dynamic routing] "
            "(within source limit; curator not required; role=mechanism)",
        ],
        "llm_calls": 4,
    },
    "paraphrase": {
        "quality_gate_status": "failed",
        "quality_gate_reasons": [
            f"{SOURCE_RELATIVE}: explicit methodology mechanisms detected but none selected"
        ],
        "curator_trigger_reason": [f"{SOURCE_RELATIVE}: explicit-method coverage failure"],
        "candidate_concepts": [
            f"{SOURCE_RELATIVE}: Handler Selection Policy [handler selection policy] role=mechanism",
            f"{SOURCE_RELATIVE}: Record Normalization Pipeline "
            "[record normalization pipeline] role=mechanism",
        ],
        "selected_concepts": [
            f"{SOURCE_RELATIVE}: Record Normalization Pipeline "
            "[record normalization pipeline] (kept)",
            f"{SOURCE_RELATIVE}: Handler Selection Policy [handler selection policy] (kept)",
        ],
        "llm_calls": 5,
    },
}


if __name__ == "__main__":
    unittest.main()

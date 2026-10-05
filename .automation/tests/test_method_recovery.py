from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_os.ai_wiki.engine import (  # noqa: E402
    AI_WIKI_MAX_OUTPUT_TOKENS,
    MAX_METHOD_RECOVERY_CALLS,
)
from knowledge_os.ai_wiki.schema import (  # noqa: E402
    CONCEPT_EXTRACTION_SCHEMA,
    build_targeted_extraction_prompt,
)
from knowledge_os.ai_wiki.source import chunk_source  # noqa: E402
from knowledge_os.llm import FakeLLMProvider, ProviderTimeoutError  # noqa: E402
from test_method_coverage import (  # noqa: E402
    E1_LEAD,
    METHOD_BODY,
    P1_LEAD,
    P2_LEAD,
    Q1_LEAD,
    SCENARIO_PARAPHRASE,
    SCENARIO_TITLE_COVER,
    SOURCE_RELATIVE,
    MethodCoverageTestCase,
    concept,
    curator_response,
    paragraph,
    response,
    source_note,
    span_ids,
)


OVERVIEW = response(
    concept("Structured Reasoning Overview", role="core_concept", excerpts=("Not in the source.",))
)
# With the default chunk size the whole METHOD_BODY is one general chunk, so the
# general pass can return a single concept for two method subsections.
RECOVERED_BOTH = (
    OVERVIEW,
    response(concept("State Construction", excerpts=(P2_LEAD,))),
    response(concept("Dynamic Routing", excerpts=(Q1_LEAD,))),
)


class MethodRecoveryTests(MethodCoverageTestCase):
    def _recovery_rows(self, plan) -> dict[str, str]:
        rows: dict[str, str] = {}
        for line in plan.method_recovery:
            match = re.match(r"^.+?: \[ms-[0-9a-f]{8}\] (?P<heading>.+?) (?:chunk=|not targeted)", line)
            if match:
                rows[match["heading"]] = line
        return rows

    def test_subsections_sharing_one_chunk_are_recovered_one_call_each(self):
        self._source(METHOD_BODY)
        plan, provider = self._run(RECOVERED_BOTH, max_chunk_chars=4_000)
        ids = span_ids(METHOD_BODY)

        self.assertEqual(plan.stats.chunk_count, 1)
        self.assertEqual(plan.stats.recovery_calls, 2)
        self.assertEqual(plan.stats.llm_calls, 3)
        self.assertEqual(plan.stats.curator_calls, 0)
        self.assertEqual(plan.failures, [])
        self.assertEqual(plan.quality_gate_status, "pass")
        self.assertEqual(
            plan.method_recovery[0],
            f"{SOURCE_RELATIVE}: detected_subsections=2 covered_before_recovery=0 "
            "targeted_subsections=2 recovered_concepts=2 still_uncovered=0 recovery_calls=2",
        )
        rows = self._recovery_rows(plan)
        for heading, title in (
            ("state construction", "State Construction"),
            ("dynamic routing", "Dynamic Routing"),
        ):
            with self.subTest(heading=heading):
                self.assertRegex(
                    rows[heading],
                    rf"^{re.escape(SOURCE_RELATIVE)}: \[{ids[heading]}\] {heading} "
                    rf"chunk=subsection-{ids[heading][3:]}-[0-9a-f]{{16}} "
                    rf"-> {title}\(mechanism\) recovered$",
                )
        self.assertEqual(
            [line.split(": ", 1)[1].split(" [")[0] for line in plan.selected_concepts],
            ["Structured Reasoning Overview", "State Construction", "Dynamic Routing"],
        )
        coverage = "\n".join(plan.method_coverage)
        self.assertEqual(coverage.count("| candidates: title_cover=y evidence_cover=y "), 2)

    def test_targeted_request_carries_only_the_subsection_and_the_usual_limits(self):
        self._source(METHOD_BODY)
        _plan, provider = self._run(RECOVERED_BOTH, max_chunk_chars=4_000)
        first, second = provider.requests[1], provider.requests[2]

        for expected in ("##### 3.1 State Construction", P1_LEAD, P2_LEAD, '"state construction"'):
            self.assertIn(expected, first.prompt)
        for absent in ("##### 3.2 Dynamic Routing", Q1_LEAD, "#### 4 Experiment", E1_LEAD):
            self.assertNotIn(absent, first.prompt)
        for expected in ("##### 3.2 Dynamic Routing", Q1_LEAD, '"dynamic routing"'):
            self.assertIn(expected, second.prompt)
        for absent in (P1_LEAD, P2_LEAD, "#### 4 Experiment", E1_LEAD):
            self.assertNotIn(absent, second.prompt)
        for request in (first, second):
            self.assertIs(request.think, False)
            self.assertEqual(request.temperature, 0.0)
            self.assertEqual(request.max_output_tokens, AI_WIKI_MAX_OUTPUT_TOKENS)
            self.assertEqual(request.response_format, CONCEPT_EXTRACTION_SCHEMA)
            self.assertIn("not the complete source system", request.prompt)

    def test_long_subsection_is_sent_as_one_bounded_chunk(self):
        self._source(METHOD_BODY)
        _plan, provider = self._run(
            (
                OVERVIEW,
                response(),
                response(concept("Dynamic Routing", excerpts=(Q1_LEAD,))),
                response(),
                response(concept("State Construction", excerpts=(P1_LEAD,))),
            )
        )
        targeted = provider.requests[4].prompt
        body = targeted.split("<source_content>\n", 1)[1].split("\n</source_content>", 1)[0]

        self.assertLessEqual(len(body), 1_000)
        self.assertIn(P1_LEAD, body)
        self.assertNotIn(P2_LEAD, body)

    def test_covered_subsections_are_not_targeted(self):
        self._source(METHOD_BODY)
        for name, responses, calls in (
            ("title", SCENARIO_TITLE_COVER, 4),
            ("evidence", SCENARIO_PARAPHRASE, 5),
        ):
            with self.subTest(cover=name):
                plan, provider = self._run(responses)
                self.assertEqual(plan.stats.recovery_calls, 0)
                self.assertEqual(len(provider.requests), calls)
                self.assertEqual(
                    plan.method_recovery,
                    [
                        f"{SOURCE_RELATIVE}: detected_subsections=2 covered_before_recovery=2 "
                        "targeted_subsections=0 recovered_concepts=0 still_uncovered=0 "
                        "recovery_calls=0"
                    ],
                )

    def test_heading_without_body_is_not_targeted_and_the_gate_still_fails(self):
        body = "\n\n".join(
            [
                "#### 3 Methodology",
                "##### 3.1 State Construction",
                "##### 3.2 Dynamic Routing",
                paragraph(Q1_LEAD),
            ]
        )
        self._source(body)
        plan, provider = self._run(
            (OVERVIEW, response(), curator_response("Structured Reasoning Overview")),
            max_chunk_chars=4_000,
        )
        rows = self._recovery_rows(plan)

        self.assertEqual(plan.stats.recovery_calls, 1)
        self.assertEqual(len(provider.requests), 3)
        self.assertTrue(rows["state construction"].endswith("not targeted: no body text"))
        self.assertTrue(rows["dynamic routing"].endswith("-> (no concept)"))
        self.assertIn("recovered_concepts=0 still_uncovered=2", plan.method_recovery[0])
        self.assertEqual(plan.quality_gate_status, "failed")
        self.assertIn(
            "explicit methodology mechanisms detected but none selected",
            plan.quality_gate_reasons[0],
        )

    def test_targeted_calls_stop_at_the_limit(self):
        names = "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliet".split()
        body = "#### 3 Methodology\n\n" + "\n\n".join(
            f"##### 3.{index} {name} Module\n\n{name} module handles one step."
            for index, name in enumerate(names, start=1)
        )
        self._source(body)
        plan, provider = self._run(
            (
                OVERVIEW,
                *(response() for _ in range(MAX_METHOD_RECOVERY_CALLS)),
                curator_response("Structured Reasoning Overview"),
            ),
            max_chunk_chars=4_000,
        )
        rows = self._recovery_rows(plan)

        self.assertEqual(MAX_METHOD_RECOVERY_CALLS, 8)
        self.assertEqual(plan.stats.recovery_calls, 8)
        self.assertEqual(len(provider.requests), 10)
        self.assertIn("targeted_subsections=8", plan.method_recovery[0])
        self.assertIn("still_uncovered=10", plan.method_recovery[0])
        for heading in ("india module", "juliet module"):
            self.assertTrue(rows[heading].endswith("not targeted: limit of 8 calls reached"))
        self.assertTrue(rows["hotel module"].endswith("-> (no concept)"))

    def test_malformed_targeted_json_is_repaired_once(self):
        self._source(METHOD_BODY)
        valid = response(concept("State Construction", excerpts=(P2_LEAD,)))
        malformed = valid.replace('", "definition"', '" "definition"', 1)
        self.assertNotEqual(malformed, valid)
        plan, provider = self._run(
            (OVERVIEW, malformed, valid, response(concept("Dynamic Routing", excerpts=(Q1_LEAD,)))),
            max_chunk_chars=4_000,
        )

        self.assertEqual(plan.failures, [])
        self.assertEqual(plan.stats.json_repairs, 1)
        self.assertEqual(plan.stats.recovery_calls, 2)
        self.assertEqual(plan.stats.llm_calls, 4)
        self.assertIn("recovered_concepts=2", plan.method_recovery[0])

    def test_targeted_failures_are_technical_and_block_the_write(self):
        self._source(METHOD_BODY)
        two_concepts = response(
            concept("State Construction", excerpts=(P1_LEAD,)),
            concept("Record Assembler", excerpts=(P2_LEAD,)),
        )
        for name, targeted in (
            ("repair fails", ("{malformed", "{still-malformed")),
            ("more than one concept", (two_concepts,)),
        ):
            with self.subTest(case=name):
                plan, _provider = self._run((OVERVIEW, *targeted), max_chunk_chars=4_000, write=True)
                self.assertEqual(len(plan.failures), 1)
                self.assertRegex(
                    plan.failures[0],
                    r"subsection-[0-9a-f]{8}-[0-9a-f]{16}: targeted extraction for "
                    r"\[ms-[0-9a-f]{8}\] failed: StructuredOutputError",
                )
                self.assertTrue(plan.write_blocked)
                self.assertEqual(plan.method_recovery, [])
                self.assertEqual(list(self.ai_wiki.glob("*.md")), [])
                self.assertFalse((self.vault / ".automation" / "state" / "ai_wiki.json").exists())

    def test_targeted_timeout_is_counted_without_retry(self):
        self._source(METHOD_BODY)
        provider = FakeLLMProvider(response_texts=(OVERVIEW,))
        original = provider.generate
        calls = []

        def generate(request):
            calls.append(request)
            if len(calls) == 2:
                raise ProviderTimeoutError("timed out after 300s")
            return original(request)

        with patch.object(provider, "generate", side_effect=generate):
            from knowledge_os.ai_wiki import ScanScope, process_ai_wiki

            plan = process_ai_wiki(
                vault_root=self.vault,
                provider=provider,
                model_name="fake-local:latest",
                scope=ScanScope("all"),
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(plan.stats.timeout_failures, 1)
        self.assertEqual(plan.stats.recovery_calls, 1)
        self.assertIn("ProviderTimeoutError", plan.failures[0])

    def test_recovered_concept_merges_into_an_existing_identity(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(
            (
                response(concept("State Construction", role="core_concept", excerpts=("Not in the source.",))),
                response(concept("State Construction", excerpts=(P2_LEAD,))),
                response(concept("Dynamic Routing", excerpts=(Q1_LEAD,))),
            ),
            max_chunk_chars=4_000,
        )

        self.assertEqual(
            plan.candidate_concepts,
            [
                f"{SOURCE_RELATIVE}: Dynamic Routing [dynamic routing] role=mechanism",
                f"{SOURCE_RELATIVE}: State Construction [state construction] role=mechanism",
            ],
        )
        self.assertIn(
            "State Construction(mechanism, located 1/2)",
            "\n".join(plan.method_coverage),
        )
        self.assertIn("recovered_concepts=2", plan.method_recovery[0])

    def test_paraphrased_recovery_is_reported_but_the_title_gate_still_fails(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(
            (
                OVERVIEW,
                response(concept("Record Normalization Pipeline", excerpts=(P1_LEAD,))),
                response(concept("Handler Selection Policy", excerpts=(Q1_LEAD,))),
                curator_response(
                    "Structured Reasoning Overview",
                    "Record Normalization Pipeline",
                    "Handler Selection Policy",
                ),
            ),
            max_chunk_chars=4_000,
        )

        self.assertIn("recovered_concepts=2 still_uncovered=0", plan.method_recovery[0])
        self.assertEqual(
            "\n".join(plan.method_coverage).count(
                "| candidates: title_cover=n evidence_cover=y | selected: title_cover=n evidence_cover=y "
            ),
            2,
        )
        self.assertEqual(plan.quality_gate_status, "failed")

    def test_source_entity_returned_by_a_targeted_call_is_not_counted(self):
        self._source(METHOD_BODY, title="NEXUS: Neural Exchange for Unified Search")
        plan, _provider = self._run(
            (
                OVERVIEW,
                response(concept("NEXUS", excerpts=(P1_LEAD,))),
                response(concept("Dynamic Routing", excerpts=(Q1_LEAD,))),
            ),
            max_chunk_chars=4_000,
        )
        rows = self._recovery_rows(plan)

        self.assertTrue(
            rows["state construction"].endswith(
                "-> NEXUS(method_entity) not counted: role is not mechanism or component"
            )
        )
        self.assertIn("recovered_concepts=1 still_uncovered=1", plan.method_recovery[0])

    def test_written_notes_and_state_keep_subsection_provenance(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(RECOVERED_BOTH, max_chunk_chars=4_000, write=True)
        ids = span_ids(METHOD_BODY)
        note = (self.ai_wiki / "State Construction.md").read_text(encoding="utf-8")
        state = json.loads(
            (self.vault / ".automation" / "state" / "ai_wiki.json").read_text(encoding="utf-8")
        )
        chunk_ids = state["sources"][SOURCE_RELATIVE]["chunks"]

        self.assertFalse(plan.write_blocked)
        self.assertIn("[[source-one]]", note)
        self.assertRegex(note, rf"- Chunk: `subsection-{ids['state construction'][3:]}-[0-9a-f]{{16}}`")
        self.assertEqual(len(chunk_ids), 3)
        self.assertRegex(chunk_ids[0], r"^chunk-0001-[0-9a-f]{16}$")
        self.assertRegex(chunk_ids[1], rf"^subsection-{ids['state construction'][3:]}-[0-9a-f]{{16}}$")
        self.assertRegex(chunk_ids[2], rf"^subsection-{ids['dynamic routing'][3:]}-[0-9a-f]{{16}}$")

    def test_dry_run_recovery_writes_nothing(self):
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
        plan, _provider = self._run(RECOVERED_BOTH, max_chunk_chars=4_000)

        self.assertEqual(plan.stats.recovery_calls, 2)
        self.assertEqual(snapshot(), before)
        self.assertIn(source.relative_to(self.vault).as_posix(), before)

    def test_report_prints_recovery_section_without_source_text(self):
        self._source(METHOD_BODY)
        plan, _provider = self._run(RECOVERED_BOTH, max_chunk_chars=4_000)
        report = self._report(plan)

        self.assertIn("  recovery_calls: 2\n", report)
        self.assertIn(f"method_recovery:\n  - {SOURCE_RELATIVE}: detected_subsections=2 ", report)
        for text in (P1_LEAD, P2_LEAD, Q1_LEAD, E1_LEAD):
            self.assertNotIn(text, report)

    def test_source_without_method_subsections_has_no_recovery(self):
        self._source("#### Survey Taxonomy\n\nThis survey organizes prior work.")
        plan, provider = self._run((OVERVIEW,))

        self.assertEqual(plan.stats.recovery_calls, 0)
        self.assertEqual(plan.method_recovery, [])
        self.assertEqual(len(provider.requests), 1)


class CuratorEvidenceSignalTests(MethodCoverageTestCase):
    def _curator_candidates(self, prompt: str) -> dict[str, dict]:
        block = prompt.split("Candidates:\n", 1)[1].split("\n\nDeterministic duplicate-risk groups", 1)[0]
        return {item["title"]: item for item in json.loads(block)}

    def test_curator_sees_which_candidates_have_evidence_in_a_method_subsection(self):
        self._source(METHOD_BODY)
        plan, provider = self._run(
            (
                response(concept("State Construction", excerpts=(P1_LEAD,))),
                response(),
                response(concept("Dynamic Routing", excerpts=(Q1_LEAD,))),
                response(concept("Dynamic Routing Mechanism", excerpts=(E1_LEAD,))),
                curator_response("State Construction", "Dynamic Routing"),
            )
        )
        curator_prompt = provider.requests[-1].prompt
        candidates = self._curator_candidates(curator_prompt)

        self.assertEqual(plan.stats.recovery_calls, 0)
        self.assertEqual(plan.stats.curator_calls, 1)
        self.assertIn("duplicate-risk group", plan.curator_trigger_reason[0])
        self.assertEqual(
            candidates["State Construction"]["method_subsection_evidence"],
            ["state construction"],
        )
        self.assertEqual(
            candidates["Dynamic Routing"]["method_subsection_evidence"],
            ["dynamic routing"],
        )
        self.assertEqual(candidates["Dynamic Routing Mechanism"]["method_subsection_evidence"], [])
        self.assertIn(
            "prefer the candidate whose evidence lies in a methodology subsection",
            curator_prompt,
        )
        for text in (P1_LEAD, Q1_LEAD, E1_LEAD):
            self.assertNotIn(text, curator_prompt)

    def test_evidence_from_a_targeted_call_is_attributed_to_its_subsection(self):
        self._source(METHOD_BODY)
        plan, provider = self._run(
            (
                # A core_concept does not cover a subsection, so both get a targeted call.
                response(
                    concept("State Construction Mechanism", role="core_concept", excerpts=(E1_LEAD,))
                ),
                response(concept("State Construction", excerpts=(P2_LEAD,))),
                response(concept("Dynamic Routing", excerpts=(Q1_LEAD,))),
                curator_response("State Construction", "Dynamic Routing"),
            ),
            max_chunk_chars=4_000,
        )
        candidates = self._curator_candidates(provider.requests[-1].prompt)

        self.assertEqual(plan.stats.recovery_calls, 2)
        self.assertEqual(plan.stats.curator_calls, 1)
        self.assertEqual(
            {title: item["method_subsection_evidence"] for title, item in candidates.items()},
            {
                "Dynamic Routing": ["dynamic routing"],
                "State Construction": ["state construction"],
                "State Construction Mechanism": [],
            },
        )


class TargetedPromptTests(unittest.TestCase):
    def test_prompt_states_the_subsection_rules_and_embeds_only_the_chunk(self):
        chunk = chunk_source(source_note(METHOD_BODY), content="##### 3.1 State Construction\n\nBody text.")[0]
        system, prompt = build_targeted_extraction_prompt(chunk, subsection_heading="state construction")

        self.assertIn("Return only JSON matching the supplied schema", system)
        for expected in (
            "Return zero concepts when it does not.",
            "not the complete source system",
            "do not create a concept from the heading alone",
            "Copy every evidence excerpt verbatim from this subsection",
            'Subsection heading (weak supervision only):\n"state construction"',
            "<source_content>\n##### 3.1 State Construction\n\nBody text.\n</source_content>",
            json.dumps(CONCEPT_EXTRACTION_SCHEMA, ensure_ascii=False, separators=(",", ":")),
        ):
            self.assertIn(expected, prompt)


if __name__ == "__main__":
    unittest.main()

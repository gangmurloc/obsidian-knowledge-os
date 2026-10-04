# Obsidian Knowledge OS — Stage 1: methodology subsection span + evidence locator + method_coverage 진단 리포트

너는 이 vault에서 구현과 테스트를 맡는다. 설계 검토는 Claude(Cowork 프로젝트)가, 실제 Ollama 실행·`--write`·커밋은 사용자가 맡는다. 이번 작업은 아래 로드맵의 Stage 1 하나뿐이다.

## 0. 작업 환경

- 작업 디렉터리: `G:\내 드라이브\Obsidian\GILVault\GIL`
  - Google Drive 동기화 경로이고 한글과 공백이 들어 있다. 경로는 `pathlib.Path`로만 다루고, 파일 쓰기는 기존 atomic write 유틸을 쓴다.
- OS: Windows 11, 셸: PowerShell, Python 3.11.9 (3.14도 설치돼 있으니 기존 테스트와 같은 `python`을 쓴다)
- Local LLM: Ollama, model `qwen3.5:4b`, config `.automation/config/local_llm.json` (이번 작업에서 수정 금지)
- 이번 작업은 실제 Ollama를 호출하지 않는다. FakeLLMProvider와 synthetic fixture만 쓴다.

## 1. 먼저 읽을 파일 (순서대로)

1. `AGENTS.md`
2. `90_System/Docs/CLAUDE_CODE_HANDOFF.md` (현재 상태와 이전 계획. 단, 아래 3절에서 수정된 판단이 우선한다)
3. `90_System/Docs/ARCHITECTURE.md`, `DATA_CONTRACT.md`, `AI_BOUNDARIES.md`
4. `.automation/README.md`
5. 코드:
   - `.automation/knowledge_os/ai_wiki/preprocess.py`
   - `.automation/knowledge_os/ai_wiki/source.py`
   - `.automation/knowledge_os/ai_wiki/engine.py`
   - `.automation/knowledge_os/ai_wiki/quality.py`
   - `.automation/knowledge_os/ai_wiki/curator.py`
   - `.automation/knowledge_os/ai_wiki/models.py`
   - `.automation/knowledge_os/ai_wiki/schema.py` (읽기만)
   - `.automation/knowledge_os/cli.py` (`_print_ai_wiki_plan`)
6. 테스트: `.automation/tests/test_ai_wiki.py`, `.automation/tests/test_ai_wiki_preprocess.py`

`30_Resources/Sources/`, `30_Resources/Knowledge/`, 개인 노트 본문은 읽지 않는다. 구현에 필요 없다.

## 2. 현재 상태 (2026-10-04 기준)

### Git
- branch `main`, HEAD `cd892c2 Refine AI Wiki concept ontology rules`, 이전 안정 태그 `ai-wiki-v1` (`110bd8e`)
- HANDOFF 작성 시점의 미커밋 변경 (semantic quality gate, method-aware weak supervision):
  - 수정: `.automation/README.md`, `ai_wiki/curator.py`, `ai_wiki/engine.py`, `ai_wiki/models.py`, `ai_wiki/preprocess.py`, `ai_wiki/schema.py`, `knowledge_os/cli.py`, `tests/test_ai_wiki.py`, `tests/test_ai_wiki_preprocess.py`, `90_System/Docs/ARCHITECTURE.md`
  - 신규: `ai_wiki/quality.py`
- 사용자에게 이 변경을 checkpoint 커밋하도록 권했다. 커밋 여부는 시작 체크리스트의 `git status`로 확인한다.

### 테스트
- HANDOFF 기준 `python -m unittest discover -s .automation/tests` 133개 통과
- Claude(Cowork)가 클라우드 사본(Python 3.13)에서 돌렸을 때 AI-Wiki/LLM 테스트 121개 통과. `test_paper_ingest`는 pymupdf가 없어 실행하지 못함

### 최신 실제 dry-run (A-MEM, 사용자 실행)
명령: `python ".automation\run.py" ai-wiki scan --source "A-MEM.md"`
- source 93,064자 → processing view 45,097자, chunk 13개 (평균 3,534자, 최대 3,997자)
- llm_calls 14, json_repairs 0, timeout 0, curator_calls 1, technical failure 없음
- 감지된 methodology subsection: `note construction`, `link generation`, `memory evolution`, `retrieve relative memory`
- 후보:
  - `Evolutionary Memory Update` role=method_entity
  - `A-MEM` role=method_entity, primary_source_entity=true
  - `A-MEM Memory Evolution Mechanism` role=method_entity
  - `A-MEM Scaling Analysis` role=analysis
- curator 선택: `A-MEM`, `Evolutionary Memory Update`
- quality_gate: failed — `explicit methodology mechanisms detected but none selected` (`--write`였다면 exit 6으로 차단)

## 3. 설계 검토에서 확인한 사실 (코드로 확인함. 너도 재확인할 것)

HANDOFF는 병목을 "general extraction이 named mechanism 후보를 만들지 못함"으로 진단하고, 다음 단계로 subsection-targeted extraction을 제안했다. 그 전에 다음 세 가지가 확인됐다.

### F1. cover 판정이 제목과 heading의 일치에 의존한다
- `quality.py`의 `explicit_method_coverage_failure`는 role ∈ {mechanism, component}이면서 `candidate_matches_methodology_subsection`이 참인 후보가 하나도 없으면 실패로 본다.
- `candidate_matches_methodology_subsection`은 `concept_comparison_signatures(title)`에 `concept_identity(heading)`이 들어 있어야 참이다. 이 시그니처는 source alias 접두어와 wrapper 접미어(Architecture/Framework/System/Mechanism/Method/Approach)를 뗀 형태다.
- 확인 결과 (source title을 `A-MEM: Agentic Memory for LLM Agents`로 가정):
  - `A-MEM Memory Evolution Mechanism` → {`memory evolution`, `mem memory evolution`} → heading과 일치
  - `Evolutionary Memory Update` → {`evolutionary memory update`} → 불일치
  - `Memory Evolution Process` → {`memory evolution process`} → 불일치
  - `Agentic Note Construction` → {`agentic note construction`} → 불일치
- 즉 heading을 제목으로 거의 그대로 복사해야만 cover로 인정된다. 이는 "heading은 weak supervision일 뿐이고 title로 복사하지 않는다"는 원칙과 충돌한다. targeted extraction이 좋은 paraphrase 제목으로 후보를 복구해도 gate가 계속 실패할 수 있다.

### F2. role 승격이 chunk 안에 heading 줄이 있는지에 의존한다 (가설 A의 근거)
- `engine.py`의 `_apply_source_context_roles`는 method_entity 후보를 mechanism으로 승격할 때 두 조건을 모두 요구한다.
  - (a) 제목 시그니처가 heading과 일치한다.
  - (b) 그 후보를 뽑은 chunk의 `_chunk_section_names`(chunk 텍스트에 실제로 들어 있는 heading 줄)에 그 heading이 있다.
- subsection 본문이 다음 chunk로 이어지면 그 chunk에는 heading 줄이 없어 (b)가 실패한다.
- `A-MEM Memory Evolution Mechanism`은 (a)를 만족하는데도 method_entity로 남았다. (b) 실패가 원인일 수 있지만, 실제 chunk 배치를 보지 않았으므로 아직 확인되지 않았다.

### F3. method root 감지 범위가 좁다
- `preprocess.py`의 `detect_methodology_subsections`는 heading이 method/methods/methodology/approach/architecture일 때만 root로 본다. 길이 6 이상인 이름은 edit distance 2 이하까지 허용한다.
- 확인 결과:
  - `3 Methodolodgy` → 감지됨
  - `3 Our Approach`, `3 Proposed Method`, `3 Framework`, 시스템 이름 섹션(`3 HyperGraphRAG`) → 모두 `()`
- 감지 결과가 0이면 coverage 검사가 조용히 꺼져 gate가 통과한다. 이번 Stage에서는 고치지 않는다(Stage 4 대상). report에서 보이게만 한다.

## 4. 전체 로드맵 (이번에는 Stage 1만 한다)

- **Stage 0 (사용자):** 현재 미커밋 변경 checkpoint 커밋
- **Stage 1 (이번 작업):** subsection span, evidence locator, method_coverage 진단 리포트. 동작 변경 없음, LLM 호출 추가 없음.
- **Stage 2 (다음, 데이터 확인 후 결정):** cover 정의를 evidence-anchored로 교체한다(role 승격과 quality gate 모두). mechanism/component role 요건은 유지한다.
- **Stage 3:** Stage 2 이후에도 uncovered인 subsection만 대상으로 bounded targeted extraction. HANDOFF의 targeted extraction 설계 원칙을 재사용하고 cover 정의만 바꾼다.
- **Stage 4:** method root 감지 확장(Our Approach, Proposed Method, Framework, source alias 섹션 등), 구조가 다른 논문 2~3편으로 dry-run, 소규모 gold set으로 recall 측정
- **이후:** quality gate pass와 사람 검토를 거쳐 첫 `--write`, 그다음 Knowledge 승격 제안 리포트

Stage 1의 목적은 A-MEM dry-run에서 다음 두 가설 중 무엇이 맞는지 판별할 데이터를 만드는 것이다.
- **가설 A:** mechanism 후보는 있었는데 role 단계(F2)와 cover 정의(F1) 때문에 놓쳤다 → Stage 2(결정론)로 해결
- **가설 B:** 해당 subsection 안에 evidence를 둔 후보가 아예 없다 → Stage 3(targeted extraction)이 필요

## 5. 목표 (한 문장)

기존 동작을 하나도 바꾸지 않고, methodology subsection의 문자 span, chunk와 subsection의 offset 기반 연결, evidence excerpt의 결정론적 위치 찾기를 구현해 dry-run report에 `method_coverage` 진단을 추가한다.

## 6. 하지 말 것 (non-goals)

- 다음은 바꾸지 않는다: role 할당, curator의 trigger·prompt·선택, quality gate 판정, extraction prompt/schema, chunking 결과(chunk 텍스트·identifier)
- targeted extraction 구현과 method root 감지 확장은 하지 않는다 (Stage 3, 4)
- LLM 호출을 추가하지 않고, 실제 Ollama나 A-MEM을 실행하지 않는다
- Source, Knowledge, AI-Wiki, `origin: me` 노트를 수정하지 않고, processing state 기록 방식도 바꾸지 않는다
- 특정 논문 제목이나 개념 이름을 하드코딩하지 않는다
- `.automation/config/*`를 수정하지 않는다
- `git commit`/`tag`/`push`를 하지 않고, 미커밋 변경을 되돌리지 않는다(`reset`, `checkout`, `stash` 금지)
- 관련 없는 파일의 line ending을 일괄 변경하지 않는다
- HANDOFF 등 기존 문서를 직접 수정하지 않는다. README에 report 설명을 추가해야 하면 diff로 제안만 한다.

## 7. 판정 용어 정의

**span(S)**
- processing view content에서 subsection S의 heading 줄 시작 offset부터, 아래 종료 지점 중 가장 먼저 오는 것 직전까지다.
- S의 heading이 번호를 가졌고 다음 heading도 번호를 가졌으면 번호만으로 판단한다. 번호 깊이가 S 이하인 heading에서 끝난다(예: 3.1의 span은 3.2나 4에서 끝나고 3.1.1에서는 끝나지 않는다).
- 그 밖의 경우는 Markdown 레벨로 판단한다. S와 같은 레벨이거나 더 높은 레벨의 heading에서 끝난다.
- method root가 끝나는 지점과 content 끝에서도 끝난다.
- `### Page N` 줄은 span을 끝내지 않는다.
- 형제 subsection의 span은 서로 겹치지 않는다. 중첩 subsection(3.1 안의 3.1.1)은 부모 span에 포함된다.

**pages(S)**: S heading 위치 직전의 마지막 `### Page N` 번호, 그리고 span 안에 있는 모든 `### Page N` 번호

**normalize(text)**: NFKC → casefold → Markdown 강조기호(`*`, `_`, `` ` ``) 제거 → 연속 공백과 개행을 공백 하나로. 정규화할 때 원래 offset으로 돌아가는 매핑 배열을 함께 만든다.

**located(e)**
- evidence e의 `source_excerpt`를 normalize한 문자열이 normalize한 processing view content의 부분 문자열이면 located다.
- 여러 곳에서 발견되면 `e.chunk_id`에 해당하는 chunk 범위 안의 위치를 우선하고, 그래도 여럿이면 첫 위치를 쓴다. 찾은 위치는 원래 offset으로 되돌린다.
- fuzzy match는 쓰지 않는다.
- 정규화 결과가 빈 문자열이거나 omission marker(`> [... omitted from AI extraction`) 안에서만 발견되면 located가 아니다.

**title_anchored_cover(S, C)**: 현재 `quality.py` 규칙 그대로. role(C) ∈ {mechanism, component}이고 `concept_comparison_signatures(C.title)`에 `concept_identity(S.canonical_heading)`이 들어 있다.

**evidence_anchored_cover(S, C)**: role(C) ∈ {mechanism, component}이고, C의 evidence 중 located 위치가 span(S) 안에 있는 것이 1개 이상이다.

**heading_chunks(S)**: 기존 방식. chunk 텍스트에 S의 heading 줄이 들어 있는 chunk들(`_chunk_section_names` 기준)

**offset_chunks(S)**: chunk의 [start, end) 범위가 span(S)와 겹치는 chunk들

**후보 집합**
- `candidates`: `_apply_source_context_roles` 직후의 전체 집합 (`plan.candidate_concepts`와 같은 집합)
- `selected`: 최종 선택 집합 (`plan.selected_concepts`와 같은 집합)

## 8. 필수 요구사항 (각각 테스트로 검증한다)

- **R1.** `preprocess.py`에 frozen dataclass `MethodSubsection`을 추가한다. 필드는 `subsection_id`, `canonical_heading`, `original_heading`, `start`, `end`, `pages: tuple[int, ...]`.
- **R2.** `AIProcessingView`에 `method_subsection_spans: tuple[MethodSubsection, ...] = ()`를 추가한다. 기존 `methodology_subsections: tuple[str, ...]`는 유지하고, 값은 spans의 canonical_heading을 순서대로 놓고 기존과 같은 규칙으로 중복을 없앤 것이다. 기존 호출부와 테스트는 고치지 않아도 통과해야 한다.
- **R3.** `subsection_id`는 canonical_heading과 출현 순번으로 만든 짧은 안정 해시다(예: `"ms-" + sha256 앞 8자리`). 같은 입력이면 같은 id가 나오고, heading이 바뀌면 다른 id가 나온다.
- **R4.** processing view content 문자열은 한 글자도 바뀌지 않는다. 그러므로 `AI_PROCESSING_VIEW_VERSION`(현재 6)도 올리지 않는다.
- **R5.** processing view 안에서 chunk의 [start, end) offset을 얻는 방법을 추가한다.
  - chunk 텍스트를 content에서 문자열 검색하는 방식은 overlap과 반복 문단 때문에 모호하므로 쓰지 않는다. `chunk_source`가 블록을 조립할 때 offset을 함께 계산하고, oversized block을 나눌 때도 offset을 유지한다.
  - `SourceChunk`에 필드를 추가한다면 기본값을 둬서 기존 생성 코드와 테스트가 깨지지 않게 한다.
  - chunk 텍스트와 identifier는 바뀌면 안 된다.
- **R6.** 결정론 함수 `locate_excerpt(excerpt, content, *, preferred_range=None) -> tuple[int, int] | None`를 추가한다. 동작은 7절 located 정의 그대로다.
- **R7.** `engine.py`는 기존 흐름을 그대로 두고, source별로 method_coverage 진단을 계산해 `ProcessingPlan`의 새 필드(예: `method_coverage: list[str]`, `evidence_locatability: list[str]`)에 담는다. 진단 계산은 role, curator, gate 결과를 읽기만 한다.
- **R8.** `cli.py`의 `_print_ai_wiki_plan`에 `method_coverage:`와 `evidence_locatability:` 섹션을 추가한다.
  - subsection마다 한 줄:
    `<source>: [<subsection_id>] <canonical_heading> pages=<..> heading_chunks=<..> offset_chunks=<..> | candidates: title_cover=<y/n> evidence_cover=<y/n> | selected: title_cover=<y/n> evidence_cover=<y/n> | in_span: <title>(<role>, located <k>/<n>), ...`
  - evidence_locatability는 source마다 한 줄:
    `<source>: located <k>/<n> evidence across <m> candidates`
  - methodology subsection이 0개인 source는 `<source>: no methodology subsections detected`를 출력한다 (F3 상황이 report에 보이게 하기 위해서다).
- **R9.** report에는 Source 본문, subsection body, excerpt 원문을 넣지 않는다. id, heading, title, role, 숫자만 넣는다.
- **R10.** 출력 상한: source당 subsection 행은 최대 20개(넘으면 `... (+N more)`), 행마다 in_span 후보는 최대 5개(넘으면 `+N more`).
- **R11.** 기존 모든 fixture에서 다음 값이 변경 전과 같아야 한다: `quality_gate_status`, `quality_gate_reasons`, `curator_trigger_reason`, `candidate_concepts`의 role 표기, `selected_concepts`, `stats.llm_calls`, exit code.
- **R12.** dry-run에서 AI-Wiki note, processing state, diagnostics 파일을 새로 쓰지 않는다. 기존 malformed JSON diagnostic 동작은 그대로 둔다.

## 9. 상한

- 추가 LLM 호출: 0회
- 진단 계산은 source 길이에 대해 대략 선형으로 유지한다. 정규화한 content는 source당 한 번만 만들고, excerpt마다 content 전체를 다시 정규화하지 않는다.

## 10. 최소 테스트 (FakeLLMProvider + synthetic fixture만)

1. 한 chunk 안에 named method subsection이 3개 있으면 span 3개가 서로 겹치지 않고, 각 start가 heading 줄 위치와 맞는다.
2. subsection 본문이 다음 chunk로 넘어가 그 chunk에 heading 줄이 없으면, heading_chunks에는 첫 chunk만, offset_chunks에는 두 chunk가 모두 들어간다 (F2 재현).
3. experiment/evaluation/implementation subsection은 span 대상이 아니다.
4. `### Page N` 줄을 지나도 span이 이어지고, pages에 두 페이지가 모두 들어간다.
5. 번호 체계(`3`, `3.1`, `3.1.1`, `3.2`, `4`)와 Markdown 레벨이 섞여 있어도 span 경계와 중첩 규칙이 맞다.
6. subsection_id는 다시 실행해도 같고, heading을 바꾸면 달라진다.
7. `methodology_subsections`는 하위 호환된다(기존 테스트 기대값 그대로).
8. processing view content가 바뀌지 않는다(R4). chunk 텍스트와 identifier도 바뀌지 않는다(R5).
9. `locate_excerpt`:
   - 대소문자, 공백, 개행, 강조기호 차이는 located
   - paraphrase는 None
   - 빈 문자열은 None
   - omission marker 안에만 있으면 None
   - 같은 문장이 두 번 나오면 preferred_range 안의 위치를 반환
10. paraphrase 제목 + role=mechanism + span 안 evidence → evidence_cover=y, title_cover=n
11. role=method_entity + span 안 evidence → evidence_cover=n
12. evidence가 다른 subsection의 span에 있으면 그 subsection만 cover된다.
13. methodology subsection이 0개인 source는 `no methodology subsections detected`를 출력한다.
14. report에 excerpt 원문이 들어가지 않는다(R9).
15. 출력 상한(R10)이 동작한다.
16. report-only 회귀(R11): 기존 대표 fixture들의 gate, curator, role, selected, llm_calls, exit code가 같다.
17. dry-run에서 아무것도 쓰지 않고(R12), Source/Knowledge fixture 파일 해시가 그대로다.
18. 기존 테스트가 전부 통과한다.

## 11. 시작 체크리스트

    git status --short
    python -m unittest discover -s ".automation\tests" -v
    git diff --check

- `git status`에 2절의 미커밋 변경이 그대로 남아 있으면, 코드를 고치기 전에 사용자에게 Stage 0 checkpoint 커밋을 먼저 할지 묻고 답을 기다린다. 사용자가 그대로 진행하라고 하면 그 위에서 작업한다. 어떤 경우에도 직접 커밋하거나 되돌리지 않는다.
- baseline 테스트 수가 133과 다르면 그 수를 기록하고 원인을 보고한다. 이 수가 수정 전 기준선이다.
- 테스트를 먼저 쓰고 실패를 확인한 뒤 구현한다.

## 12. 완료 보고 (이 순서로)

1. 조사 결과: F1~F3을 코드에서 다시 확인한 결과 (다르면 근거와 함께)
2. 수정·생성 파일 목록과 파일별 변경 요약
3. MethodSubsection 구조와 span 경계 규칙 (fixture 예시 포함)
4. chunk offset 계산 방식과 하위 호환 처리
5. `locate_excerpt`의 정규화와 offset 복원 방식
6. `method_coverage`/`evidence_locatability` report 예시 (fixture 출력 그대로)
7. 테스트 결과: 전체 수, 새로 추가한 수, 실패 0개 확인, `git diff --check` 결과
8. 실제 Ollama 호출 여부 (없어야 한다)
9. README에 report 설명 추가가 필요하면 diff 제안 (직접 수정하지 않는다)
10. 사용자가 실행할 정확한 dry-run 명령 (아래 둘)

로컬(데스크톱 Ollama):

    python ".automation\run.py" ai-wiki scan --source "A-MEM.md"

연구실 서버 Ollama를 SSH 터널(로컬 11435 → 서버 127.0.0.1:11434)로 쓸 때:

    python ".automation\run.py" ai-wiki scan --source "A-MEM.md" --config ".automation\config\local_llm.server.json"

참고: 데스크톱 GPU가 GTX 1060 3GB라 로컬 dry-run이 느리다. 그래서 사용자는 연구실 서버(RTX A5000)의 Ollama를 SSH 터널로 쓰는 방안을 준비하고 있다. 서버에는 아직 `qwen3.5:4b`가 없고(`qwen3.5:27b`만 있음), `local_llm.server.json`은 사용자가 직접 만든다. 이 방식을 허용할지는 `AI_BOUNDARIES.md`와 HANDOFF에 따로 기록할 예정이며, 이번 작업 범위가 아니다.

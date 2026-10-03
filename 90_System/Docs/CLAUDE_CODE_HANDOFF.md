---
type: system
origin: ai
knowledge_status: processed
domain:
  - knowledge-management
  - software-engineering
created: 2026-10-04
updated: 2026-10-04
human_verified: false
---

# Claude Code Handoff

## 문서 목적

이 문서는 Obsidian Knowledge OS 프로젝트를 Claude Code에 인계하기 위한 단일 진입점이다. 지금까지 구현한 기능, 운영 경계, Git 상태, 실제 검증 결과, 현재 실패 원인, 다음 구현 목표와 복사 가능한 작업 프롬프트를 포함한다.

작업 시작 전에 반드시 다음 원본 문서도 읽는다.

- `/AGENTS.md`
- `/90_System/Docs/ARCHITECTURE.md`
- `/90_System/Docs/DATA_CONTRACT.md`
- `/90_System/Docs/AI_BOUNDARIES.md`
- `/.automation/README.md`

## 한 줄 요약

PDF에서 AI-Wiki까지 이어지는 local-first 파이프라인은 기술적으로 동작한다. 현재 병목은 여러 method subsection이 하나의 일반 chunk에 섞일 때 `1 concept per chunk` 제약 때문에 명시적 mechanism이 후보로 생성되지 않는 문제다. Curator와 semantic quality gate는 이 문제를 정상적으로 감지하지만, curator는 기존 후보만 선택할 수 있으므로 누락된 mechanism을 복구할 수 없다.

## 절대 규칙

1. `30_Resources/Sources/`는 외부 원본이다. 자동 수정하지 않는다.
2. `30_Resources/Knowledge/`와 `origin: me` 노트 본문은 자동 수정하지 않는다.
3. AI가 쓸 수 있는 지식 영역은 `30_Resources/AI-Wiki/`뿐이다.
4. PDF 원본은 `_assets/PDF/`에 보존한다.
5. dry-run이 기본이며 삭제, bulk rename, bulk move를 자동 수행하지 않는다.
6. 외부 LLM API를 사용하지 않는다. Localhost Ollama만 허용한다.
7. API key나 credential을 Markdown에 저장하지 않는다.
8. AI 결과는 Source, chunk, evidence provenance를 유지한다.
9. Source title이나 특정 논문의 concept 이름을 생산 코드에 하드코딩하지 않는다.
10. Semantic similarity만으로 concept을 자동 merge하지 않는다.
11. Technical failure 또는 quality-gate failure가 하나라도 있으면 전체 write와 state update를 차단한다.
12. 실제 A-MEM/Ollama 실행은 사용자가 담당한다. 구현 단계에서는 fixture와 FakeLLMProvider만 사용한다.

## 환경

- OS: Windows 11 Enterprise 64-bit
- Vault: `G:\내 드라이브\Obsidian\GILVault\GIL`
- Google Drive 동기화 경로이므로 모든 write는 same-filesystem temp file과 atomic replace를 사용한다.
- Python: 기본 3.11.9, 3.14도 설치됨
- Local LLM provider: Ollama
- Endpoint: `http://localhost:11434`
- Model: `qwen3.5:4b`
- Temperature: `0.0`
- Timeout: `180`초
- Config: `.automation/config/local_llm.json`
- 외부 network LLM 호출: 없음

주요 로컬 의존성:

- Ollama
- PyMuPDF4LLM
- PyMuPDF / PyMuPDF Layout
- pypdf legacy fallback
- PyYAML
- Python standard-library HTTP client

## Git 상태

현재 branch와 checkpoint:

```text
branch: main
HEAD: cd892c2 Refine AI Wiki concept ontology rules
previous stable tag: ai-wiki-v1
tag commit: 110bd8e Complete AI Wiki v1 end-to-end pipeline
```

Semantic quality gate와 method-aware weak supervision 변경은 아직 커밋되지 않았다. 현재 수정/생성 파일:

```text
M  .automation/README.md
M  .automation/knowledge_os/ai_wiki/curator.py
M  .automation/knowledge_os/ai_wiki/engine.py
M  .automation/knowledge_os/ai_wiki/models.py
M  .automation/knowledge_os/ai_wiki/preprocess.py
M  .automation/knowledge_os/ai_wiki/schema.py
M  .automation/knowledge_os/cli.py
M  .automation/tests/test_ai_wiki.py
M  .automation/tests/test_ai_wiki_preprocess.py
M  90_System/Docs/ARCHITECTURE.md
?? .automation/knowledge_os/ai_wiki/quality.py
```

이 변경을 되돌리거나 덮어쓰지 말고 현재 상태 위에서 작업한다.

## 지금까지의 진행 과정

### 1. Vault 운영 헌법과 구조

- PARA, Personal Knowledge Graph, External Sources, AI-Wiki, Human Knowledge 경계를 정의했다.
- `AGENTS.md`, `ARCHITECTURE.md`, `DATA_CONTRACT.md`, `AI_BOUNDARIES.md`를 만들었다.
- Source, AI-Wiki, Knowledge의 ownership과 write 권한을 분리했다.
- 목표 폴더 구조와 property contract를 구축했다.

### 2. PDF ingestion

- `_assets/PDF/`의 PDF를 `30_Resources/Sources/Papers/` Markdown으로 정규화한다.
- 기본 extractor를 PyMuPDF4LLM로 변경했다.
- pypdf는 explicit legacy fallback으로 유지한다.
- dry-run, create, explicit replace 흐름을 제공한다.
- replace 시 custom frontmatter, `My Highlights`, `Related`를 보존한다.
- Google Drive를 고려한 atomic write를 사용한다.
- image-only/low-text PDF는 빈 Source를 만들지 않고 실패한다.

### 3. Markdown parser 안전성

- PDF plain text의 `\<`, `\>` artifact를 복원한 뒤 Content body에서만 `<`, `>`를 HTML entity로 변환한다.
- YAML frontmatter와 pipeline이 생성한 Markdown 구조에는 global replace를 적용하지 않는다.
- `k < n`, `a < b`, `x > y`, `\<unknown` 회귀 테스트가 있다.

### 4. Local LLM provider

- `LLMProvider` abstraction을 만들었다.
- `OllamaProvider`와 `FakeLLMProvider`를 구현했다.
- Loopback endpoint만 허용하며 외부 endpoint, redirect, proxy, cloud model을 차단한다.
- `llm-status`, `llm-test` CLI를 제공한다.
- Model 미지정 상태에서는 자동 선택이나 다운로드를 하지 않는다.

### 5. AI-Wiki v1

기본 흐름:

```text
Source Markdown
-> validation
-> in-memory processing view
-> chunking
-> Local LLM structured extraction
-> deterministic identity deduplication
-> source-level curator
-> semantic quality gate
-> change plan
-> explicit atomic write
```

- AI-Wiki note에 `origin: ai`, `knowledge_status: processed`, `human_verified: false`를 사용한다.
- Source Wikilink, evidence excerpt, chunk ID, backend/model provenance를 기록한다.
- Existing AI-Wiki update 시 protected metadata와 provenance를 보존한다.
- `supports`, `extends`, `contradicts`를 보수적으로 분류한다.
- dry-run에서는 note와 processing state를 쓰지 않는다.

### 6. Structured-output 안정화

- Extraction schema를 Ollama structured output format으로 전달한다.
- `think=false`, `temperature=0`, output token limit 1024를 사용한다.
- JSON syntax failure일 때 같은 local model로 syntax-only repair를 최대 1회 실행한다.
- Repair 결과도 전체 schema validation을 통과해야 한다.
- Parse failure diagnostic은 `.automation/state/diagnostics/`에만 저장한다.
- Diagnostic에는 Source 본문 전체, credential, 절대 경로, chain-of-thought를 저장하지 않는다.
- Timeout, malformed JSON, truncation은 positional fallback 없이 failure 처리한다.

### 7. Source preprocessing

- References/Bibliography 제외
- Contents/Table of Contents 제외
- NeurIPS/Paper Checklist 제외
- Appendix 유지
- 일반 prose와 heading 유지
- Figure caption 유지, raw figure/OCR text 제외
- Valid GFM table 유지, malformed/numeric-density table 제외
- Flattened/missing formula를 provenance marker로 대체
- Source Markdown은 수정하지 않음
- Processing view version은 현재 `6`

### 8. Chunking과 source-level selection

- 기본 chunk 최대 크기: 4,000 characters
- Paragraph/section boundary 우선
- Whole-paragraph overlap 최대 200 characters
- 현재 extraction 상한: chunk당 concept 1개
- 최종 Source당 concept 최대 12개
- 후보가 12개를 넘을 때 curator를 1회 호출한다.
- Curator는 후보 선택만 가능하며 새 concept 생성, rename, merge, 내용 변경은 금지한다.

### 9. Ontology cleanup

- Unicode/case/punctuation/hyphen/whitespace/leading article을 deterministic identity로 정규화한다.
- Contextual wrapper suffix 비교:
  - Architecture
  - Framework
  - System
  - Mechanism
  - Method
  - Approach
- Wrapper는 duplicate-risk 비교에서만 사용하며 title에서 전역 삭제하지 않는다.
- Source title에서 alias를 일반적으로 유도하지만 duplicate detection 용도로만 사용한다.
- Role:
  - `core_concept`
  - `mechanism`
  - `component`
  - `method_entity`
  - `dataset`
  - `metric`
  - `baseline`
  - `analysis`
- Dataset/metric은 Source 자체의 contribution일 때 예외적으로 유지할 수 있다.
- Baseline/analysis는 기본 final concept에서 제외한다.

### 10. Method-aware weak supervision과 semantic quality gate

- Method/Methodology/Approach/Architecture 하위 named subsection을 감지한다.
- Markdown heading level과 `3`, `3.1` 같은 numbered hierarchy를 함께 사용한다.
- OCR typo를 일반적인 edit-distance 기준으로 허용한다.
- Experiment, dataset, evaluation, implementation, result, ablation, analysis, hyperparameter subsection은 method signal에서 제외한다.
- Heading은 weak supervision일 뿐 concept을 강제 생성하지 않는다.
- Exact Source alias만 internal `primary_source_entity`가 될 수 있다.
- Alias prefix 뒤에 의미 있는 mechanism phrase가 있으면 primary entity로 collapse하지 않는다.
- 추가 curator trigger:
  - source-entity dominance
  - explicit-method coverage failure
- Quality gate 검사:
  - excessive source-entity dominance
  - multiple primary source entities
  - unresolved duplicate-risk after curation
  - explicit methodology mechanisms detected but none selected
  - only generic/source-name concepts selected
- Quality failure는 technical failure와 별도로 보고한다.
- Quality failure exit code는 `6`, technical failure는 `5`다.
- 어느 한 Source라도 실패하면 전체 `--write`와 state update를 차단한다.

## 핵심 코드 지도

- `.automation/run.py`: CLI entrypoint
- `.automation/knowledge_os/cli.py`: command parsing과 report 출력
- `.automation/knowledge_os/paper_ingest.py`: PDF ingestion orchestration
- `.automation/knowledge_os/pdf_extractors.py`: extractor abstraction
- `.automation/knowledge_os/io_utils.py`: atomic write
- `.automation/knowledge_os/llm/base.py`: provider request/response contract
- `.automation/knowledge_os/llm/ollama.py`: localhost Ollama transport
- `.automation/knowledge_os/llm/fake.py`: unit-test provider
- `.automation/knowledge_os/ai_wiki/source.py`: Source validation과 chunking
- `.automation/knowledge_os/ai_wiki/preprocess.py`: in-memory filtering과 method subsection detection
- `.automation/knowledge_os/ai_wiki/schema.py`: extraction schema, parser, repair prompt, merge
- `.automation/knowledge_os/ai_wiki/ontology.py`: identity와 relation suggestions
- `.automation/knowledge_os/ai_wiki/curator.py`: duplicate risk와 source-level selection
- `.automation/knowledge_os/ai_wiki/quality.py`: semantic quality gate
- `.automation/knowledge_os/ai_wiki/engine.py`: end-to-end orchestration
- `.automation/knowledge_os/ai_wiki/render.py`: AI-Wiki Markdown rendering
- `.automation/tests/test_ai_wiki.py`: extraction/selection/write safety tests
- `.automation/tests/test_ai_wiki_preprocess.py`: processing view와 method detection tests

## 최신 테스트 상태

2026-10-04 기준:

```text
python -m unittest discover -s .automation/tests
Ran 133 tests in 13.703s
OK
```

Unit test는 실제 Ollama를 호출하지 않는다. 작은 synthetic fixture와 FakeLLMProvider만 사용한다.

## 실제 A-MEM dry-run 결과

사용자가 실행한 명령:

```powershell
python ".automation\run.py" ai-wiki scan --source "A-MEM.md"
```

주요 통계:

```text
mode: dry-run
source_characters: 93064
processing_characters: 45097
chunk_count: 13
average_chunk_size: 3534.2
maximum_chunk_size: 3997
llm_calls: 14
json_repairs: 0
timeout_failures: 0
curator_calls: 1
failures: none
```

정상 감지된 methodology subsection:

```text
note construction
link generation
memory evolution
retrieve relative memory
```

추출 후보:

```text
Evolutionary Memory Update       role=method_entity
A-MEM                           role=method_entity primary_source_entity=true
A-MEM Memory Evolution Mechanism role=method_entity
A-MEM Scaling Analysis          role=analysis
```

Curator 선택:

```text
A-MEM
Evolutionary Memory Update
```

Quality gate:

```text
status: failed
reason: explicit methodology mechanisms detected but none selected
```

이 결과는 새 quality gate가 오작동한 것이 아니다. Pipeline, preprocessing, curator trigger, role filtering, quality 판정이 의도대로 동작했고 extraction 단계가 named mechanism 후보를 만들지 못한 것을 차단했다.

`write_blocked: false`였던 이유는 dry-run이라 write를 요청하지 않았기 때문이다. 같은 상태로 `--write`하면 실제 write가 차단된다.

## 현재 병목의 원인

현재 일반 chunk에는 여러 method subsection이 함께 들어갈 수 있지만 structured extraction은 chunk당 concept을 최대 하나만 허용한다.

```text
one general chunk
  - Note Construction
  - Link Generation
  - Memory Evolution
  - Retrieve Relative Memory

schema max concepts per chunk = 1
```

따라서 prompt에 method heading을 알려줘도 작은 4B model은 Source system name이나 하나의 포괄적 concept만 반복해서 반환할 수 있다.

Curator는 기존 candidate만 선택할 수 있으므로 누락된 mechanism을 생성해서 복구할 수 없다. Quality gate를 느슨하게 하거나 curator에게 새 concept 생성을 허용하면 안 된다.

## 다음 목표

일반 chunk extraction은 유지하되, 명시적인 core-method subsection 중 아직 mechanism/component candidate로 cover되지 않은 subsection만 대상으로 bounded targeted extraction을 추가한다.

권장 흐름:

```text
processing view
-> general chunk extraction
-> deterministic deduplication
-> methodology subsection coverage 확인
-> uncovered subsection targeted extraction
-> candidate merge
-> role/source-entity correction
-> curator
-> semantic quality gate
-> change plan
```

### Targeted extraction 설계 원칙

1. A-MEM 또는 특정 mechanism 이름을 코드에 하드코딩하지 않는다.
2. Method/Methodology/Approach/Architecture 하위 named subsection만 대상이다.
3. Experiment/evaluation/dataset/implementation/analysis subsection은 대상이 아니다.
4. Heading만 LLM에 보내지 않는다. 해당 subsection heading과 필터된 body를 함께 보낸다.
5. 본문이 mechanism/component를 실제로 정의하거나 설명할 때만 0개 또는 1개 후보를 반환한다.
6. Heading text를 무조건 candidate title로 복사하지 않는다.
7. Source 전체를 다시 보내지 않는다.
8. 이미 cover된 subsection은 추가 호출하지 않는다.
9. Targeted call은 Source당 bounded count를 둔다. 권장 상한은 8이다.
10. `think=false`, `temperature=0`, existing structured schema, output token limit을 재사용한다.
11. 기존 JSON repair 최대 1회 정책을 재사용한다.
12. Targeted candidate도 기존 schema validation, identity deduplication, provenance, curator, quality gate를 모두 통과해야 한다.
13. Targeted extraction 실패는 positional fallback이나 heading 강제 생성으로 대체하지 않는다.
14. Curator는 계속 선택 전용이다.
15. Source/Knowledge는 수정하지 않는다.

### 필요한 internal representation

Processing view가 method subsection별로 최소 다음을 제공하는 방식을 권장한다.

```text
canonical heading
original heading
filtered subsection body
page/section provenance
stable subsection identifier
```

현재 `AIProcessingView.methodology_subsections`는 canonical heading 문자열만 제공한다. Targeted extraction을 위해 body와 provenance를 가진 immutable dataclass로 확장하되 기존 report와 test 호환성을 유지한다.

### 권장 report 추가

```text
method_recovery:
  detected_subsections
  covered_before_recovery
  targeted_subsections
  recovered_concepts
  still_uncovered
  recovery_calls
```

Dry-run에서만 보이는 internal report이며 Source Markdown에 쓰지 않는다.

### 테스트 요구사항

- 여러 named method subsection이 한 general chunk에 있어도 subsection unit으로 분리됨
- 이미 mechanism/component로 cover된 subsection은 targeted call 없음
- uncovered subsection만 targeted call
- experiment/evaluation/implementation subsection은 대상 아님
- heading만 있고 body 설명이 없으면 candidate 0개 허용
- targeted extraction candidate는 최대 1개
- targeted call count 상한 준수
- malformed JSON은 기존 repair 최대 1회 적용
- targeted timeout/schema failure 처리
- targeted candidate provenance에 Source, subsection, chunk/page 정보 유지
- recovered candidate가 기존 identity와 같으면 deterministic merge
- curator는 새 concept 생성 불가
- recovery 후 mechanism coverage가 생기면 quality gate pass 가능
- recovery 후에도 coverage가 없으면 quality gate failed 유지
- technical/quality failure 시 `--write` 전체 차단
- Source/Knowledge unchanged
- 실제 Ollama/A-MEM 호출 없음
- 전체 기존 tests 통과

## Claude Code용 목표 프롬프트

아래 블록을 Claude Code에 그대로 전달할 수 있다.

```text
현재 Obsidian Knowledge OS의 다음 단계로 methodology-subsection targeted extraction을 구현해라.

작업 디렉터리:
G:\내 드라이브\Obsidian\GILVault\GIL

작업 전 반드시 읽을 파일:
- AGENTS.md
- 90_System/Docs/ARCHITECTURE.md
- 90_System/Docs/DATA_CONTRACT.md
- 90_System/Docs/AI_BOUNDARIES.md
- 90_System/Docs/CLAUDE_CODE_HANDOFF.md
- .automation/README.md
- .automation/knowledge_os/ai_wiki/preprocess.py
- .automation/knowledge_os/ai_wiki/source.py
- .automation/knowledge_os/ai_wiki/schema.py
- .automation/knowledge_os/ai_wiki/engine.py
- .automation/knowledge_os/ai_wiki/curator.py
- .automation/knowledge_os/ai_wiki/quality.py
- 관련 tests

현재 상태:
- PDF ingestion, processing view, Local Ollama structured extraction, deterministic identity deduplication, source-level curator, semantic quality gate가 구현되어 있다.
- 현재 uncommitted changes를 되돌리거나 덮어쓰지 마라.
- 전체 unit test 133개가 통과한다.
- 실제 A-MEM dry-run에서 methodology subsection 4개는 정확히 감지했지만 general extraction이 named mechanism 후보를 만들지 못해 quality_gate가 failed 되었다.
- curator는 선택 전용이므로 누락 후보를 생성할 수 없다.

목표:
일반 chunk extraction 뒤에, core methodology 아래의 아직 cover되지 않은 named subsection만 대상으로 bounded targeted extraction 단계를 추가한다.

필수 요구사항:
1. 생산 코드에 A-MEM이나 특정 concept 이름을 하드코딩하지 않는다.
2. Method/Methodology/Approach/Architecture 하위 named subsection만 대상으로 한다.
3. Experiment, dataset, evaluation, implementation, result, ablation, analysis, hyperparameter subsection은 제외한다.
4. Processing view가 subsection heading, filtered body, page/section provenance, stable identifier를 immutable internal representation으로 제공하게 한다.
5. Source Markdown은 수정하지 않는다.
6. Heading만으로 concept을 강제 생성하지 않는다. Subsection body가 reusable mechanism/component를 실제로 설명할 때만 0개 또는 1개를 반환한다.
7. Source 전체를 다시 보내지 않고 해당 subsection만 LLM에 보낸다.
8. General extraction 후보가 이미 해당 subsection을 mechanism/component로 cover하면 targeted call을 생략한다.
9. Targeted calls는 Source당 최대 8회로 제한한다.
10. think=false, temperature=0, localhost Ollama, existing schema/output limit을 사용한다.
11. 기존 JSON syntax repair 최대 1회와 strict schema validation을 재사용한다.
12. Targeted candidate도 deterministic identity merge, provenance, curator, quality gate를 반드시 통과한다.
13. Curator는 계속 기존 candidate 선택만 할 수 있고 새 concept 생성/rename/merge/content rewrite는 금지한다.
14. Recovery 실패 시 heading을 candidate로 복사하거나 임의 fallback을 하지 않는다.
15. Technical failure와 quality failure 모두 전체 --write와 state update를 차단한다.
16. Source/Knowledge/origin:me 노트를 수정하지 않는다.
17. 실제 A-MEM과 Ollama는 실행하지 않고 FakeLLMProvider fixture로만 테스트한다.

Dry-run report 추가:
- detected_subsections
- covered_before_recovery
- targeted_subsections
- recovered_concepts
- still_uncovered
- recovery_calls

최소 tests:
- 여러 methodology subsections가 한 general chunk에 있어도 분리
- covered subsection은 추가 호출 없음
- uncovered subsection만 호출
- experiment/evaluation/implementation 제외
- body 없는 heading은 후보 0개
- subsection당 최대 후보 1개
- Source당 targeted call 최대 8개
- malformed JSON repair 최대 1회
- timeout/schema failure
- subsection/page/chunk provenance 유지
- recovered identity deduplication
- recovery 후 quality gate pass
- recovery 실패 후 quality gate failed
- technical/quality failure write 차단
- Source/Knowledge unchanged
- 기존 tests 전체 통과

완료 보고:
1. 조사 결과
2. 수정/생성 파일
3. subsection representation
4. targeted extraction flow
5. 호출 상한과 retry 정책
6. provenance 방식
7. quality gate 연동
8. tests 결과
9. 실제 Ollama 호출 여부
10. 사용자가 다시 실행할 정확한 dry-run 명령
```

## Claude Code 첫 실행 체크리스트

1. `git status --short`로 위 uncommitted 변경이 존재하는지 확인한다.
2. 현재 tests를 먼저 실행해 baseline 133 tests 통과를 확인한다.
3. 실제 Source와 AI-Wiki 파일을 수정하지 않는다.
4. `preprocess.py`가 subsection body/provenance를 제공할 수 있도록 최소 확장한다.
5. 기존 general extraction, curator, quality gate를 재사용한다.
6. Fixture tests를 먼저 추가한다.
7. 전체 test suite와 `git diff --check`를 실행한다.
8. 실제 A-MEM dry-run은 사용자에게 명령만 제공한다.

Baseline commands:

```powershell
git status --short
python -m unittest discover -s ".automation\tests" -v
git diff --check
```

사용자가 실행할 다음 실제 검증 명령:

```powershell
python ".automation\run.py" ai-wiki scan --source "A-MEM.md"
```

Quality gate가 `pass`이고 selected concepts와 evidence가 수동 검토를 통과하기 전에는 `--write`를 사용하지 않는다.

## 알려진 주의점

- README의 과거 환경 감사 문구 중 Ollama가 설치되지 않았다는 문장은 초기 감사 기록이다. 현재는 사용자가 Ollama와 `qwen3.5:4b` 동작을 확인했다.
- `quality_gate.status`는 report contract상 `pass|warning|failed`지만 현재 구현은 실질적으로 pass 또는 failed를 사용한다.
- Dry-run에서도 malformed JSON diagnostic artifact는 `.automation/state/diagnostics/`에 생성될 수 있다.
- Google Drive 경로와 한글 경로를 고려해 path를 문자열 조합으로 다루지 말고 `pathlib.Path`를 사용한다.
- Line-ending warning(LF -> CRLF)은 현재 Windows worktree 특성이다. 관련 없는 파일의 line ending을 일괄 변경하지 않는다.
- 기존 Source 또는 AI-Wiki 결과를 bulk 수정하거나 재분류하지 않는다.

## 인계 완료 기준

Claude Code가 이 문서를 읽은 뒤 별도 역사 추적 없이 다음을 설명할 수 있어야 한다.

- 무엇이 이미 동작하는가
- 현재 실제 dry-run이 왜 실패했는가
- 왜 curator나 quality gate를 느슨하게 하면 안 되는가
- 다음 단계가 왜 subsection-targeted extraction인가
- 어떤 파일과 테스트를 수정해야 하는가
- 어떤 데이터는 절대 수정하면 안 되는가


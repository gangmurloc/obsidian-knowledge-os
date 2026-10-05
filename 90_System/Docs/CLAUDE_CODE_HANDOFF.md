---
type: system
origin: ai
knowledge_status: processed
domain:
  - knowledge-management
  - software-engineering
created: 2026-10-04
updated: 2026-10-06
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

Stage 1 진단으로 A-MEM의 method subsection 4개 중 3개에 근거를 둔 후보가 없다는 것을 확인했고, Stage 3에서 그런 subsection만 따로 추출하는 targeted extraction을 구현했다. `qwen3.5:27b`로 실행한 결과 3개가 모두 복구돼 method subsection 4개가 전부 최종 선택에 반영됐다. 남은 과제는 quality gate의 cover 판정이 여전히 제목 일치에 의존한다는 점, method root 감지 범위가 좁다는 점, 그리고 A-MEM 한 편으로만 검증했다는 점이다.

## 절대 규칙

1. `30_Resources/Sources/`는 외부 원본이다. 자동 수정하지 않는다.
2. `30_Resources/Knowledge/`와 `origin: me` 노트 본문은 자동 수정하지 않는다.
3. AI가 쓸 수 있는 지식 영역은 `30_Resources/AI-Wiki/`뿐이다.
4. PDF 원본은 `_assets/PDF/`에 보존한다.
5. dry-run이 기본이며 삭제, bulk rename, bulk move를 자동 수행하지 않는다.
6. 외부 LLM API를 사용하지 않는다. Loopback endpoint의 Ollama만 허용한다. 실제 런타임은 SSH 터널 뒤에 있는 사용자 소유 연구실 서버이며, 원격 호스트나 IP를 `base_url`에 직접 넣지 않는다.
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
- Local LLM provider: Ollama. 사용자 소유 연구실 GPU 서버(RTX A5000 24GB × 2, Ubuntu)에서 `127.0.0.1`에만 바인딩해 실행한다.
- Endpoint: `http://localhost:11435` (SSH local port forward로 서버의 `127.0.0.1:11434`에 연결)
- Model: `qwen3.5:27b`
- Temperature: `0.0`
- Timeout: `300`초 (첫 요청의 모델 로딩 시간 포함)
- keep_alive: `2m`, unload_after_run: `true`
- Config: `.automation/config/local_llm.json`
- 외부 LLM API 호출: 없음. 서버로 넘어가는 데이터는 LLM 요청에 담긴 Source chunk와 후보 요약뿐이다.
- 데스크톱 Ollama(11434)는 파이프라인에서 쓰지 않는다.

주요 로컬 의존성:

- Ollama
- PyMuPDF4LLM
- PyMuPDF / PyMuPDF Layout
- pypdf legacy fallback
- PyYAML
- Python standard-library HTTP client

## Git 상태

```text
branch: main
remote: origin https://github.com/gangmurloc/obsidian-knowledge-os (public)
stable tag: ai-wiki-v1 (Complete AI Wiki v1 end-to-end pipeline)
```

- 최근 커밋 순서: `Complete AI Wiki v1 end-to-end pipeline` → `Refine AI Wiki concept ontology rules` → `Add semantic quality gate and method-aware weak supervision` → `Route LLM calls to lab-server qwen3.5:27b and unload after each run` → 공개 저장소 준비 커밋들 → `Add method subsection spans and coverage diagnostics` → Stage 1 문서 커밋 → `Add targeted extraction for uncovered method subsections` → Stage 3 문서 커밋.
- Stage 3까지 모두 커밋됐다. 미커밋 변경은 없다.
- 2026-10-04에 공개 저장소로 올리면서 `30_Resources/Sources/`를 모든 커밋에서 제거했다. 논문 전문을 공개 재배포하지 않기 위해서다. 그래서 그 전에 문서나 프롬프트에 적어 둔 커밋 해시(`110bd8e`, `cd892c2`, `9f350e0`, `4951c90` 등)는 더 이상 유효하지 않다. 해시는 `git log --oneline`으로 확인한다.
- Source 노트는 이제 git이 추적하지 않는다(`.gitignore`). 파일은 vault에 그대로 있고 Google Drive로만 보존된다.
- 기록을 다시 쓰기 전의 전체 저장소는 `C:\Users\GIL\obsidian-knowledge-os-backup-20261004\vault-before-publish.bundle`에 백업돼 있다.

작업을 시작할 때 미커밋 변경이 있으면 되돌리거나 덮어쓰지 말고 그 위에서 작업한다.

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

### 11. Stage S: 연구실 서버 LLM 런타임과 GPU 반납

- 모든 LLM 호출은 SSH local port forward(`localhost:11435` → 서버 `127.0.0.1:11434`)를 거쳐 연구실 서버 Ollama의 `qwen3.5:27b`로 간다.
- 터널은 사용자가 연다: `ssh -N -L 11435:127.0.0.1:11434 <Host별칭>`. 파이프라인은 터널을 열거나 `ssh`를 실행하지 않는다.
- Loopback-only 검증은 그대로다. 원격 호스트나 IP는 `base_url`로 허용하지 않는다.
- PDF ingestion, preprocessing, chunking, dedup, role, quality gate, 파일 쓰기는 데스크톱에서 실행한다. 서버로 가는 것은 LLM 요청뿐이다.
- Config에 `keep_alive`(0~3600초 정수 또는 `30s`·`2m` 형식, 최대 `60m`)와 `unload_after_run`(bool, 기본 `false`)을 추가했다. 새 키가 없는 기존 config는 이전과 같은 의미로 로드된다.
- `keep_alive`를 설정하면 모든 generate payload 최상위에 들어간다. 설정하지 않으면 payload는 이전과 같다.
- `LLMProvider.unload(model)`은 `/api/generate`에 `{"model": ..., "keep_alive": 0}`만 보낸다. LLM 호출이 아니며 `stats.unload_requests`로 따로 센다.
- `ai-wiki scan`과 `llm-test`는 `unload_after_run=true`이고 LLM 호출이 1회 이상이면 종료 직전에 unload를 정확히 1회 보낸다. Pass(0), quality failure(6), technical failure(5) 경로 모두 같고, `--write`일 때는 note 쓰기와 state update 뒤에 보낸다.
- Unload 실패는 warning 한 줄로만 남고 exit code를 바꾸지 않는다. 재시도하지 않는다.
- 연결 실패(터널이 꺼짐 등)는 technical failure다. 다른 주소나 포트로 fallback하지 않는다.
- 4B를 전제로 둔 제약은 유지한다: output token 1024, `think=false`, `temperature=0`, JSON repair 최대 1회, chunk당 concept 1개, Source당 concept 최대 12개.
- 서버에서 다른 작업이 같은 모델을 동시에 쓰면 unload 때문에 그 작업이 다음 요청에서 모델을 다시 로딩한다. 그때는 `unload_after_run`을 `false`로 두고 `keep_alive`만으로 관리한다.

### 12. Stage 1: method subsection span과 coverage 진단

- 동작 변경과 추가 LLM 호출 없이 dry-run report에 `method_coverage`와 `evidence_locatability` 섹션을 추가했다. Role, curator, quality gate, exit code는 그대로다.
- `AIProcessingView.method_subsection_spans`가 subsection별 id, heading, 문자 span, page를 제공한다. 기존 `methodology_subsections`는 그대로 유지된다.
- Span은 heading 줄에서 시작해 그 subsection을 닫는 heading 직전에서 끝난다. 두 heading 모두 번호가 있으면 번호 깊이로, 아니면 Markdown 레벨로 판단한다. `### Page N`은 span을 끝내지 않는다.
- `SourceChunk`에 processing view 기준 `start`/`end` offset이 생겼다. Chunk 텍스트와 identifier는 바뀌지 않았다.
- `locate_excerpt`는 evidence excerpt의 위치를 결정론적으로 찾는다. NFKC, casefold, 강조기호 제거, 공백 축약 뒤 정확히 일치해야 하고 fuzzy match는 없다.
- `title_cover`는 현재 quality gate 규칙이고, `evidence_cover`는 mechanism/component 후보의 evidence가 span 안에 있는지다.
- Report에는 id, heading, title, role, 숫자만 나오고 Source 본문은 나오지 않는다. Source당 subsection 20행, 행당 `in_span` 후보 5개가 상한이다.
- 진단 계산이 실패하면 scan은 계속되고 warning 한 줄만 남는다.
- 형식 설명은 `.automation/README.md`의 "Method Coverage Diagnostics" 절에 있다.

### 13. Stage 3: method subsection targeted extraction

- 일반 추출과 role 할당 뒤에, cover되지 않은 method subsection마다 targeted 추출을 한 번씩 호출한다. Cowork 프롬프트 없이 이 문서의 "Targeted extraction 설계 원칙"을 명세로 삼아 구현했다.
- Cover 판정(대상 선정용): mechanism/component 후보가 제목으로 heading과 일치하거나, 그 후보의 evidence가 subsection span 안에서 발견되면 cover로 본다. Cover된 subsection은 호출하지 않는다.
- 입력은 그 subsection의 heading과 본문뿐이고, 일반 chunk 최대 크기 한 개 분량으로 자른다. Source 전체를 다시 보내지 않는다. 본문이 없는 heading은 호출하지 않는다.
- 상한: subsection당 호출 1회와 후보 최대 1개, Source당 targeted 호출 최대 8회(문서 순서). `think=false`, `temperature=0`, output token 1024, JSON repair 최대 1회는 일반 추출과 같다.
- Targeted prompt는 그 subsection이 설명하는 mechanism/component만 요구한다. Source 시스템 자체를 반환하지 말고, heading만으로 concept을 만들지 말라고 지시한다. 생산 코드에 특정 논문이나 concept 이름은 없다.
- Targeted 후보도 schema 검증, 제외 규칙, identity 병합, role 할당, curator, quality gate를 그대로 거친다. 호출이 concept을 반환하지 않으면 아무것도 만들지 않는다.
- Targeted 호출 실패는 technical failure다. 그 Source를 중단하고 전체 write를 막는다. Fallback은 없다.
- Provenance: targeted 후보의 evidence는 `subsection-<subsection id>-<hash>` 형식의 chunk id를 갖고, processing state의 `chunks` 목록에도 일반 chunk 뒤에 기록된다.
- Report에 `method_recovery` 섹션과 `statistics.recovery_calls`가 추가됐다. `recovery_calls`는 `llm_calls`에 포함된다.
- Quality gate, curator, 기존 일반 추출 prompt는 바꾸지 않았다. Gate는 여전히 제목 일치로 cover를 판정하므로, 제목이 heading을 풀어 쓴 형태인 복구 후보는 `recovered`로 집계되고 `evidence_cover=y`로 나오지만 gate의 coverage 검사는 만족시키지 못한다.
- 일반 추출 로직(호출, JSON repair, 진단 파일)을 `_extract_concepts`로 옮겨 일반 추출과 targeted 추출이 함께 쓴다. 동작은 같다.
- 형식 설명은 `.automation/README.md`의 "Method Subsection Recovery" 절에 있다.

## 핵심 코드 지도

- `.automation/run.py`: CLI entrypoint
- `.automation/knowledge_os/cli.py`: command parsing과 report 출력
- `.automation/knowledge_os/paper_ingest.py`: PDF ingestion orchestration
- `.automation/knowledge_os/pdf_extractors.py`: extractor abstraction
- `.automation/knowledge_os/io_utils.py`: atomic write
- `.automation/knowledge_os/llm/base.py`: provider request/response contract, `unload`, `request_unload`
- `.automation/knowledge_os/llm/config.py`: loopback 검증, `keep_alive`·`unload_after_run` 검증
- `.automation/knowledge_os/llm/ollama.py`: loopback Ollama transport, `keep_alive` payload, unload 요청
- `.automation/knowledge_os/llm/fake.py`: unit-test provider
- `.automation/knowledge_os/ai_wiki/source.py`: Source validation과 chunking
- `.automation/knowledge_os/ai_wiki/preprocess.py`: in-memory filtering과 method subsection detection
- `.automation/knowledge_os/ai_wiki/schema.py`: extraction schema, parser, repair prompt, merge
- `.automation/knowledge_os/ai_wiki/ontology.py`: identity와 relation suggestions
- `.automation/knowledge_os/ai_wiki/curator.py`: duplicate risk와 source-level selection
- `.automation/knowledge_os/ai_wiki/quality.py`: semantic quality gate
- `.automation/knowledge_os/ai_wiki/coverage.py`: evidence 위치 찾기와 method coverage 진단 (읽기 전용)
- `.automation/knowledge_os/ai_wiki/engine.py`: end-to-end orchestration
- `.automation/knowledge_os/ai_wiki/render.py`: AI-Wiki Markdown rendering
- `.automation/tests/test_ai_wiki.py`: extraction/selection/write safety tests
- `.automation/tests/test_ai_wiki_preprocess.py`: processing view와 method detection tests
- `.automation/tests/test_llm.py`: config, loopback, payload, unload 요청 tests
- `.automation/tests/test_llm_unload.py`: `ai-wiki scan`·`llm-test` 실행 종료 시 unload와 exit code tests
- `.automation/tests/test_method_coverage.py`: subsection span, chunk offset, excerpt 위치, coverage report tests
- `.automation/tests/test_method_recovery.py`: targeted extraction 대상 선정, 상한, 실패 처리, provenance tests

## 최신 테스트 상태

2026-10-06 기준 (Stage 3 반영 후):

```text
python -m unittest discover -s .automation/tests
Ran 221 tests in 12.845s
OK
```

Unit test는 실제 Ollama를 호출하지 않는다. 작은 synthetic fixture, fake transport, FakeLLMProvider만 사용한다.

## 실제 A-MEM dry-run 결과

현재 기준선은 `qwen3.5:27b` 결과다. 모델이 다르므로 아래 두 결과는 직접 비교할 수 없다.

### `qwen3.5:27b` 기준선 (2026-10-04, Stage S 이후)

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
unload_requests: 1
failures: none
```

추출 후보:

```text
Agentic Memory                     role=method_entity primary_source_entity=true
Agentic Memory Architecture        role=mechanism
A-MEM                              role=method_entity primary_source_entity=true
A-MEM Agentic Memory Architecture  role=method_entity
A-MEM Agentic Memory System        role=method_entity
A-MEM Retrieval Mechanism          role=mechanism
Memory Evolution                   role=mechanism
Memory Evolution Mechanism         role=mechanism
MemoryBank                         role=mechanism
```

Curator trigger는 deterministic duplicate-risk group 2개(`agentic memory`, `memory evolution`)였다.

Curator 선택:

```text
Agentic Memory
A-MEM Retrieval Mechanism
Memory Evolution
```

Quality gate:

```text
status: pass
reasons: none
```

서버 쪽 세션이 요청 로그와 대조한 결과:

- `tags` + `generate` 14쌍과 unload 1건이 모두 200이었고 경고·오류는 0건이었다.
- Unload 뒤 GPU 0 여유가 23.9GiB(전체 24.2GiB)로 돌아왔다.
- 다른 요청과 겹치지 않은 구간에서 호출당 26~31초, scan 전체는 8분 46초였다.
- 이 Ollama는 요청을 하나씩 처리한다. 서버의 다른 작업과 겹친 첫 두 호출은 대기 때문에 1분 10초대였다. Timeout 300초에는 여유가 있었다.

관찰:

- Gate는 pass지만 method subsection 4개 중 mechanism 후보와 맞은 것은 `memory evolution` 하나다. `note construction`과 `link generation`은 후보 9개 어디에도 없다. Gate는 mechanism/component가 하나만 맞아도 통과한다.
- `A-MEM Retrieval Mechanism`의 curator 사유는 space complexity와 retrieval time이다. 3.4절이 아니라 4.6 Scaling Analysis에서 나왔을 수 있다(미확인).
- 후보 9개 중 5개가 Source 시스템 자체의 변형이다. 4b 때와 같은 패턴이다.
- `A-MEM`의 identity가 `mem`으로 정규화된다. 선행 관사 제거 규칙이 `A-`에 적용된 것으로 보인다(미확인). Stage S 이전부터 있던 동작이다.
- `MemoryBank`는 baseline인데 role이 `mechanism`으로 추출됐고 curator가 제외했다.
- 이 dry-run 뒤에 `--write`는 하지 않았다. Dry-run report에는 note 본문과 evidence가 나오지 않아 이 출력만으로는 수동 검토를 할 수 없다.

### Stage 1 진단 실행 (2026-10-04, `qwen3.5:27b`)

Stage 1 구현 뒤 같은 명령으로 다시 실행했다. 통계와 선택 결과는 기준선과 같다: `llm_calls: 14`, `curator_calls: 1`, `unload_requests: 1`, gate pass, 선택 3개(`Agentic Memory`, `A-MEM Retrieval Mechanism`, `Memory Evolution`), 실패 없음. 후보는 8개였다(기준선은 9개). `temperature=0`이어도 실행마다 후보가 조금 달라진다.

```text
method_coverage:
  [ms-c3d558db] note construction pages=4 heading_chunks=4 offset_chunks=4 | candidates: title_cover=n evidence_cover=n | selected: title_cover=n evidence_cover=n | in_span: (none)
  [ms-51290a96] link generation pages=4 heading_chunks=4 offset_chunks=4 | candidates: title_cover=n evidence_cover=n | selected: title_cover=n evidence_cover=n | in_span: (none)
  [ms-f3cc630f] memory evolution pages=4,5 heading_chunks=4 offset_chunks=4,5 | candidates: title_cover=y evidence_cover=y | selected: title_cover=y evidence_cover=y | in_span: Memory Evolution(mechanism, located 1/3)
  [ms-009e7175] retrieve relative memory pages=5 heading_chunks=5 offset_chunks=5 | candidates: title_cover=n evidence_cover=n | selected: title_cover=n evidence_cover=n | in_span: (none)
evidence_locatability:
  located 26/33 evidence across 8 candidates
```

해석:

- `note construction`, `link generation`, `retrieve relative memory`에는 어떤 role의 후보도 그 span 안에 evidence가 없다. 후보가 있었는데 role이나 제목 때문에 놓친 것(가설 A)이 아니라, 그 구간에 근거를 둔 후보가 아예 없다(가설 B).
- 따라서 cover 정의를 evidence 기준으로 바꾸는 것만으로는 이 세 subsection이 복구되지 않는다. Uncovered subsection만 대상으로 하는 targeted extraction이 필요하다.
- 3.1, 3.2, 3.3의 heading이 모두 chunk 4 하나에 있고, 3.3의 뒷부분과 3.4가 chunk 5에 있다. Chunk당 concept이 1개이므로 두 chunk에서 나올 수 있는 후보는 최대 2개다.
- `memory evolution`은 heading이 chunk 4에만 있고 본문이 chunk 5로 이어진다. Heading 줄 기준 연결(`heading_chunks`)로는 chunk 5가 빠진다.
- `A-MEM Retrieval Mechanism`의 evidence는 `retrieve relative memory` span 안에 없다.
- Evidence 33개 중 7개는 위치를 찾지 못했다. 이 7개가 어느 후보의 것인지는 report에 나오지 않으므로, 일부가 빈 구간에 속할 가능성은 남아 있다. Evidence 기준 cover를 도입하면 이 비율(79%)만큼만 판정에 쓸 수 있다.
- 이 실행은 41분 걸렸다(기준선은 8분 46초). Timeout은 없었지만 호출당 평균이 3분에 가깝다. 원인은 서버 로그로 확인해야 한다.

### Stage 3 실행 (2026-10-05, `qwen3.5:27b`)

Targeted extraction을 구현한 뒤 같은 명령으로 실행했다. 현재 기준선은 이 결과다.

```text
mode: dry-run
chunk_count: 13
llm_calls: 17
json_repairs: 0
timeout_failures: 0
curator_calls: 1
recovery_calls: 3
unload_requests: 1
quality_gate: pass
failures: none
```

```text
method_recovery:
  detected_subsections=4 covered_before_recovery=1 targeted_subsections=3 recovered_concepts=3 still_uncovered=0 recovery_calls=3
  [ms-c3d558db] note construction -> Memory Note(component) recovered
  [ms-51290a96] link generation -> Autonomous Link Generation Mechanism(mechanism) recovered
  [ms-009e7175] retrieve relative memory -> Retrieve Relative Memory(mechanism) recovered
method_coverage:
  [ms-c3d558db] note construction | candidates: title_cover=n evidence_cover=y | selected: title_cover=n evidence_cover=y | in_span: Memory Note(component, located 2/3)
  [ms-51290a96] link generation | candidates: title_cover=n evidence_cover=y | selected: title_cover=n evidence_cover=y | in_span: Autonomous Link Generation Mechanism(mechanism, located 3/3)
  [ms-f3cc630f] memory evolution | candidates: title_cover=y evidence_cover=y | selected: title_cover=y evidence_cover=n | in_span: Memory Evolution(mechanism, located 1/3)
  [ms-009e7175] retrieve relative memory | candidates: title_cover=y evidence_cover=y | selected: title_cover=y evidence_cover=y | in_span: Retrieve Relative Memory(mechanism, located 3/3)
evidence_locatability:
  located 34/42 evidence across 12 candidates
```

후보는 12개였고, curator(duplicate-risk group 2개로 발동)가 5개를 선택했다.

```text
Agentic Memory
Autonomous Link Generation Mechanism
Memory Evolution Mechanism
Memory Note
Retrieve Relative Memory
```

해석:

- 빠져 있던 세 subsection이 모두 복구됐고, method subsection 4개가 전부 최종 선택에 반영됐다. 최종 concept은 3개에서 5개가 됐다.
- Targeted 호출의 evidence는 대부분 해당 span 안에서 위치가 확인된다(3/3, 3/3, 2/3). Prompt에서 excerpt를 원문 그대로 복사하라고 요구한 효과로 보인다.
- `Memory Note`와 `Autonomous Link Generation Mechanism`은 제목이 heading과 달라 `title_cover=n`이다. Gate가 pass한 것은 다른 두 subsection이 제목으로 일치해서다. 제목 일치가 하나도 없는 Source였다면 복구에 성공하고도 gate는 실패했을 것이다(F1).
- `Retrieve Relative Memory`는 제목이 heading과 같다. 본문이 그 이름으로 mechanism을 설명한 것인지, 모델이 heading을 그대로 쓴 것인지는 note 본문을 보고 검토해야 한다.
- `memory evolution`은 선택된 대표가 `Memory Evolution Mechanism`이라 `selected`의 `evidence_cover`가 `n`이다. Span 안에 evidence가 있는 `Memory Evolution`은 같은 duplicate-risk group의 alias로 탈락했다.
- 기존 `A-MEM Retrieval Mechanism`은 curator가 탈락시켰다. `MemoryBank`(baseline인데 role이 mechanism)도 탈락했다.
- 실행 시간은 8분 36초였다(호출 17회).
- `--write`는 하지 않았다. Dry-run report에는 note 본문과 evidence가 나오지 않아 수동 검토를 할 수 없다.

### `qwen3.5:4b` 결과 (Stage S 이전, 참고용)

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

이 절의 targeted extraction은 Stage 3으로 구현됐다("지금까지의 진행 과정" 13번). 아래 설계 원칙과 그 뒤의 "Claude Code용 목표 프롬프트"는 구현의 근거로 남겨 둔 기록이다. 남은 작업은 다음과 같다.

1. **첫 `--write` 전 수동 검토 수단.** Dry-run report에는 note 본문과 evidence가 나오지 않는다. 선택된 concept의 본문과 evidence를 쓰기 전에 볼 방법이 필요하다.
2. **Quality gate의 cover 정의(F1).** Gate는 제목이 heading과 일치해야 cover로 본다. Targeted 추출로 복구한 후보는 제목이 달라도 그 subsection에서 나온 것이 분명하므로, gate가 evidence나 provenance 기준 cover도 인정할지 결정해야 한다. Gate를 바꾸는 일이라 설계 검토가 필요하다.
3. **Role 승격의 heading 줄 의존(F2).** `_apply_source_context_roles`는 후보를 뽑은 chunk에 heading 줄이 있어야 method_entity를 mechanism으로 올린다. Subsection 본문이 다음 chunk로 이어지면 승격되지 않는다. Offset 기준으로 바꿀 수 있다.
4. **Method root 감지 확장(F3).** `Our Approach`, `Proposed Method`, `Framework`, 시스템 이름 섹션은 method root로 감지되지 않는다. 이런 Source에서는 복구와 coverage 검사가 둘 다 조용히 꺼진다.
5. **다른 논문으로 검증.** 지금까지 실제 실행은 A-MEM 한 편뿐이다. 구조가 다른 논문 2~3편으로 dry-run해 과적합 여부를 확인한다.
6. **실행 간 변동.** `temperature=0`이어도 실행마다 후보가 조금 달라진다. 비교 실험을 하려면 seed 고정을 검토한다.

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

아래 블록은 Stage 3에서 이미 구현한 작업의 프롬프트다. 기록으로 남겨 두며, 다시 전달할 필요는 없다.

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
- 전체 unit test 221개가 통과한다.
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

1. `git status --short`로 미커밋 변경이 있는지 확인한다.
2. 현재 tests를 먼저 실행해 baseline 221 tests 통과를 확인한다.
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

- README의 과거 환경 감사 문구 중 Ollama가 설치되지 않았다는 문장은 초기 감사 기록이다. 이후 사용자가 데스크톱 Ollama와 `qwen3.5:4b` 동작을 확인했고, Stage S부터는 연구실 서버의 `qwen3.5:27b`를 쓴다.
- 실제 실행 전에 SSH 터널(`localhost:11435`)이 열려 있어야 한다. 터널이 꺼져 있으면 `ai-wiki scan`은 technical failure(exit 5)로 끝나고 다른 주소로 재시도하지 않는다.
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


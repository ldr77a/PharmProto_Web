# 다음 세션 인수인계 (2026-10-04 밤 기준)

이 파일은 앱 저장소(PhramaProto-0.1)에서 새 Claude Code 세션을 열 때 첫 명령으로 읽히는 용도다.
DB 저장소(`../Phrama_Proto`)에서 작업하던 세션의 메모리는 폴더에 묶여 있어 여기서는 보이지 않는다. 필요한 맥락을 전부 적는다.

## 1. 현재 상태

- 브랜치 `feat/schema2-role-layer` (main 에서 분기). 커밋 `abe6336`(schema 2 역할층·스냅샷 20261004T120041Z), 그 위에 해설층 커밋. 푸시 안 함, main 머지 여부는 사용자 결정.
- 스냅샷 `release-data/knowledge.sqlite` 는 schema 2, LFS 포인터로 커밋됨(git-lfs 설치 확인됨).
- 테스트: macOS 에서는 `LOCALAPPDATA=/tmp/localappdata uv run pytest -q --deselect tests/product/test_launcher.py --deselect tests/product/test_release_baseline.py --deselect tests/product/test_release_zip.py --deselect tests/product/test_windows_standalone.py` → 45 passed. 제외한 23개는 msvcrt·powershell 이 필요한 Windows 전용. JS 는 `node --test tests/test_app_js.mjs`.
- 린트 `uv run ruff check .` 는 기존 코드의 경고가 남아 있다(새 파일은 통과). 새로 손댄 파일만 깨끗하게 유지한다.
- macOS 에서 앱을 띄워 보려면(개발용): `LOCALAPPDATA=/tmp/localappdata uv run python -c "from pharma_proto.app import create_app; create_app().run(host='127.0.0.1', port=8765)"` 후 브라우저에서 127.0.0.1:8765. 정식 실행은 Windows `start.bat`.
- LLM 키는 화면의 "API 설정"에 넣는다(메모리에만 저장, 파일에 안 남음). 개발 중 Claude 키는 `../Phrama_Proto/.env` 의 `CLAUDE_API_KEY` 에 있다. 채팅에 붙이지 말 것.

## 2. 절대 규칙 (CLAUDE.md 와 동일, 다시 강조)

- **계약 파일은 여기서 고치지 않는다.** `pharma_proto/knowledge/{snapshot,sqlite_repository,contracts,evidence,function_taxonomy}.py`, `cleaning/canonical_base.py`, `gates/kg_util.py`, `function_seed.json`, `pharma_proto/cli.py` 는 DB 저장소가 소유하고 `tools/publish_snapshot.py` 가 복사한다. 바꿔야 하면 DB 저장소에서 바꾸고 publish 한다.
- 스냅샷·DB 를 앱에서 수정하지 않는다. 새 데이터가 필요하면 DB 저장소 쪽 작업이다.
- 오류는 코드만 노출(`pharma_proto/errors.py`). 예외 문구·경로·키를 응답이나 로그에 쓰지 않는다.
- LLM 이 숫자를 만들지 않는다(I8). 해설층도 표의 숫자를 바꾸지 않는 규칙으로 돈다.
- Claude 는 현재 모델(sonnet-5-5/opus-5-5)이 강제 `tool_choice` 를 거부하므로 `messages.parse` 구조화 출력을 쓴다. 모델 ID 는 `llm/catalog.py` 의 것만.

## 3. 오늘까지 끝난 것

- 역할층(schema 2): 후보 선정·배분·게이트2 가 역할별 표(`role_candidates`, `role_pct_range`, `role_pct_sum_range`)를 먼저 본다. 결과: 트리메타지딘 20mg 직타 후보 1 이 lactose/HPC → MCC/hypromellose.
- 용량: `dose_resolver` 가 승인 라벨 용량(`api_doses(mode="approved_label")`)을 먼저 본다(특허 예시 용량에 끌려가지 않게).
- 해설층: `generation/explanation.py` → `LLMService.explain` → `FormulationExplanation` → `html_formatter.explanation_html`. 문장마다 `basis`(evidence/general) 배지. 실측 Sonnet 5.5 약 80초.
- DB 쪽: 트리메타지딘 특허 3건 적재, 메타진정 라벨 2건, 역할 사전 533항목.

## 4. 평가자 피드백 9항목과 대응 계획 (2026-08-28 평가지)

| # | 피드백 | 위치 | 상태 / 계획 |
|---|---|---|---|
| 1 | 1차 답변에 추가·보완 질문 불가 | 앱 | 미착수. 세션에 spec+candidates 보관, 후속 질문을 LLM 이 spec 변경(JSON diff)으로 번역 → `run_generation` 재실행. `app.py /api/generate` 에 `conversation_id` 와 이전 spec 전달. 해설층과 같은 구조화 출력 패턴 |
| 2 | 고형제 외 제형 | 앱+DB | 미착수. `generation/oral_solid_profiles.py` 가 비고형을 거부(`_NON_ORAL_SOLID`). DB 스냅샷에는 suspension 168·solution 131 등이 이미 있고 역할 표도 제형별로 있음. 액제 프로파일(용매·보존제·완충제·점증제 역할)을 추가하면 1차 지원 가능. 분량 통계는 특허 유래라 약함 |
| 3 | 질량·성분명 세부 지정이 무시됨 | 앱 | 미착수. 원인: `llm/schema.py ParsedRequest` 에 성분별 분량 칸이 없어 사용자가 적은 % 가 버려짐. `excipient_allocator.allocate(user_pcts=...)` 는 이미 사용자 % 를 받으므로 스키마에 `{ingredient, pct|mg}` 를 추가하고 `to_domain()`→`FormulationSpec`→`allocate` 로 흘리면 됨. 총중량 `target_total_mg` 도 같은 경로 |
| 4 | 화면색 밝게 | 앱 | 미착수. `static/app.css` 가 `color-scheme: dark` 고정. `prefers-color-scheme` 대응 + 토글 버튼(localStorage) |
| 5 | 인쇄 | 앱 | 미착수. `@media print` 로 컨트롤·사이드바 숨기고 카드만, "인쇄" 버튼은 `window.print()` |
| 6 | 비전문가용 설명, 근거 클릭 설명 | 앱 | 절반. 해설층이 성분별 이유를 줌. 남은 것: 근거 꼬리표("KG 범위, n=919")에 툴팁/클릭 설명, 게이트 안내 쉬운 말로 |
| 7 | 로그아웃 | 앱 | 사실상 "API 설정 변경" 버튼이 키 삭제(`MemoryKeyStore.clear`)임. 버튼 이름·안내 문구만 바꾸면 됨 |
| 8 | LLM 보다 답변 품질 낮음 | 앱 | 해설층으로 1단계 완료. 남은 순서: (a) 공정 반영 — `spec.process` 가 파싱되지만 `resolve_profile` 키워드에만 쓰임. 직타/습식 프로파일 규칙(JSON) 추가, (b) 총중량을 라벨 값·API 함량 규칙으로(지금은 `api_mg+80` 휴리스틱), (c) LLM 제안→DB 검증 하이브리드 선정, (d) API 프로파일 + 호환성 게이트(`gates/compatibility.py` 는 구현돼 있으나 파이프라인 미연결, Maillard 등 규칙 등급 분리 필요) |
| 9 | 작업 내용 저장 | 앱 | 미착수. 결과 HTML·엑셀·해설을 `LOCALAPPDATA/PhramaProto/results/<timestamp>/` 에 저장하고 목록 화면 추가 |

권장 순서: 3 → 8(a,b) → 1 → 9 → 4·5·7 → 6 → 2. 3번과 8(a,b)는 결과 품질에 직접 닿고 작다.

## 5. 알아 둘 함정

- `generation/generation_loop._distinct_picks` 는 후보 i 가 각 역할의 i번째 선택지를 쓰며, 성분이 겹치면 다음 조합으로 넘어간다(후보 1에 PVA 코팅이 나오는 이유).
- 역할별 범위가 표본 5 미만이거나 중앙값 0 이면 base 전체 범위로 떨어진다(`excipient_allocator._rep_pct`).
- 게이트2(제조성)는 대리지표이고, 화학 호환성 게이트는 아직 돌지 않는다. 해설층의 Maillard 언급은 모델 일반 지식(general) 이다.
- 특허 유래 용량이 많아 `api_doses()` 전체 분포 중앙값은 신뢰하지 말고 `approved_label` 모드를 먼저 본다.
- `tests/product/fakes.py FakeKnowledge` 는 역할층 메서드를 갖고 있으며 기본은 빈 결과다. 역할별 동작을 테스트하려면 생성자 인자로 넣는다.
- `tests/test_web_workflow.py` 의 `_FakeLLMService` 는 `explain` 도 갖는다. `tests/product/test_mvp_app.py` 의 가짜는 `parse` 만 있어 앱이 해설을 건너뛴다(`getattr` 가드).

## 6. 새 세션 첫 명령 예시

"docs/handoffs/NEXT_CHAT_CONTEXT.md 와 CLAUDE.md 를 읽고, 피드백 3번(세부 지정 무시)부터 시작해."

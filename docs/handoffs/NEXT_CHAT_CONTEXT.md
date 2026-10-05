# 다음 세션 인수인계 (2026-10-04 밤, 피드백 9항목 대응 뒤 기준)

이 파일은 앱 저장소(PhramaProto-0.1)에서 새 Claude Code 세션을 열 때 첫 명령으로 읽히는 용도다.
DB 저장소(`../Phrama_Proto`)에서 작업하던 세션의 메모리는 폴더에 묶여 있어 여기서는 보이지 않는다. 필요한 맥락을 전부 적는다.

## 1. 현재 상태

- 브랜치 `feat/schema2-role-layer` (main 에서 분기). 커밋 순서: `abe6336`(schema 2 역할층·스냅샷 20261004T120041Z) →
  해설층 → 인수인계 → `0676d09` 라이트 테마 → `b010023` 공통 기반 → `eb5ab63` 3번 분량 반영 → `b7b163a` 1·7번 후속 질문·로그아웃 →
  `e2a98e4` 4·5번 테마·인쇄 → `bd56423` 9번 저장 → `f215e85` 6·8번 설명 → (이 문서 커밋). 푸시 안 함, main 머지 여부는 사용자 결정.
- 스냅샷 `release-data/knowledge.sqlite` 는 schema 2(20261004T120041Z), LFS 포인터로 커밋됨.
- 테스트: macOS 에서는 `LOCALAPPDATA=/tmp/localappdata uv run pytest -q --deselect tests/product/test_launcher.py --deselect tests/product/test_release_baseline.py --deselect tests/product/test_release_zip.py --deselect tests/product/test_windows_standalone.py`
  → **103 passed, 2 skipped**. 제외한 32개는 msvcrt·powershell 이 필요한 Windows 전용. JS 는 `node --test tests/test_app_js.mjs` → **7 passed**.
- 린트 `uv run ruff check .` 는 기존 코드의 경고가 남아 있다. 이번에 손댄 파일은 모두 통과. 새로 손댄 파일만 깨끗하게 유지한다.
- 개발용 실행(macOS): `LOCALAPPDATA=/tmp/localappdata uv run python -c "from pharma_proto.app import create_app; create_app().run(host='127.0.0.1', port=8765)"`.
  **주의**: 8765 를 이전 세션의 서버가 잡고 있을 수 있다(`lsof -nP -iTCP:8765 -sTCP:LISTEN`). 그 서버는 구 스냅샷(schema 1)이고 새 라우트가 없다.
- 정식 실행은 Windows `start.bat`. **릴리스 ZIP 은 아직 다시 만들지 않았다** — 새 모듈 5개가 허용목록에 들어갔으니 Windows 에서
  `pwsh tools/build-release.ps1` 후 `docs/release/WINDOWS_SMOKE_CHECKLIST.md` 로 확인해야 한다.
- LLM 키는 화면의 "API 설정"에 넣는다(메모리에만, 로그아웃이 지움). 개발 중 Claude 키는 `../Phrama_Proto/.env` 의 `CLAUDE_API_KEY` 에 있다. 채팅에 붙이지 말 것.
- **실제 LLM 으로 끝까지 돌려 본 적은 없다**(가짜 서비스 테스트만). 다음 세션 첫 작업으로 Claude 키를 넣고 §6 의 수동 시나리오를 돌려 보기를 권한다.

## 2. 절대 규칙 (CLAUDE.md 와 동일, 다시 강조)

- **계약 파일은 여기서 고치지 않는다.** `pharma_proto/knowledge/{snapshot,sqlite_repository,contracts,evidence,function_taxonomy}.py`, `cleaning/canonical_base.py`, `gates/kg_util.py`, `function_seed.json`, `pharma_proto/cli.py` 는 DB 저장소가 소유하고 `tools/publish_snapshot.py` 가 복사한다.
- 스냅샷·DB 를 앱에서 수정하지 않는다.
- 오류는 코드만 노출(`pharma_proto/errors.py`). 예외 문구·경로·키를 응답이나 로그에 쓰지 않는다. 저장된 작업 응답에도 경로 대신 id 만.
- LLM 이 숫자를 만들지 않는다(I8). 해설층·후속 답변도 표의 숫자를 바꾸지 않는 규칙으로 돈다. 후속 '수정'은 요청(ParsedRequest)만 고치고 숫자는 다시 계산한다.
- Claude 는 `messages.parse` 구조화 출력(현재 모델이 강제 `tool_choice` 거부). 모델 ID 는 `llm/catalog.py` 의 것만.
- `app.js` 에 `localStorage|sessionStorage|document.cookie` 금지(테스트가 막음). 상태는 JS 변수나 서버(`preferences.json`, `results/`)에.
- CSP 가 인라인 스크립트·스타일을 막는다. 데이터 주입은 `<script type="application/json">`(`#model-catalog`, `#help-text`) 방식만.

## 3. 이번에 끝난 것 — 평가 피드백 9항목(2026-08-28 평가지) 대응

| # | 피드백 | 상태 | 구현 요점 |
|---|---|---|---|
| 1 | 후속·보완 질문 불가 | **완료** | `POST /api/followup`. LLM 이 의도 분류(`FollowUpResponse.action` refine/answer). refine 은 전체 `ParsedRequest` 를 돌려주고 서버가 `request_changes` 로 diff → 바뀐 게 있을 때만 `to_domain()` 으로 재생성·재해설. answer 는 문장마다 근거/일반지식 배지. 대화는 `pharma_proto/conversation.py`(메모리 LRU 20). 화면: 결과 아래 '이 결과에 이어서 질문' |
| 2 | 비고형 제형 | **진입점만** | 비고형 요청은 `400 REQUEST-FORM-001` + 한국어 안내(전에는 500). 본 구현 설계는 `docs/design/liquid-dosage-forms.md` |
| 3 | 세부 지정(질량·성분명) 무시 | **완료** | `ParsedRequest.amounts[{ingredient, mg|pct}]` → `FormulationSpec.user_amounts` → 후보별 역할 키로 재배열 → `allocate(user_pcts, user_mgs)`. 총중량 없고 희석제 분량만 있으면 역산. 사용자 총중량은 `_adjust_total` 재시도로 바꾸지 않음. 게이트1 위반이 사용자 지정 성분뿐이면 '조건부'(칩은 실패 그대로). 결과 상단 '요청 해석' 카드가 인식된 요청·미반영 분량을 보여 줌 |
| 4 | 화면색 밝게 | **완료** | 라이트 기본 + OS 다크 자동 + 수동 토글(시스템/밝게/어둡게). 선택값은 `LOCALAPPDATA/PhramaProto/preferences.json`(`pharma_proto/preferences.py`, 허용 키만). 첫 화면은 서버가 `data-theme` 렌더 |
| 5 | 인쇄 | **완료** | '인쇄' 버튼 + `@media print`(밝은 토큰 강제, 컨트롤 숨김, 인쇄 머리글: 요청·시각·DB 스냅샷·모델·면책, 후속 질의응답 포함). `beforeprint` 에서 접힌 해설 펼침 |
| 6 | 비전문가용 설명, 근거 클릭 | **완료** | `generation/help_text.py` 한 곳의 문장을 사이드바와 팝오버가 공유. 근거 꼬리표·게이트 칩·상태 배지·근거/일반지식 배지가 `data-help` 버튼. 사이드바 '이 도구는 일반 AI 와 무엇이 다른가요?' |
| 7 | 로그아웃 | **완료** | `POST /api/logout` 이 키·대화를 비움. 버튼 '로그아웃 (API 키 삭제)', 설정 카드에 키 보관 방식 안내 |
| 8 | LLM 보다 품질 낮음 | **설명·(b)총중량 완료, (a)공정 규칙 미착수** | 사용자 총중량·분량 존중(3번과 같이), 해설층(이전 세션), '일반 AI 와 다른 점' 패널. 공정 규칙 JSON 설계는 `docs/design/liquid-dosage-forms.md` 하단 |
| 9 | 작업 저장 | **완료(수동)** | '이 결과 저장' → `LOCALAPPDATA/PhramaProto/results/<시각>-<대화id8>/`(request.json·독립 result.html·explanation.json·followup.json·xlsx). 사이드바 '저장된 작업': 열기(읽기 전용)·이어서 질문(저장된 ParsedRequest 로 결정적 재계산, LLM 호출 없음, 다른 스냅샷이면 409)·삭제 |

**디자인 전면 개편(2026-10-05, 사용자와 문답으로 결정)**: 연구 노트형(종이 톤 + 잉크 남색, DB 근거는 초록 유지), 작업대형 2단
(왼쪽 고정 열에 질문·후속 질문, 오른쪽에 결과), 후보가 2개 이상이면 결과 상단에 후보 요약 띠(`candidate_strip_html`, `#candidate-N` 앵커),
게이트 안내·저장된 작업은 상단 버튼으로 여는 옆 패널(`#side-panel`), 생성 중 스켈레톤·시작 안내(빈 상태), 예시 질문 칩, 종이 질감(`static/paper.svg`),
파비콘, 건너뛰기 링크. 글꼴은 **Pretendard Variable 동봉**(`static/fonts/`, OFL, 2 MB — 릴리스 허용목록에 들어 있음). 다크는 검정이 아니라 어두운 세피아.
'이 도구는 일반 AI 와 무엇이 다른가요?' 패널은 사용자 요청으로 삭제(README 에 내용 없음 — 평가자 8번 답은 해설 배지·근거 꼬리표·게이트 설명이 대신한다).

부수 수정: 릴리스 허용목록에 빠져 있던 `pharma_proto/excel_export.py`, `generation/explanation.py` 추가(배포본에서 생성 요청이 ImportError 나던 버그).
새 오류 코드: `REQUEST-FORM-001`, `CONVERSATION-001`, `RESULTS-001`, `RESULTS-IO-001`, `RESULTS-SNAPSHOT-001`, `PREFERENCES-IO-001`. `app.js` 의 `ERROR_MESSAGES` 가 코드 옆에 한국어 한 줄을 붙인다.

## 4. 남은 일 (우선순위 순)

1. **실제 LLM 으로 끝까지 검증**(§6). 특히 Gemini 의 `amounts`·`FollowUpResponse` 스키마(포터블 dict)와 Claude `messages.parse` 의 `FollowUpResponse`(중첩 `ParsedRequest`)가 실제로 통하는지. 실패하면 `LLM-RESPONSE-001` 과 로그의 `provider_reason` 을 본다.
2. **Windows 릴리스 ZIP 재생성 + 스모크**(`tools/build-release.ps1`, `check-release-tree.ps1`). 새 모듈: `conversation.py`, `preferences.py`, `results_store.py`, `generation/help_text.py`(+ 누락됐던 2개).
3. 8(a) 공정 규칙 `generation/process_rules.json` — DB 변경 없이 가능. 설계는 design 문서.
4. 2번 액제 지원 — DB 쪽 역할 사전·범위 표본이 먼저.
5. 선택: 자동 저장 옵션(지금은 수동), 저장 목록 검색, 결과 비교 화면.

## 5. 알아 둘 함정

- `run_generation` 은 spec 을 제자리에서 바꾼다(`excipient_choices`·`profile_id`·`selection_sources`). 재생성은 항상 `ParsedRequest.to_domain()` 으로. `Conversation.spec` 은 해설 payload 용으로만 읽는다.
- `_GenerateRequest` 는 `extra="forbid"` 이고 바꾸지 않았다(테스트가 추가 필드 거부를 확인). 새 요청은 새 모델(`_FollowUpRequest`, `_SaveRequest`, `_ResumeRequest`, `_PreferencesRequest`).
- 기존 가짜 서비스(`tests/product/test_mvp_app.py:FakeLLMService` 는 `parse` 만, `tests/test_web_workflow.py` 의 `_FakeLLMService` 는 `parse`+`explain`)가 그대로 돌아야 하므로 앱은 `parse_request`/`followup`/`explain` 을 `getattr` 로 찾는다. 후속 질문 테스트는 `_ConversationalFakeLLMService`.
- `tests/test_app_js.mjs` 는 가짜 DOM 의 `elements` 맵을 쓴다. `index.html` 에 id 를 추가하면 **같은 커밋에서** 맵에 넣어야 한다(없으면 `querySelector` 가 `undefined` 를 돌려줘 전체 JS 테스트가 깨진다). `fetch` 는 `routes["METHOD url"]` 로 응답을 꾸밀 수 있다.
- `allocate` 는 분량 지정이 없으면 예전과 수치가 같아야 한다 — `tests/test_user_amounts.py::test_allocate_without_amounts_is_unchanged` 가 실측값(833 mg, 4%, 27.976%)으로 고정.
- `generation_loop._distinct_picks` 는 후보 i 가 각 역할의 i번째 선택지를 쓰며, 성분이 겹치면 다음 조합으로 넘어간다.
- 역할별 범위가 표본 5 미만이거나 중앙값 0 이면 base 전체 범위로 떨어진다(`excipient_allocator._rep_pct`).
- 게이트2(제조성)는 대리지표이고, 화학 호환성 게이트는 아직 돌지 않는다. 해설·후속 답변의 Maillard 언급은 모델 일반 지식(general)이다.
- 특허 유래 용량이 많아 `api_doses()` 전체 분포 중앙값은 신뢰하지 말고 `approved_label` 모드를 먼저 본다(`dose_resolver`).
- 저장본 `result.html` 은 앱이 서빙하지 않는다(파일로만 연다). 앱 화면에는 마커 사이의 조각만 돌려준다. `followup.json` 의 turn 에 카드 html 이 들어 있어 '열기'가 질의응답을 그대로 그린다.
- `preferences.json` 은 허용 키(`theme`)만 읽는다. 비밀 모양 키는 쓰기 거부, 파일에 있어도 무시.

## 6. 수동 검증 시나리오 (실제 키 필요)

1. 3번: "아세트아미노펜 500 mg, MCC 20%, 크로스포비돈 4%, 스테아르산마그네슘 1%, 총 700 mg 속방정" → 표에 지정 % 와 '사용자 지정' 라벨, 총 700 mg, '요청 해석' 카드.
2. 1번: "총중량 650 mg 으로" → 표 교체 + 변경 한 줄; "왜 MCC 를 골랐어?" → 답변 카드와 근거/일반지식 배지.
3. 7·4·5: 로그아웃 뒤 `/health` providers false; 토글 3단 순환 후 새로고침 유지; 인쇄 미리보기에서 컨트롤 숨김·카드 분리·해설 펼침·밝은 색.
4. 9: 저장 → `%LOCALAPPDATA%\PhramaProto\results\<id>\` 파일 5종, 목록에서 열기·이어서 질문·삭제; `result.html` 을 브라우저로 직접 열어 서식 확인.
5. 6: 근거 꼬리표·게이트 칩·배지 클릭 → 팝오버, ESC 닫힘.
6. 2: "리도카인 2% 주사제" → 400 과 한국어 안내.

## 7. 새 세션 첫 명령 예시

"docs/handoffs/NEXT_CHAT_CONTEXT.md 와 CLAUDE.md 를 읽고, 실제 Claude 키로 §6 시나리오 1·2 를 돌려 본 뒤 문제를 고쳐."

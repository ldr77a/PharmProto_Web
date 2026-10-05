# 다음 세션 인수인계 (2026-10-05 저녁, 0.2.0 릴리스 준비 기준)

이 파일은 앱 저장소(PharmaProto-0.1)에서 새 Claude Code 세션을 열 때 첫 명령으로 읽히는 용도다.
DB 저장소(`../Pharma_Proto`)에서 작업하던 세션의 메모리는 폴더에 묶여 있어 여기서는 보이지 않는다. 필요한 맥락을 전부 적는다.

## 1. 현재 상태

- 앱 버전 **0.2.0**(`pharma_proto/__init__.py`, `pyproject.toml`, `uv.lock`). 폴더·데이터 경로 이름은 오타를 고친 `PharmaProto`
  (`~/Library/Application Support/PharmaProto` 또는 `%LOCALAPPDATA%\PharmaProto`; 옛 `PhramaProto` 폴더는 첫 실행 때 한 번 옮긴다).
- 브랜치 `feat/schema2-role-layer`, main 보다 27+ 커밋 앞. 피드백 9항목 대응 → 디자인 개편(연구 노트형) → 해설 분리(`/api/explain`) →
  schema 3(게이트1 저용량 오탐 수정) → 제외 성분·희석제 재배치 → 이름 오타 수정 → 0.2.0 버전 올림. 푸시·main 머지·태그는 사용자 결정.
  원격은 `https://github.com/ldr77a/PhramaProto-0.1.git`(저장소 이름은 아직 옛 표기).
- 스냅샷 `release-data/knowledge.sqlite` 는 **schema 3(20261005T070640Z)**, DB 저장소 `release-data/` 와 해시 동일, LFS 로 커밋됨.
  매니페스트 사본은 `docs/release/snapshot-20261005T070640Z-manifest.json`.
- 테스트: macOS 에서는 `LOCALAPPDATA=/tmp/localappdata uv run pytest -q --deselect tests/product/test_launcher.py --deselect tests/product/test_release_baseline.py --deselect tests/product/test_release_zip.py --deselect tests/product/test_windows_standalone.py`
  → **144 passed, 2 skipped**. 제외한 32개는 msvcrt·powershell 이 필요한 Windows 전용. JS 는 `node --test tests/test_app_js.mjs` → **11 passed**.
- 린트 `uv run ruff check .` 는 예전 코드의 스타일 경고 28건이 남아 있다(동작 무관). 새로 손댄 파일만 깨끗하게 유지한다.
- 릴리스 허용목록(`tools/build-release.ps1 $runtimePackageFiles`) 감사: 목록 54개 모두 존재, 앱이 import 하는 저장소 모듈 41개와 글꼴·svg 전부 포함(2026-10-05 확인).
  ZIP 에는 허용목록 + `start.bat`·`pyproject.toml`·`uv.lock`·`function_seed.json`·`README-RESEARCHER.md` + `tools/bootstrap-runtime.ps1`·`uv-windows-x64.sha256` + `release-data/` 만 들어간다.
  `docs/`, `tests/`, `CLAUDE.md`, 사용자 매뉴얼은 들어가지 않는다.
- 개발용 실행(macOS): `LOCALAPPDATA="$HOME/Library/Application Support" uv run python -c "from waitress import serve; from pharma_proto.app import create_app; serve(create_app(), host='127.0.0.1', port=8765, threads=4)"`.
  템플릿은 서버가 처음 한 번만 읽으므로 `index.html` 을 바꾸면 재시작해야 한다(정적 JS·CSS 는 바로 반영). 재시작하면 메모리의 키가 사라진다.
- 정식 실행은 Windows `start.bat`. **0.2.0 릴리스 ZIP 은 아직 만들지 않았다.** 빌드 스크립트는 `.venv\Scripts\python.exe` 와 PowerShell 전용 cmdlet 을 쓰므로 Windows 에서만 돈다:
  `pwsh tools/build-release.ps1` → `dist/PharmaProto-0.2.0-20261005T070640Z.zip`, 이어서 `check-release-tree.ps1`, 제외했던 Windows 테스트 32개, `docs/release/WINDOWS_SMOKE_CHECKLIST.md`.
- LLM 키는 화면의 "API 설정"에 넣는다(메모리에만, 로그아웃이 지움). 개발 중 Claude 키는 `../Pharma_Proto/.env` 의 `CLAUDE_API_KEY` 에 있다. 채팅에 붙이지 말 것.
- 실제 LLM 검증: Claude 로 생성·해설은 여러 번 성공(진단 로그 `generation_complete`·`explanation_complete`, 해설 속도 실측은 아래 절).
  **후속 질문·저장·이어서 질문은 실제 키로 돌린 기록이 없고, Gemini·OpenAI 는 실제 호출 기록이 전혀 없다.**

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
| 4 | 화면색 밝게 | **완료** | 라이트 기본 + OS 다크 자동 + 수동 토글(시스템/밝게/어둡게). 선택값은 `LOCALAPPDATA/PharmaProto/preferences.json`(`pharma_proto/preferences.py`, 허용 키만). 첫 화면은 서버가 `data-theme` 렌더 |
| 5 | 인쇄 | **완료** | '인쇄' 버튼 + `@media print`(밝은 토큰 강제, 컨트롤 숨김, 인쇄 머리글: 요청·시각·DB 스냅샷·모델·면책, 후속 질의응답 포함). `beforeprint` 에서 접힌 해설 펼침 |
| 6 | 비전문가용 설명, 근거 클릭 | **완료** | `generation/help_text.py` 한 곳의 문장을 사이드바와 팝오버가 공유. 근거 꼬리표·게이트 칩·상태 배지·근거/일반지식 배지가 `data-help` 버튼. 사이드바 '이 도구는 일반 AI 와 무엇이 다른가요?' |
| 7 | 로그아웃 | **완료** | `POST /api/logout` 이 키·대화를 비움. 버튼 '로그아웃 (API 키 삭제)', 설정 카드에 키 보관 방식 안내 |
| 8 | LLM 보다 품질 낮음 | **설명·(b)총중량 완료, (a)공정 규칙 미착수** | 사용자 총중량·분량 존중(3번과 같이), 해설층(이전 세션), '일반 AI 와 다른 점' 패널. 공정 규칙 JSON 설계는 `docs/design/liquid-dosage-forms.md` 하단 |
| 9 | 작업 저장 | **완료(수동)** | '이 결과 저장' → `LOCALAPPDATA/PharmaProto/results/<시각>-<대화id8>/`(request.json·독립 result.html·explanation.json·followup.json·xlsx). 사이드바 '저장된 작업': 열기(읽기 전용)·이어서 질문(저장된 ParsedRequest 로 결정적 재계산, LLM 호출 없음, 다른 스냅샷이면 409)·삭제 |

**디자인 전면 개편(2026-10-05, 사용자와 문답으로 결정)**: 연구 노트형(종이 톤 + 잉크 남색, DB 근거는 초록 유지), 작업대형 2단
(왼쪽 고정 열에 질문·후속 질문, 오른쪽에 결과), 후보가 2개 이상이면 결과 상단에 후보 요약 띠(`candidate_strip_html`, `#candidate-N` 앵커),
게이트 안내·저장된 작업은 상단 버튼으로 여는 옆 패널(`#side-panel`), 생성 중 스켈레톤·시작 안내(빈 상태), 예시 질문 칩, 종이 질감(`static/paper.svg`),
파비콘, 건너뛰기 링크. 글꼴은 **Pretendard Variable 동봉**(`static/fonts/`, OFL, 2 MB — 릴리스 허용목록에 들어 있음). 다크는 순검정이 아닌 중립 회색 계열(사용자 요청으로 갈색 톤에서 변경).
'이 도구는 일반 AI 와 무엇이 다른가요?' 패널은 사용자 요청으로 삭제(README 에 내용 없음 — 평가자 8번 답은 해설 배지·근거 꼬리표·게이트 설명이 대신한다).

부수 수정: 릴리스 허용목록에 빠져 있던 `pharma_proto/excel_export.py`, `generation/explanation.py` 추가(배포본에서 생성 요청이 ImportError 나던 버그).
새 오류 코드: `REQUEST-FORM-001`, `CONVERSATION-001`, `RESULTS-001`, `RESULTS-IO-001`, `RESULTS-SNAPSHOT-001`, `PREFERENCES-IO-001`. `app.js` 의 `ERROR_MESSAGES` 가 코드 옆에 한국어 한 줄을 붙인다.

## 4. 남은 일 (우선순위 순)

1. **0.2.0 릴리스 마무리(Windows)**: `pwsh tools/build-release.ps1` → ZIP, `check-release-tree.ps1`, Windows 전용 테스트 32개, 스모크 체크리스트. 끝나면 `docs/release/` 에 빌드가 만든 릴리스 매니페스트를 커밋하고 태그 `v0.2.0`.
2. **후속 질문·저장·이어서 질문을 실제 Claude 키로 한 번**(§6 의 2·4). Gemini 를 쓸 연구자가 있으면 Gemini 로 생성 1회 — `amounts`·`excluded`·`FollowUpResponse` 포터블 스키마가 실제로 통하는지. 실패하면 `LLM-RESPONSE-001` 과 로그의 `provider_reason` 을 본다.
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
4. 9: 저장 → `%LOCALAPPDATA%\PharmaProto\results\<id>\` 파일 5종, 목록에서 열기·이어서 질문·삭제; `result.html` 을 브라우저로 직접 열어 서식 확인.
5. 6: 근거 꼬리표·게이트 칩·배지 클릭 → 팝오버, ESC 닫힘.
6. 2: "리도카인 2% 주사제" → 400 과 한국어 안내.

## 7. 새 세션 첫 명령 예시

"docs/handoffs/NEXT_CHAT_CONTEXT.md 와 CLAUDE.md 를 읽고, 실제 Claude 키로 §6 시나리오 1·2 를 돌려 본 뒤 문제를 고쳐."

## 해설 속도 (2026-10-05 추가)

해설은 생성 결과를 입력으로 쓰므로 두 번째 LLM 호출을 없앨 수는 없다. 대신 가볍게 만들었다(실측, 트리메타지딘 3후보, Claude Sonnet 5.5):
- effort high · 전체 해설: 91s, 출력 14k 토큰 → effort low · 분량 제한 · 후보 2 이후는 차이점만: 26~27s.
- 적용 위치: `llm/service.py` `_structured_call(effort=...)`(Claude 만 output_config.effort), `EXPLAIN_INSTRUCTION` 8번 규칙.
- (적용됨) 해설은 `/api/generate` 밖으로 뺐다. 표는 파싱+생성만으로 뜨고, app.js 가 후보 1 은 자동으로, 나머지는 '해설 보기' 버튼으로 `POST /api/explain {conversation_id, candidate_idx}` 를 부른다. 서버는 후보 하나짜리 payload 로 해설을 받아 `conversation.explanation.candidates` 에 누적하고 `conversation.html` 을 다시 그린다(저장·후속·재개가 같은 해설을 본다). 저장은 해설이 붙은 뒤에 해야 저장본에 들어간다. 후속 '수정' 재생성 뒤에는 후보 1 해설을 다시 자동으로 부른다. 저장본 '열기'(대화 없음)는 버튼을 숨긴다.

## 제형 거부·코팅 목록·후보 조합 (2026-10-05 추가)

- `REQUEST-FORM-001`(경구 고형제만 지원) 오탐 수정: 비고형 판정이 질문 전체가 아니라 `dosage_form` 만 보고, 단어 경계로 찾는다(`is_oral_solid`). '포비돈 결합액(binder solution)', 'dissolution', 'gelatin' 에 더 이상 걸리지 않는다. 고형제 단어(tablet·capsule·정제…)가 있으면 무조건 통과.
- LLM 이 돌려주는 영문 역할 표현(`film coating`, `colorant`, `pigment`, `filler`, `dry binder` …)을 생성기 역할로 매핑(`_ROLE_NORMALIZED_ALIASES`). 전에는 `film_coating_agent` 가 역할 이름 그대로 표에 찍혔다.
- 사용자가 '코팅: HPMC, PEG6000, 탈크, 색소' 처럼 코팅 시스템을 통째로 적으면 역할 사전(없으면 이름 규칙)으로 가소제·활택보조·착색제 자리로 가르고 코팅 자리엔 피막 형성제만 남긴다(`candidate_selector._split_coating_system`, `coating_system_role`).
- `_distinct_picks`: 같은 성분이 두 역할에 걸리면(활택제 talc·활택보조 talc) 조합을 통째로 버리지 않고 그 역할만 다음 선택지로 넘기거나 뺀다. 후보 1 이 사용자가 첫 번째로 적은 성분을 그대로 쓴다.
- 검증 사례: NDMA 질문(트리메타지딘 20 mg, 95 mg, 직타/건식과립, MCC PH102). 후보 1 = MCC 결합제·talc 활택제·HPMC 코팅·PEG 가소제·색소·CCS·mannitol q.s. 해설은 2차 아민과 아질산염 불순물에 의한 니트로소아민 위험을 '일반 지식'으로 언급한다.

## 게이트1 저용량 오탐 수정 — schema 3 (2026-10-05 추가)

- 증상: 암로디핀 5 mg/100 mg 직타정에서 MCC 86% 가 "범위 벗어남(p95=62.89%)" 하드 실패. 원인은 잔여 채움 희석제의 % 가 100−API−나머지로 결정되는 값인데 모든 API 함량을 합친 성분 범위로 심사한 것. 같은 DB 에서 API ≤5% 구간만 보면 MCC p95 96.5%, 최대 희석제 p95 96.5%.
- DB 저장소: export 때 역할 추정으로 배합별 '가장 큰 희석제 %' 를 API 함량 구간(le5·5_10·10_25·25_50·gt50, `contracts.api_load_band`)별로 집계한 `lookup_filler_pct_ranges`(성분별 행은 표본 5 이상, 전체는 `*`). 계약 메서드 `filler_pct_range(ingredient, band)`. `SUPPORTED_SCHEMA_VERSIONS={3}`, 스냅샷 `20261005T070640Z`.
- 앱: `Component.filler`(allocator 가 q.s. 희석제에 표시) → `gates/allowable_range.py` 가 filler 만 구간 분포로 심사, 표본 없으면 전체 범위. 표기 "KG 잔여채움·API ≤5%[p5~p95=…]".
- 계약 파일 3개(contracts·snapshot·sqlite_repository)는 publish 로 복사된 것. 앱에서 고치지 말 것.

## 기존 조성을 적은 질문 처리 (2026-10-05 추가, 커밋 6a923f2·9bcba32)

- 증상: NDMA 질문에서 후보 1 엑셀에 D-만니톨이 없고 옥수수전분만 있었다. 파서가 희석제를 ['corn starch', 'D-mannitol'] 순으로 돌려주고 앱은 한 역할의 여러 성분을 '후보마다 하나씩' 쓰기 때문.
- `candidate_selector._reroute_diluents_by_primary_role`: 희석제 목록 중 역할 사전 기본 역할이 붕해제·결합제·활택보조·활택제인 성분(옥수수전분→붕해제)은 그 역할로 옮긴다. 진짜 희석제가 하나도 안 남으면 그대로 둔다.
- `ParsedRequest.excluded`: '포비돈 대신 MCC', '유당을 다른 희석제로' 같은 교체·제거 요청을 파서가 `excluded` 로 돌려주고, 선택기가 사용자 목록·DB 후보·검토 기본값 모두에서 뺀다(Gemini 스키마·해설 payload 에도 반영). 파싱 지시문에 '언급 성분 누락 금지·언급 순서 유지·제외 성분' 규칙 추가.
- 코팅 역할 영문 표현 보강(film coating polymer, anti-tacking agent → glidant 등).
- 검증: NDMA 질문 두 번 연속 후보 1 = MCC 결합제·탈크 활택제·HPMC 코팅·PEG·색소·옥수수전분 붕해제 7.5%·만니톨 q.s. 46%, 포비돈 없음.

# 설계 메모 — 비고형 제형(액제) 지원과 공정 규칙 (피드백 2번, 8(a))

작성 2026-10-04. 아직 구현하지 않은 항목의 설계와 데이터 요구사항을 적어 둔다. 앱 저장소와 DB 저장소
양쪽 작업이 필요하며, DB 쪽이 먼저다.

## 지금 상태

- 앱은 경구 고형제(정제·캡슐·과립·펠릿·산제, `generation/oral_solid_profiles.py` 의 10개 프로파일)만 지원한다.
- 액제·주사제 등은 `resolve_profile` 이 `UnsupportedDosageForm` 을 올리고, 앱은 `400 REQUEST-FORM-001`
  ("현재는 경구 고형제만 지원합니다")로 안내한다. 예전에는 500 이었다.
- 스냅샷에는 이미 suspension 168건·solution 131건 등 비고형 배합이 있고 역할 표(`lookup_role_*`)도 제형별로 있다.
  다만 분량 통계가 특허 유래라 약하다.

## 평가자 질문에 대한 답: "추가 제형은 LLM 학습방법을 그대로?"

아니다. 이 도구의 숫자는 LLM 이 아니라 지식 데이터베이스가 만든다. 새 제형을 지원하려면
(1) DB 에 그 제형의 배합·문헌을 적재하고, (2) 제형별 역할 사전과 범위 표를 만들고, (3) 앱에 제형 프로파일과
단위·게이트 규칙을 추가한다. LLM 쪽은 프롬프트 문구("경구 고형제")를 일반화하는 정도다.

## 앱 쪽 변경 (DB 가 준비된 뒤)

1. **프로파일 일반화** — `OralSolidProfile` 을 `DosageFormProfile` 로:
   `profile_id`, `dosage_form_bases`, `auto_roles`, `required_functions` 에 더해
   `filler_role`(고형: `diluent`, 액제: `vehicle`/`solvent`), `unit`(`mg` | `mg/mL` | `% w/v`),
   `total_label`("총중량" | "총부피"), `release_profile_keywords`. `_NON_ORAL_SOLID` 토큰 목록 대신
   "지원 프로파일에 매칭되지 않으면 거절"로 바꾼다. "gel" 이 "hard gelatin capsule" 에 걸리는 부분 문자열 문제도
   이때 토큰 매칭을 단어 경계로 고친다.
2. **배분(`excipient_allocator.allocate`)** — q.s. 역할을 하드코딩된 `"diluent"` 대신 `profile.filler_role` 로 받는다.
   액제는 `target_total` 이 부피(mL)이고 성분은 mg/mL 또는 % w/v 로 들어온다. `Alloc` 에 `unit` 을 추가하고,
   `candidate_rows`·엑셀·HTML 표의 열 머리글을 프로파일 단위로 바꾼다.
3. **게이트** — 게이트3(총량)·4(합계)는 단위만 바꾸면 그대로. 게이트2(제조성 대리지표)는 고형 전용 규칙이므로
   액제 프로파일에서는 건너뛰고(`skip`), 대신 액제용 대리지표(보존제 유무, pH 조절제 유무, 현탁화제 비율)를
   `gates/manufacturability.py` 에 프로파일 분기로 넣는다. 게이트5(필수 기능)는 프로파일의 `required_functions` 를 쓴다.
4. **입력 스키마** — `ParsedRequest.dosage_form` 은 자유 문자열이라 그대로. `amounts` 의 `mg|pct` 에
   `mg_per_ml` 을 추가하거나, 액제에서는 `pct` 를 % w/v 로 해석한다(프롬프트에 명시).
5. **해설·후속 프롬프트** — `EXPLAIN_INSTRUCTION`·`FOLLOWUP_INSTRUCTION` 의 "경구 고형제" 를 프로파일 이름으로 치환.
6. **설명 사전(`generation/help_text.py`)** — 액제 게이트·단위 설명 추가.

## DB 쪽 요구사항 (Pharma_Proto)

- 액제 역할 사전: `solvent`/`vehicle`, `preservative`, `buffer`, `sweetener`, `flavoring_agent`, `suspending_agent`,
  `viscosity_agent`, `wetting_agent`, `antioxidant`, `chelating_agent`, `cosolvent`.
- 제형별 역할 범위 표본: suspension·solution·syrup 각각 `role_pct_range` n ≥ 5 가 되도록. 특허 유래 분량만으로
  부족하면 승인 라벨(액제) 적재가 필요하다.
- `function_taxonomy.ROLE_ALIASES` 에 위 역할의 KG 기능명 매핑(계약 파일이므로 DB 저장소에서 바꾸고 publish).
- 스냅샷 `schema_version` 을 올릴 필요는 없다(표 구조는 같고 행만 늘어난다). 올리면 앱의 `SUPPORTED_SCHEMA_VERSIONS`
  (계약 파일 `snapshot.py`)도 같이 publish 돼야 한다.

## 공정 규칙 (8(a)) — `generation/process_rules.json` (앱 소유 런타임 데이터)

현재 `spec.process` 는 프로파일 키워드 매칭에만 쓰이고 조성에는 영향이 없다. 제안:

```json
{
  "direct_compression": {
    "aliases": ["직타", "직접타정", "direct compression", "dc"],
    "required_roles": ["diluent", "lubricant"],
    "recommended_roles": ["glidant"],
    "prefer_candidates": {"diluent": ["microcrystalline cellulose", "lactose monohydrate"]},
    "notes": ["직타용 등급(예: MCC PH-102, 분무건조 유당)이 흐름성을 좌우한다"]
  },
  "wet_granulation": {
    "aliases": ["습식", "습식과립", "wet granulation"],
    "required_roles": ["binder", "diluent", "disintegrant", "lubricant"],
    "notes": ["결합제는 용액으로 넣는 경우가 많아 건조 후 잔류 수분을 확인한다"]
  },
  "dry_granulation": {"aliases": ["건식", "롤러컴팩션", "roller compaction", "dry granulation"], "required_roles": ["binder", "diluent", "lubricant"]}
}
```

적용 지점: `candidate_selector.complete_excipient_choices` 가 `required_roles`·`recommended_roles` 를 프로파일의
`auto_roles` 에 합치고, `prefer_candidates` 는 DB 후보 순위에서 우선 배치(DB 에 있는 것만), `notes` 는 해설 payload 의
`request.process_hints` 로 넘겨 LLM 의 `process_notes` 가 근거(evidence) 로 인용하게 한다. 게이트5 는 공정별
`required_roles` 를 `required_functions` 에 더해 검사한다.

## 순서 제안

1. DB: 액제 역할 사전·범위 표본 확보 → publish.
2. 앱: 프로파일 일반화 + 배분 단위 + 게이트 분기 + 표 열 머리글 (테스트: FakeKnowledge 에 액제 역할 범위 넣어 한 후보 생성).
3. 앱: 공정 규칙 JSON + 선정·게이트5·해설 힌트 (DB 변경 없이 가능 — 2번보다 먼저 해도 된다).

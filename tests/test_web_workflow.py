from __future__ import annotations

import base64
import json
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from openpyxl import load_workbook

import pharma_proto.app as app_module
from gates.formulation import Component, GateResult
from generation.dose_resolver import DoseResult
from generation.excipient_allocator import Alloc
from generation.generation_loop import Candidate
from pharma_proto.app import create_app, shutdown_app_resources
from pharma_proto.excel_export import candidate_workbook
from pharma_proto.llm.resilience import LLMFailure

ROOT = Path(__file__).resolve().parents[1]


class _ElementProbe(HTMLParser):
    _VOID_TAGS: ClassVar[frozenset[str]] = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self.elements: dict[str, dict[str, object]] = {}
        self._stack: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id is not None:
            self.elements[element_id] = {"attrs": attributes, "text": []}
        if tag not in self._VOID_TAGS:
            self._stack.append(element_id)

    def handle_endtag(self, tag: str) -> None:
        self._stack.pop()

    def handle_data(self, data: str) -> None:
        for element_id in self._stack:
            if element_id is not None:
                text = self.elements[element_id]["text"]
                assert isinstance(text, list)
                text.append(data)

    def attrs(self, element_id: str) -> dict[str, str | None]:
        attrs = self.elements[element_id]["attrs"]
        assert isinstance(attrs, dict)
        return attrs

    def text(self, element_id: str) -> str:
        text = self.elements[element_id]["text"]
        assert isinstance(text, list)
        return " ".join("".join(text).split())


class _FakeLLMService:
    def __init__(self, spec: SimpleNamespace, explanation=None, explain_failure=None) -> None:
        self._spec = spec
        self._explanation = explanation
        self._explain_failure = explain_failure
        self.explain_payloads: list[dict] = []

    def parse(self, provider: str, tier: str, api_key: str, question: str):
        return self._spec

    def explain(self, provider: str, tier: str, api_key: str, payload: dict):
        self.explain_payloads.append(payload)
        if self._explain_failure is not None:
            raise self._explain_failure
        if self._explanation is None:
            raise LLMFailure("LLM-RESPONSE-001", False)
        return self._explanation


class _FailingLLMService:
    def __init__(self, failure: LLMFailure) -> None:
        self._failure = failure

    def parse(self, provider: str, tier: str, api_key: str, question: str):
        raise self._failure


class _ParsedRequestLLMService:
    """실제 ParsedRequest → to_domain() 경로를 타는 가짜(분량 지정 포함). 해설은 건너뛴다."""

    def __init__(self, parsed) -> None:
        self._parsed = parsed

    def parse(self, provider: str, tier: str, api_key: str, question: str):
        return self._parsed.to_domain()


class _ConversationalFakeLLMService:
    """parse_request / explain / followup 를 모두 갖춘 가짜 — 후속 질문 경로용."""

    def __init__(self, parsed, *, explanation=None, reply=None) -> None:
        self._parsed = parsed
        self._explanation = explanation
        self._reply = reply
        self.followup_payloads: list[dict] = []
        self.explain_calls = 0

    def parse_request(self, provider: str, tier: str, api_key: str, question: str):
        return self._parsed

    def explain(self, provider: str, tier: str, api_key: str, payload: dict):
        self.explain_calls += 1
        if self._explanation is None:
            raise LLMFailure("LLM-RESPONSE-001", False)
        return self._explanation

    def followup(self, provider: str, tier: str, api_key: str, payload: dict):
        self.followup_payloads.append(payload)
        if self._reply is None:
            raise LLMFailure("LLM-RESPONSE-001", False)
        return self._reply


def _parsed_request(**overrides):
    from pharma_proto.llm.schema import ParsedRequest

    base = {"apis": [{"name": "acetaminophen", "dose_mg": 500}], "n_candidates": 2}
    base.update(overrides)
    return ParsedRequest.model_validate(base)


def _followup_reply(**fields):
    from pharma_proto.llm.schema import FollowUpResponse

    return FollowUpResponse.model_validate(fields)


def _count_generations(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    real = app_module.run_generation
    calls: list[int] = []

    def counting(spec, *, repository, offline):
        calls.append(1)
        return real(spec, repository=repository, offline=offline)

    monkeypatch.setattr(app_module, "run_generation", counting)
    return calls


@pytest.fixture
def app_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    apps = []

    def build(*, llm_service=None):
        overrides = {
            "SNAPSHOT_PATH": ROOT / "release-data" / "knowledge.sqlite",
            "MANIFEST_PATH": ROOT / "release-data" / "manifest.json",
        }
        if llm_service is not None:
            overrides["LLM_SERVICE"] = llm_service
        app = create_app(overrides)
        app.config["TESTING"] = True
        apps.append(app)
        return app

    yield build

    for app in apps:
        shutdown_app_resources(app)


def _candidate(index: int) -> Candidate:
    api = Component(
        "Acetaminophen",
        role="api",
        mg=500.0,
        pct=83.333,
        function="api",
    )
    diluent = Component(
        "Microcrystalline cellulose",
        role="excipient",
        mg=100.0,
        pct=16.667,
        function="diluent",
    )
    gate = GateResult("게이트1 사용량 범위", "pass", "사용량 범위 충족")
    return Candidate(
        idx=index,
        pick={"diluent": "Microcrystalline cellulose"},
        doses=[DoseResult("Acetaminophen", 500.0, "user", "사용자 지정")],
        allocs=[
            Alloc(
                "Microcrystalline cellulose",
                "diluent",
                16.667,
                "filler(q.s.)",
                mg=100.0,
            )
        ],
        components=[api, diluent],
        total_mg=600.0,
        gate_out={"warnings": [], "hard_fails": [], "results": [gate]},
        status="pass",
    )


def test_first_load_only_exposes_api_setup(app_factory) -> None:
    response = app_factory().test_client().get("/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    probe = _ElementProbe()
    probe.feed(page)

    assert 'data-theme="light"' in page                                   # 기본은 밝은 화면
    assert probe.attrs("theme-toggle")["aria-label"] == "어두운 화면으로 전환"   # 오른쪽 아래 해·달 버튼
    assert probe.attrs("theme-toggle")["class"] == "theme-fab" and probe.text("print") == "인쇄"
    assert "hidden" not in probe.attrs("api-setup")
    assert "hidden" in probe.attrs("research-app")
    assert "hidden" in probe.attrs("review-notice")
    assert "hidden" in probe.attrs("followup-panel")
    assert probe.text("api-cost-notice") == "외부 AI API 호출은 과금 대상입니다."
    assert "파일에 저장하지 않습니다" in probe.text("key-notice")
    assert "hidden" in probe.attrs("resume-key") and probe.text("continue-key") == "저장된 키로 계속"
    assert "연구 검토용 시제품입니다." not in probe.text("api-setup")
    assert "로그아웃 (API 키 삭제)" in probe.text("research-app")
    assert "API 설정 변경" not in probe.text("research-app")

    catalog = json.loads(probe.text("model-catalog"))
    assert catalog == {
        "openai": {
            "cheap": "gpt-5.6-luna",
            "normal": "gpt-5.6-terra",
            "good": "gpt-5.6-sol",
        },
        "gemini": {
            "cheap": "gemini-3.5-flash-lite",
            "normal": "gemini-3.7-flash",
            "good": "gemini-3.1-pro-preview",
        },
        "claude": {
            "cheap": "claude-haiku-4-5-20251001",
            "normal": "claude-sonnet-5-5",
            "good": "claude-opus-5-5",
        },
    }


def test_research_screen_contains_collapsed_five_gate_guide(app_factory) -> None:
    response = app_factory().test_client().get("/")
    probe = _ElementProbe()
    probe.feed(response.get_data(as_text=True))

    assert "gate-guide" in probe.elements
    assert "open" not in probe.attrs("gate-guide")
    guide = probe.text("gate-guide")
    for gate in (
        "게이트1 사용량 범위",
        "게이트2 제조성 대리지표",
        "게이트3 총량 제약",
        "게이트4 조성 합계",
        "게이트5 필수 기능 구성",
    ):
        assert gate in guide
    assert "게이트6" not in guide
    assert "화학적 호환성" not in guide

    # 피드백 6번: 사이드바 문장과 클릭 설명 사전이 같은 소스(generation/help_text.py)에서 나온다.
    from generation.help_text import GATES

    help_text = json.loads(probe.text("help-text"))
    for gate in GATES:
        assert gate["text"] in guide
        assert help_text[gate["key"]] == {"title": gate["title"], "text": gate["text"]}
    assert "src:kg_role" in help_text and "basis:general" in help_text and "status:unresolved" in help_text
    assert "hidden" in probe.attrs("help-popover")
    # 안내는 옆 패널(닫힌 상태)로 옮겼고, '일반 AI 와 다른 점' 패널은 없앴다.
    assert "hidden" in probe.attrs("side-panel") and "hidden" in probe.attrs("gate-guide")
    assert "about-tool" not in probe.elements
    assert probe.text("open-gates") == "게이트 안내" and probe.text("open-saved") == "저장된 작업"
    assert "hidden" not in probe.attrs("results-empty") and "시작하기" in probe.text("results-empty")
    assert "hidden" in probe.attrs("results-skeleton")


def test_generate_returns_one_real_xlsx_download_per_candidate(
    app_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = SimpleNamespace(
        apis=[SimpleNamespace(name="Acetaminophen")],
        dosage_form="tablet",
        process="direct compression",
        profile_id="immediate_release_tablet",
    )
    monkeypatch.setattr(
        app_module,
        "run_generation",
        lambda spec, *, repository, offline: [_candidate(i) for i in range(1, 4)],
    )
    client = app_factory(llm_service=_FakeLLMService(spec)).test_client()
    assert client.post(
        "/api/key",
        json={"provider": "openai", "api_key": "test-key"},
    ).status_code == 200

    response = client.post(
        "/api/generate",
        json={
            "provider": "openai",
            "tier": "normal",
            "question": "아세트아미노펜 500 mg 정제",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["html"].count('class="download-xlsx ') == 3
    # 피드백 6번: 배지·게이트 칩·근거 꼬리표가 클릭 설명 키를 갖는다
    assert payload["html"].count("data-help='status:pass'") == 3
    assert payload["html"].count("data-help='gate:1'") == 3
    assert "data-help='src:filler(q.s.)'" in payload["html"] and "data-help='src:user'" in payload["html"]
    assert [item["candidate_idx"] for item in payload["downloads"]] == [1, 2, 3]
    assert [item["filename"] for item in payload["downloads"]] == [
        "조성_후보_1.xlsx",
        "조성_후보_2.xlsx",
        "조성_후보_3.xlsx",
    ]

    workbook_bytes = base64.b64decode(payload["downloads"][0]["content_base64"])
    workbook = load_workbook(BytesIO(workbook_bytes), data_only=True)
    sheet = workbook.active
    assert sheet.title == "조성 후보 1"
    assert sheet["A1"].value == "조성 후보 1"
    assert [sheet.cell(5, column).value for column in range(1, 6)] == [
        "성분",
        "기능",
        "mg",
        "%",
        "근거",
    ]
    assert [sheet.cell(6, column).value for column in range(1, 6)] == [
        "Acetaminophen",
        "API",
        500.0,
        83.33,
        "사용자 지정",
    ]
    assert [sheet.cell(8, column).value for column in range(1, 6)] == [
        "합계",
        None,
        600.0,
        100.0,
        "총중량 600mg",
    ]


def test_generate_echoes_parsed_request_and_user_amounts(app_factory) -> None:
    """피드백 3번: 사용자가 적은 분량·총중량이 표에 그대로 들어가고 '요청 해석'에 에코된다(실제 스냅샷)."""
    from pharma_proto.llm.schema import ParsedRequest

    parsed = ParsedRequest.model_validate({
        "apis": [{"name": "acetaminophen", "dose_mg": 500}],
        "disintegrant": ["croscarmellose sodium"],
        "amounts": [{"ingredient": "croscarmellose sodium", "pct": 4}],
        "target_total_mg": 700,
        "n_candidates": 1,
    })
    client = app_factory(llm_service=_ParsedRequestLLMService(parsed)).test_client()
    assert client.post("/api/key", json={"provider": "openai", "api_key": "test-key"}).status_code == 200

    response = client.post("/api/generate", json={
        "provider": "openai", "tier": "normal",
        "question": "아세트아미노펜 500 mg, 크로스카르멜로스나트륨 4%, 총 700 mg 정제",
    })

    assert response.status_code == 200
    html = response.get_json()["html"]
    assert "<header class='print-header print-only'>" in html          # 인쇄·저장본 머리글(화면 숨김)
    assert "아세트아미노펜 500 mg, 크로스카르멜로스나트륨 4%, 총 700 mg 정제" in html
    assert "<dt>DB 스냅샷</dt>" in html and "<dt>모델</dt><dd>gpt-5.6-terra</dd>" in html
    assert "요청 해석" in html
    assert "Acetaminophen 500 mg (사용자 지정)" in html
    assert "700 mg (사용자 지정)" in html
    assert "Croscarmellose sodium 4%" in html                       # 지정 분량 에코
    assert ("4.00</td><td class='ev '><button type='button' class='help-trigger' "
            "data-help='src:user'>사용자 지정</button></td>") in html     # 표의 % 와 근거 라벨(클릭 설명)
    assert "총중량 700mg" in html
    assert "미반영 분량" not in html


def test_followup_refine_regenerates_from_the_revised_request(app_factory, monkeypatch) -> None:
    """피드백 1번: '후보 1개, 총중량 650' 같은 수정 요청은 새 요청으로 다시 생성한다(실제 스냅샷)."""
    parsed = _parsed_request()
    reply = _followup_reply(action="refine", request=_parsed_request(n_candidates=1, target_total_mg=650),
                            note="후보 1개, 총중량 650 mg 으로.")
    service = _ConversationalFakeLLMService(parsed, explanation=_explanation(), reply=reply)
    calls = _count_generations(monkeypatch)
    client = app_factory(llm_service=service).test_client()
    assert client.post("/api/key", json={"provider": "claude", "api_key": "test-key"}).status_code == 200

    first = client.post("/api/generate", json={"provider": "claude", "tier": "normal",
                                               "question": "아세트아미노펜 500 mg 정제 후보 2개"})
    assert first.status_code == 200
    conversation_id = first.get_json()["conversation_id"]
    assert len(conversation_id) == 32 and first.get_json()["html"].count("조성 후보 ") == 2

    second = client.post("/api/followup", json={"provider": "claude", "tier": "normal",
                                                "conversation_id": conversation_id,
                                                "question": "후보 1개, 총중량 650 mg 으로"})

    assert second.status_code == 200
    data = second.get_json()
    assert data["action"] == "refine" and data["changed"] is True
    assert data["conversation_id"] == conversation_id
    assert data["html"].count("조성 후보 ") == 1 and "총중량 650mg" in data["html"]
    # 후보 카드는 접이식(details): 머리줄에 제목·상태·핵심 부형제·총중량, 기본은 펼침
    assert first.get_json()["html"].count('<details class="card candidate"') == 2
    assert 'id="candidate-1" open' in first.get_json()["html"]
    assert first.get_json()["html"].count('<summary class="candidate-summary">') == 2
    assert "candidate-strip" not in first.get_json()["html"]
    assert len(data["downloads"]) == 1
    assert "후보 수: 2 → 1" in data["answer_html"] and "총중량: 자동 → 650 mg" in data["answer_html"]
    assert "후보 1개, 총중량 650 mg 으로." in data["answer_html"]
    assert calls == [1, 1] and service.explain_calls == 2
    payload = service.followup_payloads[0]
    assert payload["previous_request"]["apis"][0]["name"] == "acetaminophen"
    assert payload["question"] == "후보 1개, 총중량 650 mg 으로"
    assert payload["turns"][0]["kind"] == "question"
    assert [c["candidate_idx"] for c in payload["result"]["candidates"]] == [1, 2]
    assert payload["previous_explanation_summaries"][0]["summary"] == "단순 직타 조성."


def test_followup_answer_renders_basis_badges_without_regenerating(app_factory, monkeypatch) -> None:
    parsed = _parsed_request(n_candidates=1)
    reply = _followup_reply(action="answer", request=parsed, answer=[
        {"text": "희석제는 역할별 범위 안이다.", "basis": "evidence", "refs": ["KG 역할별 범위 n=2034"]},
        {"text": "흡습성은 실험으로 확인한다.", "basis": "general"},
    ])
    service = _ConversationalFakeLLMService(parsed, reply=reply)
    calls = _count_generations(monkeypatch)
    client = app_factory(llm_service=service).test_client()
    client.post("/api/key", json={"provider": "openai", "api_key": "test-key"})
    first = client.post("/api/generate", json={"provider": "openai", "tier": "normal", "question": "q"}).get_json()

    second = client.post("/api/followup", json={"provider": "openai", "tier": "normal",
                                                "conversation_id": first["conversation_id"],
                                                "question": "왜 이 희석제를 골랐어?"})

    assert second.status_code == 200
    data = second.get_json()
    assert data["action"] == "answer" and "changed" not in data
    assert data["html"] == first["html"]
    assert "class='basis ev'" in data["answer_html"] and "class='basis gen'" in data["answer_html"]
    assert "왜 이 희석제를 골랐어?" in data["answer_html"] and "KG 역할별 범위 n=2034" in data["answer_html"]
    assert calls == [1]


def test_followup_refine_without_changes_keeps_the_result(app_factory, monkeypatch) -> None:
    parsed = _parsed_request(n_candidates=1)
    service = _ConversationalFakeLLMService(parsed, reply=_followup_reply(action="refine", request=parsed))
    calls = _count_generations(monkeypatch)
    client = app_factory(llm_service=service).test_client()
    client.post("/api/key", json={"provider": "openai", "api_key": "test-key"})
    first = client.post("/api/generate", json={"provider": "openai", "tier": "normal", "question": "q"}).get_json()

    second = client.post("/api/followup", json={"provider": "openai", "tier": "normal",
                                                "conversation_id": first["conversation_id"],
                                                "question": "그대로 해 줘"}).get_json()

    assert second["action"] == "refine" and second["changed"] is False
    assert second["html"] == first["html"]
    assert "변경할 내용이 없어" in second["answer_html"]
    assert calls == [1]


def test_followup_rejects_unknown_conversation_bad_ids_and_extra_fields(app_factory) -> None:
    service = _ConversationalFakeLLMService(_parsed_request(), reply=None)
    client = app_factory(llm_service=service).test_client()
    client.post("/api/key", json={"provider": "openai", "api_key": "test-key"})
    base = {"provider": "openai", "tier": "normal", "question": "왜?"}

    unknown = client.post("/api/followup", json={**base, "conversation_id": "f" * 32})
    bad_id = client.post("/api/followup", json={**base, "conversation_id": "../etc"})
    extra = client.post("/api/followup", json={**base, "conversation_id": "f" * 32, "spec": {}})

    assert (unknown.status_code, unknown.get_json()) == (404, {"error": "CONVERSATION-001"})
    assert (bad_id.status_code, bad_id.get_json()) == (400, {"error": "REQUEST-001"})
    assert (extra.status_code, extra.get_json()) == (400, {"error": "REQUEST-001"})
    assert service.followup_payloads == []


def test_followup_unsupported_dosage_form_keeps_previous_result(app_factory) -> None:
    parsed = _parsed_request(n_candidates=1)
    reply = _followup_reply(action="refine", request=_parsed_request(n_candidates=1, dosage_form="syrup"))
    service = _ConversationalFakeLLMService(parsed, reply=reply)
    client = app_factory(llm_service=service).test_client()
    client.post("/api/key", json={"provider": "openai", "api_key": "test-key"})
    first = client.post("/api/generate", json={"provider": "openai", "tier": "normal", "question": "q"}).get_json()

    failed = client.post("/api/followup", json={"provider": "openai", "tier": "normal",
                                                "conversation_id": first["conversation_id"],
                                                "question": "시럽으로"})

    assert (failed.status_code, failed.get_json()) == (400, {"error": "REQUEST-FORM-001"})
    service._reply = _followup_reply(action="answer", request=parsed, answer=[{"text": "그대로.", "basis": "general"}])
    again = client.post("/api/followup", json={"provider": "openai", "tier": "normal",
                                               "conversation_id": first["conversation_id"],
                                               "question": "지금 표는?"}).get_json()
    assert again["html"] == first["html"]                      # 실패한 수정은 대화를 바꾸지 않았다


def test_logout_clears_keys_and_conversations(app_factory) -> None:
    service = _ConversationalFakeLLMService(_parsed_request(n_candidates=1), reply=None)
    client = app_factory(llm_service=service).test_client()
    client.post("/api/key", json={"provider": "openai", "api_key": "test-key"})
    first = client.post("/api/generate", json={"provider": "openai", "tier": "normal", "question": "q"}).get_json()
    assert client.get("/health").get_json()["providers"]["openai"] is True

    logout = client.post("/api/logout")

    assert logout.status_code == 200 and logout.get_json() == {"ok": True}
    assert client.get("/health").get_json()["providers"]["openai"] is False
    body = {"provider": "openai", "tier": "normal", "conversation_id": first["conversation_id"], "question": "왜?"}
    assert client.post("/api/followup", json=body).get_json() == {"error": "LLM-KEY-001"}
    client.post("/api/key", json={"provider": "openai", "api_key": "test-key"})
    assert client.post("/api/followup", json=body).get_json() == {"error": "CONVERSATION-001"}


def test_save_list_open_resume_and_delete_round_trip(app_factory, monkeypatch, tmp_path: Path) -> None:
    """피드백 9번: 수동 저장 → 목록 → 열기 → 이어서 질문(LLM 호출 없이 결정적 재계산) → 삭제."""
    parsed = _parsed_request(n_candidates=1)
    service = _ConversationalFakeLLMService(parsed, explanation=_explanation(), reply=None)
    calls = _count_generations(monkeypatch)
    client = app_factory(llm_service=service).test_client()
    client.post("/api/key", json={"provider": "claude", "api_key": "test-key"})
    first = client.post("/api/generate", json={"provider": "claude", "tier": "normal",
                                               "question": "아세트아미노펜 500 mg 정제"}).get_json()

    saved = client.post("/api/results", json={"conversation_id": first["conversation_id"]})

    assert saved.status_code == 200
    result_id = saved.get_json()["result_id"]
    folder = tmp_path / "PhramaProto" / "results" / result_id
    assert (folder / "request.json").is_file() and (folder / "조성_후보_1.xlsx").is_file()
    assert "test-key" not in (folder / "request.json").read_text(encoding="utf-8")
    assert "검토용." in (folder / "result.html").read_text(encoding="utf-8")

    listing = client.get("/api/results").get_json()["results"]
    assert [item["id"] for item in listing] == [result_id]
    assert listing[0]["api_names"] == ["acetaminophen"] and listing[0]["n_candidates"] == 1

    opened = client.get(f"/api/results/{result_id}").get_json()
    assert opened["html"] == first["html"] and opened["resumable"] is True
    assert opened["question"] == "아세트아미노펜 500 mg 정제" and opened["turns"][0]["kind"] == "question"
    assert str(tmp_path) not in json.dumps(opened) and str(tmp_path) not in json.dumps(listing)
    assert str(tmp_path) not in saved.get_json()["location"]          # 응답에 실제 경로 없음

    resumed = client.post(f"/api/results/{result_id}/resume", json={"provider": "claude", "tier": "normal"})

    assert resumed.status_code == 200
    data = resumed.get_json()
    assert len(data["conversation_id"]) == 32 and data["conversation_id"] != first["conversation_id"]
    assert "조성 후보 1" in data["html"] and "검토용." in data["html"]      # 저장된 해설을 재사용
    assert service.explain_calls == 1 and calls == [1, 1]                 # LLM 없이 결정적 재계산

    assert client.delete(f"/api/results/{result_id}").get_json() == {"deleted": True}
    emptied = client.get("/api/results").get_json()
    assert emptied["results"] == [] and str(tmp_path) not in emptied["location"]
    assert client.get(f"/api/results/{result_id}").status_code == 404


def test_answer_followup_after_save_is_appended_to_the_saved_folder(app_factory, tmp_path: Path) -> None:
    parsed = _parsed_request(n_candidates=1)
    reply = _followup_reply(action="answer", request=parsed,
                            answer=[{"text": "희석제는 범위 안이다.", "basis": "evidence", "refs": ["KG n=10"]}])
    service = _ConversationalFakeLLMService(parsed, reply=reply)
    client = app_factory(llm_service=service).test_client()
    client.post("/api/key", json={"provider": "openai", "api_key": "test-key"})
    first = client.post("/api/generate", json={"provider": "openai", "tier": "normal", "question": "q"}).get_json()
    result_id = client.post("/api/results", json={"conversation_id": first["conversation_id"]}).get_json()["result_id"]

    client.post("/api/followup", json={"provider": "openai", "tier": "normal",
                                       "conversation_id": first["conversation_id"], "question": "왜 이 희석제?"})

    folder = tmp_path / "PhramaProto" / "results" / result_id
    turns = json.loads((folder / "followup.json").read_text(encoding="utf-8"))
    assert [t["kind"] for t in turns] == ["question", "question", "answer"]
    assert "희석제는 범위 안이다." in (folder / "result.html").read_text(encoding="utf-8")
    assert "희석제는 범위 안이다." in client.get(f"/api/results/{result_id}").get_json()["turns"][-1]["html"]


def test_resume_refuses_other_snapshot_and_unknown_ids(app_factory, tmp_path: Path) -> None:
    service = _ConversationalFakeLLMService(_parsed_request(n_candidates=1), reply=None)
    client = app_factory(llm_service=service).test_client()
    client.post("/api/key", json={"provider": "openai", "api_key": "test-key"})
    first = client.post("/api/generate", json={"provider": "openai", "tier": "normal", "question": "q"}).get_json()
    result_id = client.post("/api/results", json={"conversation_id": first["conversation_id"]}).get_json()["result_id"]
    request_file = tmp_path / "PhramaProto" / "results" / result_id / "request.json"
    request = json.loads(request_file.read_text(encoding="utf-8"))
    request["snapshot_id"] = "older-snapshot"
    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

    stale = client.post(f"/api/results/{result_id}/resume", json={"provider": "openai", "tier": "normal"})
    unknown = client.post("/api/results/20990101T000000Z-deadbeef/resume", json={"provider": "openai"})
    bad_id = client.get("/api/results/not-an-id")
    missing_conversation = client.post("/api/results", json={"conversation_id": "f" * 32})
    extra = client.post("/api/results", json={"conversation_id": first["conversation_id"], "path": "x"})

    assert (stale.status_code, stale.get_json()) == (409, {"error": "RESULTS-SNAPSHOT-001"})
    assert client.get(f"/api/results/{result_id}").get_json()["resumable"] is False     # 열람·다운로드는 가능
    assert (unknown.status_code, unknown.get_json()) == (404, {"error": "RESULTS-001"})
    assert (bad_id.status_code, bad_id.get_json()) == (404, {"error": "RESULTS-001"})
    assert (missing_conversation.status_code, missing_conversation.get_json()) == (404, {"error": "CONVERSATION-001"})
    assert (extra.status_code, extra.get_json()) == (400, {"error": "REQUEST-001"})


def test_generate_logs_safe_provider_diagnostics(app_factory, tmp_path: Path) -> None:
    failure = LLMFailure(
        "LLM-UPSTREAM-001",
        False,
        provider_code=400,
        provider_status="INVALID_ARGUMENT",
        provider_reason="API_KEY_INVALID",
    )
    client = app_factory(llm_service=_FailingLLMService(failure)).test_client()
    assert client.post(
        "/api/key",
        json={"provider": "gemini", "api_key": "test-key"},
    ).status_code == 200

    response = client.post(
        "/api/generate",
        json={
            "provider": "gemini",
            "tier": "cheap",
            "question": "아세트아미노펜 500 mg 정제",
        },
    )

    assert response.status_code == 502
    rows = (tmp_path / "PhramaProto" / "logs" / "app.log").read_text(encoding="utf-8")
    row = json.loads(rows.splitlines()[-1])
    assert row["provider_code"] == "400"
    assert row["provider_status"] == "INVALID_ARGUMENT"
    assert row["provider_reason"] == "API_KEY_INVALID"


@pytest.mark.parametrize(
    "ingredient_name",
    [
        '=HYPERLINK("https://invalid.example")',
        "+1+1",
        "-1+1",
        "@SUM(1,1)",
    ],
)
def test_xlsx_treats_formula_like_ingredient_names_as_text(
    ingredient_name: str,
) -> None:
    candidate = _candidate(1)
    candidate.components[0].name = ingredient_name

    workbook = load_workbook(
        BytesIO(candidate_workbook(candidate)),
        data_only=False,
    )
    ingredient_cell = workbook.active["A6"]

    assert ingredient_cell.data_type == "s"
    assert ingredient_cell.value == f"'{ingredient_name}"


def _explanation():
    from pharma_proto.llm.schema import FormulationExplanation

    return FormulationExplanation.model_validate({
        "api_profile": [{"text": "수용성 결정성 분말.", "basis": "general"}],
        "candidates": [{
            "candidate_idx": 1,
            "summary": "단순 직타 조성.",
            "ingredient_notes": [{"ingredient": "Microcrystalline cellulose",
                                  "rationale": "역할별 범위 안.", "basis": "evidence",
                                  "refs": ["KG 역할별 범위 n=2034"]}],
            "risks": [{"text": "흡습성 확인.", "basis": "general"}],
        }],
        "disclaimer": "검토용.",
    })


def test_generate_renders_explanation_with_basis_badges(app_factory, monkeypatch) -> None:
    spec = SimpleNamespace(apis=[SimpleNamespace(name="Acetaminophen")], dosage_form="tablet",
                           process="direct compression", profile_id="immediate_release_tablet")
    monkeypatch.setattr(app_module, "run_generation",
                        lambda spec, *, repository, offline: [_candidate(1), _candidate(2)])
    service = _FakeLLMService(spec, explanation=_explanation())
    client = app_factory(llm_service=service).test_client()
    assert client.post("/api/key", json={"provider": "claude", "api_key": "test-key"}).status_code == 200

    response = client.post("/api/generate", json={"provider": "claude", "tier": "normal",
                                                  "question": "아세트아미노펜 500 mg 정제"})

    assert response.status_code == 200
    html = response.get_json()["html"]
    assert html.count("<details class='explain' open>") == 1          # 해설이 있는 후보 1만
    assert "class='basis ev'" in html and "class='basis gen'" in html
    assert "data-help='basis:evidence'" in html and "data-help='basis:general'" in html
    assert "KG 역할별 범위 n=2034" in html and "API 프로파일" in html and "검토용." in html
    payload = service.explain_payloads[0]
    assert payload["request"]["apis"][0]["name"] == "Acetaminophen"
    assert [c["candidate_idx"] for c in payload["candidates"]] == [1, 2]
    assert payload["candidates"][0]["components"][0]["ingredient"] == "Acetaminophen"


def test_generate_keeps_table_when_explanation_fails(app_factory, monkeypatch, tmp_path: Path) -> None:
    spec = SimpleNamespace(apis=[SimpleNamespace(name="Acetaminophen")], dosage_form="tablet",
                           process="", profile_id="immediate_release_tablet")
    monkeypatch.setattr(app_module, "run_generation",
                        lambda spec, *, repository, offline: [_candidate(1)])
    failure = LLMFailure("LLM-RATE-001", True, provider_code=429)
    client = app_factory(llm_service=_FakeLLMService(spec, explain_failure=failure)).test_client()
    assert client.post("/api/key", json={"provider": "openai", "api_key": "test-key"}).status_code == 200

    response = client.post("/api/generate", json={"provider": "openai", "tier": "normal",
                                                  "question": "아세트아미노펜 500 mg 정제"})

    assert response.status_code == 200
    html = response.get_json()["html"]
    assert "해설 생성 실패 (LLM-RATE-001)" in html and 'class="download-xlsx ' in html
    rows = (tmp_path / "PhramaProto" / "logs" / "app.log").read_text(encoding="utf-8")
    assert '"LLM-RATE-001"' in rows.splitlines()[-1] or "LLM-RATE-001" in rows

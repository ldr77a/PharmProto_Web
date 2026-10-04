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
    probe = _ElementProbe()
    probe.feed(response.get_data(as_text=True))

    assert "hidden" not in probe.attrs("api-setup")
    assert "hidden" in probe.attrs("research-app")
    assert "hidden" in probe.attrs("review-notice")
    assert probe.text("api-cost-notice") == "외부 AI API 호출은 과금 대상입니다."
    assert "연구 검토용 시제품입니다." not in probe.text("api-setup")
    assert "API 설정 변경" in probe.text("research-app")

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
    assert "요청 해석" in html
    assert "Acetaminophen 500 mg (사용자 지정)" in html
    assert "700 mg (사용자 지정)" in html
    assert "Croscarmellose sodium 4%" in html                       # 지정 분량 에코
    assert "4.00</td><td class='ev '>사용자 지정</td>" in html       # 표의 % 와 근거 라벨
    assert "총중량 700mg" in html
    assert "미반영 분량" not in html


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

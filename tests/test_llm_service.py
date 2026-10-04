from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

from pharma_proto.llm.resilience import RetryPolicy
from pharma_proto.llm.service import LLMService


class _RecordingGeminiModels:
    def __init__(self) -> None:
        self.config = None
        self.submitted_schema = None

    def generate_content(self, *, model, contents, config):
        from google.genai import _transformers

        self.config = config
        self.submitted_schema = deepcopy(config.response_schema)
        _transformers.t_schema(None, config.response_schema)
        return SimpleNamespace(
            text=json.dumps(
                {
                    "apis": [{"name": "Acetaminophen", "dose_mg": 500}],
                    "dosage_form": "tablet",
                    "process": "direct compression",
                    "n_candidates": 3,
                }
            )
        )


class _RecordingGeminiClient:
    def __init__(self) -> None:
        self.models = _RecordingGeminiModels()

    def close(self) -> None:
        pass


class _RecordingClaudeMessages:
    """현재 Claude 모델은 강제 tool_choice 를 거부하므로 구조화 출력(messages.parse)만 흉내 낸다."""

    def __init__(self) -> None:
        self.output_format = None
        self.kwargs = None

    def parse(self, *, output_format, **kwargs):
        self.output_format = output_format
        self.kwargs = kwargs
        if output_format.__name__ == "ParsedRequest":
            payload = {
                "apis": [{"name": "Acetaminophen", "dose_mg": 500}],
                "dosage_form": "tablet",
                "disintegrant": ["Croscarmellose sodium"],
                "amounts": [{"ingredient": "Croscarmellose sodium", "pct": 5}],
                "release_profile": "immediate release",
                "n_candidates": 3,
            }
        elif output_format.__name__ == "FollowUpResponse":
            payload = _FOLLOWUP_PAYLOAD
        else:
            payload = _EXPLANATION_PAYLOAD
        return SimpleNamespace(parsed_output=output_format.model_validate(payload), stop_reason="end_turn")


_FOLLOWUP_PAYLOAD = {
    "action": "REFINE",
    "request": {
        "apis": [{"name": "Acetaminophen", "dose_mg": 500}],
        "dosage_form": "tablet",
        "n_candidates": 1,
        "target_total_mg": 650,
    },
    "answer": [],
    "note": "후보 1개, 총중량 650 mg 으로 바꿨다.",
}

_EXPLANATION_PAYLOAD = {
    "api_profile": [{"text": "2차 아민을 가진 수용성 염.", "basis": "general", "refs": []}],
    "candidates": [
        {
            "candidate_idx": 1,
            "summary": "희석제 중심의 단순 조성.",
            "ingredient_notes": [
                {"ingredient": "Microcrystalline cellulose", "rationale": "KG 역할별 범위 안.",
                 "basis": "evidence", "refs": ["KG 역할별 범위 n=2034"], "caution": ""}
            ],
            "risks": [{"text": "lactose 와 Maillard 가능성.", "basis": "general", "refs": []}],
            "process_notes": [],
            "verification_checklist": [{"text": "함량균일성.", "basis": "general"}],
            "alternatives": [],
        }
    ],
    "disclaimer": "검토용 해설.",
}


class _RecordingClaudeClient:
    def __init__(self) -> None:
        self.messages = _RecordingClaudeMessages()

    def close(self) -> None:
        pass


def test_gemini_uses_a_schema_accepted_by_the_installed_sdk() -> None:
    client = _RecordingGeminiClient()
    service = LLMService(
        client_factories={"gemini": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    formulation = service.parse(
        "gemini",
        "cheap",
        "test-key",
        "아세트아미노펜 500 mg 속방정제",
    )

    assert formulation.apis[0].name == "Acetaminophen"
    assert formulation.apis[0].dose_mg == 500
    assert formulation.process == "direct compression"
    assert formulation.n_candidates == 3
    assert client.models.config.response_json_schema is None


def test_gemini_schema_only_uses_portable_structured_output_fields() -> None:
    client = _RecordingGeminiClient()
    service = LLMService(
        client_factories={"gemini": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    service.parse("gemini", "normal", "test-key", "아세트아미노펜 500 mg 정제")

    allowed = {"type", "properties", "required", "items"}
    pending = [client.models.submitted_schema]
    while pending:
        node = pending.pop()
        assert isinstance(node, dict)
        assert set(node) <= allowed
        properties = node.get("properties", {})
        assert isinstance(properties, dict)
        pending.extend(properties.values())
        if "items" in node:
            pending.append(node["items"])


def test_claude_parses_with_structured_output_not_forced_tools() -> None:
    client = _RecordingClaudeClient()
    service = LLMService(
        client_factories={"claude": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    formulation = service.parse(
        "claude",
        "cheap",
        "test-key",
        "아세트아미노펜 500 mg 속방정을 크로스카멜로오스나트륨으로 제조",
    )

    assert formulation.apis[0].name == "Acetaminophen"
    assert formulation.apis[0].dose_mg == 500
    assert formulation.excipient_choices["disintegrant"] == ["croscarmellose sodium"]
    assert formulation.user_amounts["croscarmellose sodium"].pct == 5
    assert formulation.release_profile == "immediate release"
    assert client.messages.output_format.__name__ == "ParsedRequest"
    assert "tool_choice" not in client.messages.kwargs and "tools" not in client.messages.kwargs


def test_parse_request_returns_schema_object_for_follow_up_edits() -> None:
    from pharma_proto.llm.schema import ParsedRequest

    client = _RecordingClaudeClient()
    service = LLMService(
        client_factories={"claude": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    parsed = service.parse_request("claude", "normal", "test-key", "아세트아미노펜 500 mg 정제")

    assert isinstance(parsed, ParsedRequest)
    assert parsed.amounts[0].ingredient == "Croscarmellose sodium"
    assert parsed.to_domain().apis[0].dose_mg == 500


def test_gemini_schema_declares_amounts() -> None:
    client = _RecordingGeminiClient()
    service = LLMService(
        client_factories={"gemini": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    service.parse("gemini", "normal", "test-key", "아세트아미노펜 500 mg 정제, MCC 40%")

    amounts = client.models.submitted_schema["properties"]["amounts"]
    assert amounts["type"] == "ARRAY"
    assert set(amounts["items"]["properties"]) == {"ingredient", "mg", "pct"}
    assert amounts["items"]["required"] == ["ingredient"]


def _payload() -> dict:
    return {"request": {"apis": [{"name": "acetaminophen", "dose_mg": 500}]},
            "candidates": [{"candidate_idx": 1, "components": []}]}


def test_claude_explain_returns_normalized_explanation() -> None:
    client = _RecordingClaudeClient()
    service = LLMService(
        client_factories={"claude": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    explanation = service.explain("claude", "normal", "test-key", _payload())

    assert client.messages.output_format.__name__ == "FormulationExplanation"
    assert client.messages.kwargs["max_tokens"] >= 8000
    candidate = explanation.for_candidate(1)
    assert candidate is not None and candidate.ingredient_notes[0].basis == "evidence"
    assert candidate.risks[0].basis == "general"
    assert candidate.verification_checklist[0].refs == []
    assert explanation.for_candidate(9) is None


class _RecordingGeminiExplainModels(_RecordingGeminiModels):
    def generate_content(self, *, model, contents, config):
        from google.genai import _transformers

        self.config = config
        self.submitted_schema = deepcopy(config.response_schema)
        _transformers.t_schema(None, config.response_schema)
        return SimpleNamespace(text=json.dumps(_EXPLANATION_PAYLOAD, ensure_ascii=False))


def test_gemini_explain_schema_only_uses_portable_fields() -> None:
    client = _RecordingGeminiClient()
    client.models = _RecordingGeminiExplainModels()
    service = LLMService(
        client_factories={"gemini": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    explanation = service.explain("gemini", "normal", "test-key", _payload())

    assert explanation.candidates[0].summary == "희석제 중심의 단순 조성."
    allowed = {"type", "properties", "required", "items"}
    pending = [client.models.submitted_schema]
    while pending:
        node = pending.pop()
        assert isinstance(node, dict) and set(node) <= allowed
        pending.extend(node.get("properties", {}).values())
        if "items" in node:
            pending.append(node["items"])


class _RecordingOpenAIResponses:
    def __init__(self) -> None:
        self.text_format = None

    def parse(self, *, model, input, text_format):
        self.text_format = text_format
        return SimpleNamespace(output_parsed=text_format.model_validate(_EXPLANATION_PAYLOAD))


def test_openai_explain_uses_responses_parse() -> None:
    client = SimpleNamespace(responses=_RecordingOpenAIResponses(), close=lambda: None)
    service = LLMService(
        client_factories={"openai": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    explanation = service.explain("openai", "normal", "test-key", _payload())

    assert client.responses.text_format.__name__ == "FormulationExplanation"
    assert explanation.disclaimer == "검토용 해설."


def test_explain_rejects_empty_payload() -> None:
    service = LLMService(policy=RetryPolicy(max_attempts=1))
    import pytest

    with pytest.raises(ValueError):
        service.explain("claude", "normal", "test-key", {"candidates": []})


def _followup_payload() -> dict:
    return {
        "previous_request": {"apis": [{"name": "Acetaminophen", "dose_mg": 500}], "n_candidates": 3},
        "question": "후보 1개, 총중량 650 mg 으로",
        "turns": [],
        "result": _payload(),
    }


def test_claude_followup_normalizes_action_and_returns_full_request() -> None:
    client = _RecordingClaudeClient()
    service = LLMService(
        client_factories={"claude": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    reply = service.followup("claude", "normal", "test-key", _followup_payload())

    assert client.messages.output_format.__name__ == "FollowUpResponse"
    assert "tool_choice" not in client.messages.kwargs
    assert reply.action == "refine"
    assert reply.request.n_candidates == 1 and reply.request.target_total_mg == 650
    assert reply.note.startswith("후보 1개")


class _RecordingGeminiFollowupModels(_RecordingGeminiModels):
    def generate_content(self, *, model, contents, config):
        from google.genai import _transformers

        self.config = config
        self.submitted_schema = deepcopy(config.response_schema)
        _transformers.t_schema(None, config.response_schema)
        return SimpleNamespace(text=json.dumps(_FOLLOWUP_PAYLOAD, ensure_ascii=False))


def test_gemini_followup_schema_only_uses_portable_fields() -> None:
    client = _RecordingGeminiClient()
    client.models = _RecordingGeminiFollowupModels()
    service = LLMService(
        client_factories={"gemini": lambda *args, **kwargs: client},
        policy=RetryPolicy(max_attempts=1),
    )

    reply = service.followup("gemini", "normal", "test-key", _followup_payload())

    assert reply.action == "refine" and reply.request.n_candidates == 1
    schema = client.models.submitted_schema
    assert set(schema["properties"]) == {"action", "request", "answer", "note"}
    assert "amounts" in schema["properties"]["request"]["properties"]
    allowed = {"type", "properties", "required", "items"}
    pending = [schema]
    while pending:
        node = pending.pop()
        assert isinstance(node, dict) and set(node) <= allowed
        pending.extend(node.get("properties", {}).values())
        if "items" in node:
            pending.append(node["items"])


def test_followup_rejects_payload_without_question_or_previous_request() -> None:
    import pytest

    service = LLMService(policy=RetryPolicy(max_attempts=1))

    with pytest.raises(ValueError):
        service.followup("claude", "normal", "test-key", {"previous_request": {"apis": []}})
    with pytest.raises(ValueError):
        service.followup("claude", "normal", "test-key", {"question": "왜?"})

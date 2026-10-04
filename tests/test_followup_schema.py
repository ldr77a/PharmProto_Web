"""후속 질문 응답 스키마 — 의도 정규화, answer 문장 필수, 요청 간 변경 목록."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pharma_proto.llm.schema import FollowUpResponse, ParsedRequest, request_changes

_BASE = {
    "apis": [{"name": "acetaminophen", "dose_mg": 500}],
    "disintegrant": ["croscarmellose sodium"],
    "amounts": [{"ingredient": "croscarmellose sodium", "pct": 4}],
    "n_candidates": 3,
}


def test_action_is_normalized_and_answer_needs_sentences() -> None:
    refine = FollowUpResponse.model_validate({"action": "REFINE", "request": _BASE})
    assert refine.action == "refine" and refine.answer == []

    answer = FollowUpResponse.model_validate({
        "action": "Answer", "request": _BASE,
        "answer": [{"text": "범위 안.", "basis": "evidence", "refs": ["KG n=10"]}],
    })
    assert answer.action == "answer" and answer.answer[0].basis == "evidence"

    with pytest.raises(ValidationError):
        FollowUpResponse.model_validate({"action": "answer", "request": _BASE, "answer": []})


def test_request_changes_lists_field_level_differences_in_korean() -> None:
    old = ParsedRequest.model_validate(_BASE)
    new = ParsedRequest.model_validate({
        **_BASE,
        "n_candidates": 1,
        "target_total_mg": 650,
        "disintegrant": ["Croscarmellose sodium"],                    # 대소문자만 다름 → 변경 아님
        "lubricant": ["magnesium stearate"],
        "amounts": [{"ingredient": "croscarmellose sodium", "pct": 5},
                    {"ingredient": "magnesium stearate", "mg": 8}],
    })

    changes = request_changes(old, new)

    assert "후보 수: 3 → 1" in changes
    assert "총중량: 자동 → 650 mg" in changes
    assert "활택제: 없음 → magnesium stearate" in changes
    assert "분량 변경: croscarmellose sodium 4% → croscarmellose sodium 5%" in changes
    assert "분량 추가: magnesium stearate 8 mg" in changes
    assert not any(line.startswith("붕해제") for line in changes)


def test_request_changes_is_empty_for_equivalent_requests() -> None:
    old = ParsedRequest.model_validate(_BASE)
    same = ParsedRequest.model_validate({**_BASE, "process": "  "})

    assert request_changes(old, same) == []

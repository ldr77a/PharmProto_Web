"""Provider adapters: 질문 → 구조화 스펙(parse), 후보 조성 → 해설(explain), 후속 질문 → 수정/답변(followup).

셋 다 고정 스키마 구조화 출력이며 공급자 분기는 _structured_call 하나에 있다.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

from pharma_proto.llm.catalog import model_for
from pharma_proto.llm.resilience import RetryPolicy, run_with_retry
from pharma_proto.llm.schema import (
    FollowUpResponse,
    FormulationExplanation,
    ParsedRequest,
)

SYSTEM_INSTRUCTION = (
    "Extract the pharmaceutical formulation request into the supplied schema. "
    "Translate ingredient names to English generic names. Do not add fields outside the schema "
    "and do not invent excipients the user did not provide. "
    "When the user states an amount for an excipient, record it in `amounts` as "
    "{ingredient, mg or pct} using exactly the English name you put in its role list, and also "
    "list that ingredient under its role (binder, disintegrant, diluent, lubricant or "
    "additional_roles). Put API doses in apis[].dose_mg and a stated total tablet or capsule "
    "weight in target_total_mg. Never invent amounts; leave a field empty when the user did not "
    "state it."
)

EXPLAIN_INSTRUCTION = (
    "당신은 경구 고형제 제제 연구자를 돕는 해설자다. 입력은 지식 데이터베이스가 만든 조성 후보와 그 근거다.\n"
    "규칙:\n"
    "1. 표의 숫자(mg, %)를 바꾸거나 새 숫자를 제안하지 않는다. 숫자를 말할 때는 표의 값을 그대로 인용한다.\n"
    "2. 입력에 있는 근거(KG 범위와 n, HPE6 모노그래프·용도범위·부적합성·안정성·물성, 실사용 배합 수, 게이트 결과)를 "
    "인용할 수 있는 문장은 basis='evidence' 로 두고 refs 에 그 꼬리표(예: 'KG 역할별 범위 n=1102', 'HPE6 p.347')를 적는다. "
    "입력에 없는 일반 제제학 지식은 반드시 basis='general' 로 둔다.\n"
    "3. 최종 제조 가능 판정을 내리지 않는다. 의사결정 지원이며, 사람이 검토한다고 전제한다.\n"
    "4. 한국어로 쓰되 성분명은 입력의 영문 표기를 그대로 쓴다. 문장은 짧고 구체적으로.\n"
    "5. 후보마다: summary(한 문단), ingredient_notes(성분별 선택 이유와 주의, API 포함), risks(호환성·안정성·공정 위험), "
    "process_notes(요청 공정 기준의 메모), verification_checklist(실험으로 확인할 항목), alternatives(대안과 이유).\n"
    "6. api_profile 에는 API 의 물성·작용기·제제 설계 시 주의점을 적되 전부 basis='general' 로 표시한다.\n"
    "7. disclaimer 에 이 해설의 한계를 한 문장으로 적는다."
)

FOLLOWUP_INSTRUCTION = (
    "당신은 경구 고형제 조성 연구 도구의 후속 질문 담당자다. 입력 JSON 에는 previous_request(이전 구조화 요청), "
    "result(지식 데이터베이스가 만든 현재 조성 후보와 근거·게이트 결과), turns(앞선 대화), question(새 메시지)이 있다.\n"
    "규칙:\n"
    "1. 의도를 판정한다. 성분·분량·총중량·제형·공정·방출·후보 수를 바꾸라는 요구면 action='refine', "
    "현재 결과에 대한 질문·설명 요구면 action='answer'.\n"
    "2. refine: request 에 previous_request 의 모든 필드를 그대로 복사한 뒤 질문이 바꾸라고 한 부분만 고친다. "
    "언급되지 않은 성분·분량·총중량은 유지한다. 사용자가 말하지 않은 성분을 새로 넣지 않는다. 분량은 amounts 에 "
    "{ingredient, mg 또는 pct} 로 적고 그 성분은 역할 리스트에도 둔다. answer 는 비운다. note 에 바꾼 내용을 한 문장으로.\n"
    "3. answer: request 는 previous_request 를 그대로 복사한다. 표의 숫자를 바꾸거나 새 숫자를 제안하지 않고, "
    "숫자를 말할 때는 result 의 값을 그대로 인용한다. 문장마다 basis 를 둔다 — result 의 근거(KG 범위와 n, HPE6, "
    "게이트 결과, 실사용 배합 수)를 인용하면 'evidence' 와 refs, 입력에 없는 일반 제제학 지식이면 'general'.\n"
    "4. 최종 제조 가능 판정을 내리지 않는다. 의사결정 지원이며 사람이 검토한다.\n"
    "5. 한국어로 쓰되 성분명은 영문 표기를 그대로 쓴다. 문장은 짧고 구체적으로."
)

ClientFactory = Callable[..., Any]


def _openai_factory(api_key: str, *, timeout: float, max_retries: int):
    from openai import OpenAI

    return OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)


def _claude_factory(api_key: str, *, timeout: float, max_retries: int):
    from anthropic import Anthropic

    return Anthropic(api_key=api_key, timeout=timeout, max_retries=max_retries)


def _gemini_factory(api_key: str, *, timeout: float, max_retries: int):
    from google import genai
    from google.genai import types

    attempts = 1 if max_retries == 0 else max_retries + 1
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=int(timeout * 1000),
            retry_options=types.HttpRetryOptions(attempts=attempts),
        ),
    )


_DEFAULT_FACTORIES: dict[str, ClientFactory] = {
    "openai": _openai_factory,
    "gemini": _gemini_factory,
    "claude": _claude_factory,
}


def _coerce(model_type, value: object):
    if isinstance(value, model_type):
        return value
    return model_type.model_validate(value)


def _gemini_response_schema() -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "apis": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING"},
                        "dose_mg": {"type": "NUMBER"},
                    },
                    "required": ["name"],
                },
            },
            "dosage_form": {"type": "STRING"},
            "binder": {"type": "ARRAY", "items": {"type": "STRING"}},
            "disintegrant": {"type": "ARRAY", "items": {"type": "STRING"}},
            "diluent": {"type": "ARRAY", "items": {"type": "STRING"}},
            "lubricant": {"type": "ARRAY", "items": {"type": "STRING"}},
            "additional_roles": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "role": {"type": "STRING"},
                        "ingredients": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                        },
                    },
                    "required": ["role"],
                },
            },
            "amounts": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "ingredient": {"type": "STRING"},
                        "mg": {"type": "NUMBER"},
                        "pct": {"type": "NUMBER"},
                    },
                    "required": ["ingredient"],
                },
            },
            "process": {"type": "STRING"},
            "release_profile": {"type": "STRING"},
            "n_candidates": {"type": "INTEGER"},
            "target_total_mg": {"type": "NUMBER"},
        },
        "required": ["apis"],
    }


def _gemini_item_schema() -> dict[str, Any]:
    """해설·후속 답변의 문장 하나(text/basis/refs). 호출마다 새 dict — SDK 가 제자리에서 바꿀 수 있다."""
    return {
        "type": "OBJECT",
        "properties": {
            "text": {"type": "STRING"},
            "basis": {"type": "STRING"},
            "refs": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["text", "basis"],
    }


def _gemini_explanation_schema() -> dict[str, Any]:
    item = _gemini_item_schema()
    note = {
        "type": "OBJECT",
        "properties": {
            "ingredient": {"type": "STRING"},
            "rationale": {"type": "STRING"},
            "basis": {"type": "STRING"},
            "refs": {"type": "ARRAY", "items": {"type": "STRING"}},
            "caution": {"type": "STRING"},
        },
        "required": ["ingredient", "rationale", "basis"],
    }
    candidate = {
        "type": "OBJECT",
        "properties": {
            "candidate_idx": {"type": "INTEGER"},
            "summary": {"type": "STRING"},
            "ingredient_notes": {"type": "ARRAY", "items": note},
            "risks": {"type": "ARRAY", "items": item},
            "process_notes": {"type": "ARRAY", "items": item},
            "verification_checklist": {"type": "ARRAY", "items": item},
            "alternatives": {"type": "ARRAY", "items": item},
        },
        "required": ["candidate_idx", "summary"],
    }
    return {
        "type": "OBJECT",
        "properties": {
            "api_profile": {"type": "ARRAY", "items": item},
            "candidates": {"type": "ARRAY", "items": candidate},
            "disclaimer": {"type": "STRING"},
        },
        "required": ["candidates"],
    }


def _gemini_followup_schema() -> dict[str, Any]:
    """union/nullable 없이: request 는 항상 채우고(answer 면 이전 요청 복사), action 은 문자열."""
    return {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING"},
            "request": _gemini_response_schema(),
            "answer": {"type": "ARRAY", "items": _gemini_item_schema()},
            "note": {"type": "STRING"},
        },
        "required": ["action", "request"],
    }


class LLMService:
    def __init__(
        self,
        *,
        client_factories: Mapping[str, ClientFactory] | None = None,
        policy: RetryPolicy | None = None,
        explain_policy: RetryPolicy | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._factories = dict(_DEFAULT_FACTORIES)
        if client_factories is not None:
            self._factories.update(client_factories)
        self._policy = policy or RetryPolicy()
        # 해설은 입력이 길고 출력이 수천 토큰이라 파싱보다 긴 시간을 준다. 재시도는 한 번만.
        self._explain_policy = explain_policy or RetryPolicy(
            timeout_seconds=max(120.0, self._policy.timeout_seconds), max_attempts=2
        )
        self._sleeper = sleeper

    def _structured_call(
        self,
        provider: str,
        model: str,
        api_key: str,
        *,
        system: str,
        user_text: str,
        output_model,
        gemini_schema: dict[str, Any],
        max_tokens: int,
        timeout: float,
    ):
        """세 공급자의 구조화 출력 호출 하나. 응답은 output_model 인스턴스.

        Claude 는 현재 모델이 강제 tool_choice 를 거부하므로 messages.parse(output_format) 를 쓴다.
        Gemini 는 pydantic 스키마 대신 손으로 쓴 포터블 dict(type/properties/required/items) 를 받는다.
        """
        client = self._factories[provider](api_key, timeout=timeout, max_retries=0)
        try:
            if provider == "openai":
                response = client.responses.parse(
                    model=model,
                    input=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_text},
                    ],
                    text_format=output_model,
                )
                return _coerce(output_model, response.output_parsed)
            if provider == "claude":
                response = client.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user_text}],
                    output_format=output_model,
                )
                if getattr(response, "stop_reason", None) == "refusal":
                    raise ValueError("Claude declined the request")
                return _coerce(output_model, response.parsed_output)
            if provider == "gemini":
                from google.genai import types

                response = client.models.generate_content(
                    model=model,
                    contents=user_text,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_schema=gemini_schema,
                    ),
                )
                return output_model.model_validate_json(response.text)
            raise ValueError("unsupported provider")
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _parse_once(
        self,
        provider: str,
        model: str,
        api_key: str,
        question: str,
    ) -> ParsedRequest:
        return self._structured_call(
            provider, model, api_key,
            system=SYSTEM_INSTRUCTION, user_text=question, output_model=ParsedRequest,
            gemini_schema=_gemini_response_schema(), max_tokens=4096,
            timeout=self._policy.timeout_seconds,
        )

    def _explain_once(
        self,
        provider: str,
        model: str,
        api_key: str,
        payload: Mapping[str, Any],
    ) -> FormulationExplanation:
        user_text = (
            "다음은 데이터베이스가 만든 조성 후보와 근거다. 규칙에 따라 해설을 작성하라.\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        return self._structured_call(
            provider, model, api_key,
            system=EXPLAIN_INSTRUCTION, user_text=user_text, output_model=FormulationExplanation,
            gemini_schema=_gemini_explanation_schema(), max_tokens=16000,
            timeout=self._explain_policy.timeout_seconds,
        )

    def _followup_once(
        self,
        provider: str,
        model: str,
        api_key: str,
        payload: Mapping[str, Any],
    ) -> FollowUpResponse:
        user_text = (
            "다음은 이전 요청, 데이터베이스가 만든 현재 결과, 대화 기록, 새 메시지다. "
            "규칙에 따라 의도를 판정하고 응답하라.\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        return self._structured_call(
            provider, model, api_key,
            system=FOLLOWUP_INSTRUCTION, user_text=user_text, output_model=FollowUpResponse,
            gemini_schema=_gemini_followup_schema(), max_tokens=8000,
            timeout=self._explain_policy.timeout_seconds,
        )

    def followup(
        self,
        provider: str,
        tier: str,
        api_key: str,
        payload: Mapping[str, Any],
    ) -> FollowUpResponse:
        """후속 메시지 → 수정된 요청(refine) 또는 근거 표시된 답변(answer). 숫자는 만들지 않는다."""
        model = model_for(provider, tier)
        key = api_key.strip()
        if not key or not payload or not payload.get("question") or not payload.get("previous_request"):
            raise ValueError("invalid LLM request")
        return run_with_retry(
            lambda: self._followup_once(provider, model, key, payload),
            policy=self._explain_policy,
            sleeper=self._sleeper,
        )

    def explain(
        self,
        provider: str,
        tier: str,
        api_key: str,
        payload: Mapping[str, Any],
    ) -> FormulationExplanation:
        """후보 조성(payload)에 대한 해설. 숫자는 바꾸지 않고 근거/일반지식을 구분해 돌려준다."""
        model = model_for(provider, tier)
        key = api_key.strip()
        if not key or not payload or not payload.get("candidates"):
            raise ValueError("invalid LLM request")
        return run_with_retry(
            lambda: self._explain_once(provider, model, key, payload),
            policy=self._explain_policy,
            sleeper=self._sleeper,
        )

    def parse_request(
        self,
        provider: str,
        tier: str,
        api_key: str,
        question: str,
    ) -> ParsedRequest:
        """질문 → 구조화 요청(ParsedRequest). 후속 질문이 이전 요청을 고쳐 쓸 수 있게 스키마 객체를 돌려준다."""
        model = model_for(provider, tier)
        key = api_key.strip()
        text = question.strip()
        if not key or not text or len(text) > 4000:
            raise ValueError("invalid LLM request")
        return run_with_retry(
            lambda: self._parse_once(provider, model, key, text),
            policy=self._policy,
            sleeper=self._sleeper,
        )

    def parse(
        self,
        provider: str,
        tier: str,
        api_key: str,
        question: str,
    ):
        return self.parse_request(provider, tier, api_key, question).to_domain()


__all__ = ["EXPLAIN_INSTRUCTION", "FOLLOWUP_INSTRUCTION", "SYSTEM_INSTRUCTION", "LLMService"]

"""One provider-neutral structured schema for formulation requests."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from generation.input_parser import FormulationSpec, build_spec
from generation.oral_solid_profiles import canonical_role

IngredientName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ParsedAPI(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: IngredientName
    dose_mg: float | None = Field(default=None, gt=0, le=1_000_000)


class ParsedRoleChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: IngredientName
    ingredients: list[IngredientName] = Field(default_factory=list, max_length=20)


class ParsedAmount(BaseModel):
    """사용자가 적은 성분별 분량. mg 또는 % 중 하나는 있어야 한다.

    Gemini 구조화 출력은 nullable 을 못 쓰므로 '없음'이 0 으로 올 수 있다 → 0 은 없음으로 본다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ingredient: IngredientName
    mg: float | None = Field(default=None, gt=0, le=1_000_000)
    pct: float | None = Field(default=None, gt=0, lt=100)

    @model_validator(mode="before")
    @classmethod
    def _absent_if_zero(cls, data: object) -> object:
        if isinstance(data, dict):
            cleaned = dict(data)
            for key in ("mg", "pct"):
                if key in cleaned and cleaned[key] in (0, 0.0, "", None):
                    cleaned.pop(key)
            return cleaned
        return data

    @model_validator(mode="after")
    def _one_required(self) -> ParsedAmount:
        if self.mg is None and self.pct is None:
            raise ValueError("amount needs mg or pct")
        return self


class ParsedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    apis: list[ParsedAPI] = Field(min_length=1, max_length=10)
    dosage_form: IngredientName = "tablet"
    binder: list[IngredientName] = Field(default_factory=list, max_length=20)
    disintegrant: list[IngredientName] = Field(default_factory=list, max_length=20)
    diluent: list[IngredientName] = Field(default_factory=list, max_length=20)
    lubricant: list[IngredientName] = Field(default_factory=list, max_length=20)
    additional_roles: list[ParsedRoleChoice] = Field(default_factory=list, max_length=40)
    amounts: list[ParsedAmount] = Field(default_factory=list, max_length=40)
    process: str = Field(default="", max_length=500)
    release_profile: str = Field(default="", max_length=200)
    n_candidates: int = Field(default=3, ge=1, le=5)
    target_total_mg: float | None = Field(default=None, gt=0, le=10_000_000)

    def to_domain(self) -> FormulationSpec:
        excipients: dict[str, list[str]] = {
            "binder": list(self.binder),
            "disintegrant": list(self.disintegrant),
            "diluent": list(self.diluent),
            "lubricant": list(self.lubricant),
        }
        for item in self.additional_roles:
            role = canonical_role(item.role)
            if role and item.ingredients:
                excipients.setdefault(role, []).extend(item.ingredients)
        return build_spec(
            [(item.name, item.dose_mg) for item in self.apis],
            {role: values for role, values in excipients.items() if values},
            dosage_form=self.dosage_form,
            process=self.process,
            release_profile=self.release_profile,
            n_candidates=self.n_candidates,
            target_total_mg=self.target_total_mg,
            amounts={item.ingredient: (item.mg, item.pct) for item in self.amounts},
        )


# --- 해설층(2차 호출) ---------------------------------------------------------------
# 숫자는 DB 가 만들고 LLM 은 해석만 한다. 문장마다 basis 로 "제공된 근거 인용(evidence)" 과
# "모델 일반 지식(general, 검증 필요)" 을 구분해 화면에 표시한다.
_BASIS_VALUES = ("evidence", "general")


def _normalize_basis(value: str) -> str:
    text = (value or "").strip().lower()
    return "evidence" if text.startswith("ev") or text in ("근거", "evidence") else "general"


class ExplanationItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]
    basis: str = "general"
    refs: list[Annotated[str, StringConstraints(max_length=200)]] = Field(default_factory=list, max_length=12)

    def model_post_init(self, context: object, /) -> None:
        object.__setattr__(self, "basis", _normalize_basis(self.basis))


class IngredientNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ingredient: IngredientName
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]
    basis: str = "general"
    refs: list[Annotated[str, StringConstraints(max_length=200)]] = Field(default_factory=list, max_length=12)
    caution: Annotated[str, StringConstraints(max_length=800)] = ""

    def model_post_init(self, context: object, /) -> None:
        object.__setattr__(self, "basis", _normalize_basis(self.basis))


class CandidateExplanation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidate_idx: int = Field(ge=1, le=20)
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    ingredient_notes: list[IngredientNote] = Field(default_factory=list, max_length=40)
    risks: list[ExplanationItem] = Field(default_factory=list, max_length=20)
    process_notes: list[ExplanationItem] = Field(default_factory=list, max_length=20)
    verification_checklist: list[ExplanationItem] = Field(default_factory=list, max_length=20)
    alternatives: list[ExplanationItem] = Field(default_factory=list, max_length=20)


class FormulationExplanation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_profile: list[ExplanationItem] = Field(default_factory=list, max_length=20)
    candidates: list[CandidateExplanation] = Field(default_factory=list, max_length=20)
    disclaimer: Annotated[str, StringConstraints(max_length=600)] = ""

    def for_candidate(self, idx: int) -> CandidateExplanation | None:
        return next((item for item in self.candidates if item.candidate_idx == idx), None)


# --- 후속 질문(3차 호출) ---------------------------------------------------------------
# LLM 은 의도만 분류한다: 요청을 고쳐 다시 만들기(refine) 또는 현재 결과에 대해 답하기(answer).
# request 는 두 경우 모두 채운다(answer 면 이전 요청을 그대로 복사). Gemini 구조화 출력이
# union/nullable 을 못 쓰고, 무엇이 바뀌었는지는 서버가 결정적으로 계산할 수 있기 때문이다.


def _normalize_action(value: str) -> str:
    text = (value or "").strip().lower()
    return "refine" if text.startswith("ref") or text in ("수정", "재생성", "regenerate") else "answer"


class FollowUpResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str = "answer"
    request: ParsedRequest
    answer: list[ExplanationItem] = Field(default_factory=list, max_length=20)
    note: Annotated[str, StringConstraints(max_length=400)] = ""

    @model_validator(mode="after")
    def _normalize(self) -> FollowUpResponse:
        self.action = _normalize_action(self.action)
        if self.action == "answer" and not self.answer:
            raise ValueError("answer needs at least one sentence")
        return self


_REQUEST_FIELDS_KO = (
    ("dosage_form", "제형"), ("process", "공정"), ("release_profile", "방출"),
    ("n_candidates", "후보 수"), ("target_total_mg", "총중량"),
)
_ROLE_FIELDS_KO = (
    ("binder", "결합제"), ("disintegrant", "붕해제"), ("diluent", "희석제"), ("lubricant", "활택제"),
)


def _fmt_value(value: object) -> str:
    if value is None or value == "" or value == []:
        return "없음"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _fmt_total(value: float | None) -> str:
    return "자동" if value is None else f"{_fmt_value(value)} mg"


def _fmt_amount(item: ParsedAmount) -> str:
    return f"{item.ingredient} " + (f"{item.pct:g}%" if item.pct is not None else f"{item.mg:g} mg")


def request_changes(old: ParsedRequest, new: ParsedRequest) -> list[str]:
    """두 요청의 필드별 차이를 한국어 한 줄씩. 비어 있으면 바뀐 것이 없다(재생성하지 않는다)."""
    changes: list[str] = []
    old_apis = {a.name.casefold(): a for a in old.apis}
    new_apis = {a.name.casefold(): a for a in new.apis}
    for key in sorted(set(old_apis) | set(new_apis)):
        before, after = old_apis.get(key), new_apis.get(key)
        if before is None:
            changes.append(f"주성분 추가: {after.name}" + (f" {after.dose_mg:g} mg" if after.dose_mg else ""))
        elif after is None:
            changes.append(f"주성분 제거: {before.name}")
        elif before.dose_mg != after.dose_mg:
            changes.append(f"{after.name} 용량: {_fmt_value(before.dose_mg)} → {_fmt_value(after.dose_mg)} mg")
    for field_name, label in _REQUEST_FIELDS_KO:
        before, after = getattr(old, field_name), getattr(new, field_name)
        if isinstance(before, str) and isinstance(after, str):
            if before.strip().casefold() == after.strip().casefold():
                continue
        elif before == after:
            continue
        if field_name == "target_total_mg":
            changes.append(f"{label}: {_fmt_total(before)} → {_fmt_total(after)}")
        else:
            changes.append(f"{label}: {_fmt_value(before)} → {_fmt_value(after)}")
    roles_old = {label: list(getattr(old, name)) for name, label in _ROLE_FIELDS_KO}
    roles_new = {label: list(getattr(new, name)) for name, label in _ROLE_FIELDS_KO}
    roles_old.update({item.role: list(item.ingredients) for item in old.additional_roles})
    roles_new.update({item.role: list(item.ingredients) for item in new.additional_roles})
    for role in sorted(set(roles_old) | set(roles_new)):
        before, after = roles_old.get(role, []), roles_new.get(role, [])
        if [v.casefold() for v in before] != [v.casefold() for v in after]:
            changes.append(f"{role}: {_fmt_value(before)} → {_fmt_value(after)}")
    old_amounts = {a.ingredient.casefold(): a for a in old.amounts}
    new_amounts = {a.ingredient.casefold(): a for a in new.amounts}
    for key in sorted(set(old_amounts) | set(new_amounts)):
        before, after = old_amounts.get(key), new_amounts.get(key)
        if before is None:
            changes.append(f"분량 추가: {_fmt_amount(after)}")
        elif after is None:
            changes.append(f"분량 제거: {before.ingredient}")
        elif (before.mg, before.pct) != (after.mg, after.pct):
            changes.append(f"분량 변경: {_fmt_amount(before)} → {_fmt_amount(after)}")
    return changes


__all__ = [
    "CandidateExplanation", "ExplanationItem", "FollowUpResponse", "FormulationExplanation",
    "IngredientNote", "ParsedAPI", "ParsedAmount", "ParsedRequest", "ParsedRoleChoice",
    "request_changes",
]

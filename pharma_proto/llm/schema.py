"""One provider-neutral structured schema for formulation requests."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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


class ParsedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    apis: list[ParsedAPI] = Field(min_length=1, max_length=10)
    dosage_form: IngredientName = "tablet"
    binder: list[IngredientName] = Field(default_factory=list, max_length=20)
    disintegrant: list[IngredientName] = Field(default_factory=list, max_length=20)
    diluent: list[IngredientName] = Field(default_factory=list, max_length=20)
    lubricant: list[IngredientName] = Field(default_factory=list, max_length=20)
    additional_roles: list[ParsedRoleChoice] = Field(default_factory=list, max_length=40)
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


__all__ = [
    "CandidateExplanation", "ExplanationItem", "FormulationExplanation", "IngredientNote",
    "ParsedAPI", "ParsedRequest", "ParsedRoleChoice",
]

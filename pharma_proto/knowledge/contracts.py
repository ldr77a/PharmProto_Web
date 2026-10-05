from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol  # noqa: UP035 - keep the specified contract import

from pharma_proto.knowledge.evidence import FunctionDescriptor, IngredientEvidence


@dataclass(frozen=True)
class RangeStats:
    n: int
    lo: float | None = None
    hi: float | None = None
    mean: float | None = None
    p5: float | None = None
    p95: float | None = None
    median: float | None = None
    aggregation_mode: str | None = None
    identity: Mapping[str, object] | None = None
    excluded_reason: str | None = None


@dataclass(frozen=True)
class UsageEvidence:
    count: int
    source_types: tuple[str, ...]


# API 함량 구간. 잔여 채움 희석제의 % 는 API 함량의 산술 결과라 구간별로 심사한다(schema 3).
API_LOAD_BANDS: tuple[tuple[str, float, float], ...] = (
    ("le5", 0.0, 5.0), ("5_10", 5.0, 10.0), ("10_25", 10.0, 25.0), ("25_50", 25.0, 50.0), ("gt50", 50.0, 1e9),
)
API_LOAD_BAND_LABELS: Mapping[str, str] = {
    "le5": "API ≤5%", "5_10": "API 5~10%", "10_25": "API 10~25%", "25_50": "API 25~50%", "gt50": "API >50%",
}
FILLER_ANY_INGREDIENT = "*"


def api_load_band(api_pct: float | None) -> str | None:
    """API 합계 %(정제 전체 기준) → 구간 키. 경계는 아랫구간에 붙는다(5.0 → 'le5')."""
    if api_pct is None or api_pct < 0:
        return None
    for key, _low, high in API_LOAD_BANDS:
        if api_pct <= high:
            return key
    return API_LOAD_BANDS[-1][0]


class KnowledgeRepository(Protocol):
    def api_doses(self, name: str, *, mode: str | None = None) -> list[float]: ...

    def pct_range(self, ingredient: str, *, mode: str | None = None) -> RangeStats: ...

    def function(self, ingredient: str) -> str | None: ...

    def function_pct_range(self, function: str) -> RangeStats: ...

    def ingredient_candidates(
        self,
        functions: tuple[str, ...],
        *,
        dosage_form_bases: tuple[str, ...],
        limit: int = 3,
    ) -> list[str]: ...

    def compatibility_usage(self, api: str, excipient: str) -> UsageEvidence: ...

    def function_catalog(self) -> tuple[FunctionDescriptor, ...]: ...

    # 역할층(schema 2): "이 배합에서 맡은 역할" 기준 집계. 빈 결과는 None / [] / RangeStats(n=0).
    def primary_role(self, ingredient: str) -> str | None: ...

    def role_candidates(
        self,
        role: str,
        *,
        dosage_form_bases: tuple[str, ...],
        limit: int = 3,
    ) -> list[str]: ...

    def role_pct_range(self, ingredient: str, role: str) -> RangeStats: ...

    def role_pct_sum_range(self, role: str) -> RangeStats: ...

    # schema 3: API 함량 구간별 '가장 큰 희석제 %' 분포. 성분별 표본이 5 미만이면 전체('*') 행으로 대체.
    def filler_pct_range(self, ingredient: str, api_load_band: str) -> RangeStats: ...

    def ingredient_evidence(self, ingredient: str) -> IngredientEvidence: ...

    def health(self) -> Mapping[str, object]: ...

    def close(self) -> None: ...


class NullKnowledgeRepository:
    def api_doses(self, name: str, *, mode: str | None = None) -> list[float]:
        return []

    def pct_range(self, ingredient: str, *, mode: str | None = None) -> RangeStats:
        return RangeStats(n=0)

    def function(self, ingredient: str) -> str | None:
        return None

    def function_pct_range(self, function: str) -> RangeStats:
        return RangeStats(n=0)

    def ingredient_candidates(
        self,
        functions: tuple[str, ...],
        *,
        dosage_form_bases: tuple[str, ...],
        limit: int = 3,
    ) -> list[str]:
        return []

    def compatibility_usage(self, api: str, excipient: str) -> UsageEvidence:
        return UsageEvidence(count=0, source_types=())

    def function_catalog(self) -> tuple[FunctionDescriptor, ...]:
        return ()

    def primary_role(self, ingredient: str) -> str | None:
        return None

    def role_candidates(
        self,
        role: str,
        *,
        dosage_form_bases: tuple[str, ...],
        limit: int = 3,
    ) -> list[str]:
        return []

    def role_pct_range(self, ingredient: str, role: str) -> RangeStats:
        return RangeStats(n=0)

    def role_pct_sum_range(self, role: str) -> RangeStats:
        return RangeStats(n=0)

    def filler_pct_range(self, ingredient: str, api_load_band: str) -> RangeStats:
        return RangeStats(n=0)

    def ingredient_evidence(self, ingredient: str) -> IngredientEvidence:
        return IngredientEvidence.empty(ingredient)

    def health(self) -> Mapping[str, object]:
        return {"status": "unconfigured"}

    def close(self) -> None:
        pass


__all__ = [
    "API_LOAD_BANDS",
    "API_LOAD_BAND_LABELS",
    "FILLER_ANY_INGREDIENT",
    "KnowledgeRepository",
    "NullKnowledgeRepository",
    "RangeStats",
    "UsageEvidence",
    "api_load_band",
]

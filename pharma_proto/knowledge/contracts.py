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

    def ingredient_evidence(self, ingredient: str) -> IngredientEvidence:
        return IngredientEvidence.empty(ingredient)

    def health(self) -> Mapping[str, object]:
        return {"status": "unconfigured"}

    def close(self) -> None:
        pass


__all__ = [
    "KnowledgeRepository",
    "NullKnowledgeRepository",
    "RangeStats",
    "UsageEvidence",
]

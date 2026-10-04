"""Task C — 부형제 % 폴백 + 배분. 사용자 > KG 범위(canonical_base p50) > 기능 기본값.

배분 로직(희석제 q.s. 방식 — 현실 배합과 동일):
  1. API mg 고정 → 목표 총중량(target_total_mg) 기준 API% 계산.
  2. 기능성 부형제(binder/disintegrant/lubricant/glidant)는 KG 대표% (중앙값) 로 고정.
  3. 희석제(diluent)는 '나머지'로 채운다(100 - API% - 기능성%합) → Σ=100 이 구조적으로 보장.
각 % 에 source(user|kg|function_default) + n(KG표본) 을 붙인다(provenance).
"""

from __future__ import annotations

from dataclasses import dataclass

from gates.formulation import Component  # type: ignore[import-not-found]
from generation.oral_solid_profiles import role_aliases
from pharma_proto.knowledge import KnowledgeRepository, RangeStats

# KG에 없을 때 기능별 통상 % (중앙값 근사). (lo, hi) → mid 사용.
FUNCTION_DEFAULT: dict[str, tuple[float, float]] = {
    "binder": (2, 5), "disintegrant": (2, 8), "lubricant": (0.5, 2),
    "glidant": (0.2, 1), "diluent": (20, 80), "coating": (2, 4),
    "film_forming_agent": (2, 5), "plasticizer": (1, 3),
    "opacifier": (0.5, 2), "colorant": (0.1, 1),
    "sweetener": (0.5, 3), "flavoring_agent": (0.1, 1),
    "taste_masking_agent": (1, 5), "wetting_agent": (0.2, 2),
    "solubilizer": (1, 5), "dissolution_enhancer": (1, 5),
    "adsorbent": (1, 5), "anticaking_agent": (0.2, 2),
    "stabilizer": (0.1, 2), "antioxidant": (0.01, 0.5),
    "preservative": (0.05, 0.5), "buffer": (0.5, 5),
    "acidifying_agent": (0.1, 2), "alkalizing_agent": (0.1, 2),
    "chelating_agent": (0.01, 0.2), "sustained_release_agent": (10, 35),
    "granulation_aid": (1, 5), "moisture_control_agent": (0.2, 2),
}


@dataclass
class Alloc:
    name: str
    function: str
    pct: float
    source: str          # user | hpe6 | hpe6+kg | hpe6+kg_role | kg | kg_role | function_default | filler(q.s.)
    n: int = 0
    mg: float = 0.0


class InfeasibleAllocationError(ValueError):
    """Raised when fixed ingredients leave no positive diluent residual."""


def _rep_pct(
    repository: KnowledgeRepository | None,
    ingredient: str,
    func: str,
    user_pct: float | None,
    dosage_form: str,
) -> tuple[float, str, int]:
    if user_pct is not None:
        return user_pct, "user", 0
    if repository is not None:
        role_range = getattr(repository, "role_pct_range", None)   # schema 2: (성분, 역할) 별 범위
        stats = role_range(ingredient, func) if callable(role_range) else RangeStats(n=0)
        kg_label = "kg_role"
        if stats.n < 5 or not stats.median or stats.median <= 0:   # 표본 부족·0% 중앙값은 역할별 범위로 쓰지 않는다
            stats = repository.pct_range(ingredient)
            kg_label = "kg"
        evidence_lookup = getattr(repository, "ingredient_evidence", None)
        if callable(evidence_lookup):
            evidence = evidence_lookup(ingredient)
            aliases = set(role_aliases(func))
            reviewed = {"direct_monograph", "verified", "approved"}
            ranges = [
                item
                for item in evidence.use_ranges
                if item.function_name in aliases
                and item.unit == "%"
                and item.review_status in reviewed
                and (item.min_pct is not None or item.max_pct is not None)
            ]
            requested_form = dosage_form.casefold()
            ranges.sort(
                key=lambda item: (
                    0 if item.dosage_form and item.dosage_form.casefold() in requested_form else 1,
                    abs((item.max_pct or item.min_pct or 0) - (item.min_pct or item.max_pct or 0)),
                    item.evidence_id,
                )
            )
            if ranges:
                chosen = ranges[0]
                lo = chosen.min_pct if chosen.min_pct is not None else chosen.max_pct
                hi = chosen.max_pct if chosen.max_pct is not None else chosen.min_pct
                if lo is not None and hi is not None:
                    if (
                        stats.n >= 5
                        and stats.p5 is not None
                        and stats.p95 is not None
                    ):
                        intersection_lo = max(lo, stats.p5)
                        intersection_hi = min(hi, stats.p95)
                        if intersection_lo <= intersection_hi:
                            return (
                                round((intersection_lo + intersection_hi) / 2, 3),
                                f"hpe6+{kg_label}",
                                stats.n,
                            )
                    return round((lo + hi) / 2, 3), "hpe6", 1
        if stats.n > 0 and stats.median is not None:
            return round(stats.median, 3), kg_label, stats.n
    lo, hi = FUNCTION_DEFAULT.get(func, (1, 3))
    return round((lo + hi) / 2, 3), "function_default", 0


def allocate(
    spec_apis_doses,
    excipient_pick: dict[str, str],
    *,
    repository: KnowledgeRepository | None = None,
    target_total_mg: float,
    user_pcts: dict[str, float] | None = None,
    dosage_form: str = "",
):
    """한 후보의 성분 배분 → (components, allocs, total_mg, warnings).

    spec_apis_doses: [DoseResult] (mg 있는 것). excipient_pick: {function: chosen_name}.
    """
    user_pcts = user_pcts or {}
    warnings: list[str] = []

    api_mg = sum(d.mg for d in spec_apis_doses if d.mg) or 0.0
    # 목표 총중량: 사용자값 없으면 API mg + 여유(부형제분). 고용량 API(MgO 등)면 API가 다수를
    # 차지하도록 api_mg/0.6 근사(API~60%), 저용량이면 최소 여유 80mg 확보.
    total = target_total_mg or round(max(api_mg / 0.6, api_mg + 80), 0)

    # mg 중심 배분(반올림이 Σ를 흔들지 않게): 기능성은 KG%→mg, 희석제는 '남은 mg'로 정확히 채움.
    allocs: list[Alloc] = []
    non_filler_mg = 0.0
    for func, name in excipient_pick.items():
        if func != "diluent":
            pct, src, n = _rep_pct(
                repository, name, func, user_pcts.get(func), dosage_form
            )
            mg = round(pct / 100 * total, 3)
            non_filler_mg += mg
            allocs.append(Alloc(name, func, round(mg / total * 100, 3), src, n, mg=mg))

    diluent_name = excipient_pick.get("diluent")
    diluent_mg = round(total - api_mg - non_filler_mg, 3)   # 정확한 잔여(반올림 흡수)
    if diluent_name:
        if diluent_mg <= 0:
            raise InfeasibleAllocationError(
                f"insufficient diluent residual: {diluent_mg:.3f} mg"
            )
        allocs.append(Alloc(diluent_name, "diluent", round(diluent_mg / total * 100, 3),
                            "filler(q.s.)", 0, mg=diluent_mg))
    else:
        warnings.append("희석제 미지정 — Σ=100 보정 불가")

    # Component 리스트: 정확한 mg 를 그대로 사용 → Σmg=total, Σpct=100 (반올림 오차 없음).
    comps: list[Component] = []
    for d in spec_apis_doses:
        if d.mg:
            comps.append(Component(d.name, role="api", mg=d.mg,
                                   pct=round(d.mg / total * 100, 3), function="api"))
    for a in allocs:
        comps.append(Component(a.name, role="excipient", pct=a.pct, mg=a.mg, function=a.function))
    return comps, allocs, total, warnings

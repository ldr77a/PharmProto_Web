"""Task C — 부형제 % 폴백 + 배분. 사용자 > KG 범위(canonical_base p50) > 기능 기본값.

배분 로직(희석제 q.s. 방식 — 현실 배합과 동일):
  1. API mg 고정 → 목표 총중량(target_total_mg) 기준 API% 계산.
  2. 기능성 부형제(binder/disintegrant/lubricant/glidant)는 사용자 지정(% 또는 mg) 또는 KG 대표%(중앙값).
  3. 희석제(diluent)는 '나머지'로 채운다(100 - API% - 기능성%합) → Σ=100 이 구조적으로 보장.
     총중량이 없고 희석제 분량만 지정됐으면 그 분량이 맞아떨어지는 총중량을 거꾸로 푼다.
각 % 에 source(user|user_adjusted|kg|function_default…) + n(KG표본) 을 붙인다(provenance).
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
    source: str          # user | user_adjusted | hpe6 | hpe6+kg | hpe6+kg_role | kg | kg_role | function_default | filler(q.s.)
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


def default_total_mg(api_mg: float) -> float:
    """사용자 총중량이 없을 때의 기본 총중량. 고용량 API(MgO 등)면 API≈60% 근사, 저용량이면 여유 80 mg."""
    return round(max(api_mg / 0.6, api_mg + 80), 0)


def _solve_total(api_mg: float, fixed_mg: float, fraction_sum: float) -> float:
    """비율(%)로 정해진 몫과 mg 로 정해진 몫이 함께 맞아떨어지는 총중량.

    total = (api_mg + Σmg지정) / (1 − Σ비율지정). 비율 합이 100% 에 닿으면 풀 수 없다.
    """
    denominator = 1.0 - fraction_sum
    if denominator <= 0:
        raise InfeasibleAllocationError(
            f"user fractions leave no room: {fraction_sum * 100:.2f}% already assigned"
        )
    return round((api_mg + fixed_mg) / denominator, 3)


def allocate(
    spec_apis_doses,
    excipient_pick: dict[str, str],
    *,
    repository: KnowledgeRepository | None = None,
    target_total_mg: float,
    user_pcts: dict[str, float] | None = None,
    user_mgs: dict[str, float] | None = None,
    dosage_form: str = "",
):
    """한 후보의 성분 배분 → (components, allocs, total_mg, warnings).

    spec_apis_doses: [DoseResult] (mg 있는 것). excipient_pick: {function: chosen_name}.
    user_pcts / user_mgs: 역할(function) 키의 사용자 지정 %, mg. 같은 역할에 둘 다 있으면 % 가 이긴다.
    분량 지정이 하나도 없으면 결과는 예전 구현과 수치까지 같다.
    """
    user_pcts = user_pcts or {}
    user_mgs = user_mgs or {}
    warnings: list[str] = []

    api_mg = sum(d.mg for d in spec_apis_doses if d.mg) or 0.0

    # 1패스 — 비희석 역할마다 비율(%) 또는 절대량(mg) 을 정한다(총중량은 아직 모름).
    planned: list[tuple[str, str, float | None, float | None, str, int]] = []
    fraction_sum = 0.0
    fixed_mg = 0.0
    for func, name in excipient_pick.items():
        if func == "diluent":
            continue
        if func in user_mgs and func not in user_pcts:
            mg = float(user_mgs[func])
            planned.append((func, name, None, mg, "user", 0))
            fixed_mg += mg
        else:
            pct, src, n = _rep_pct(repository, name, func, user_pcts.get(func), dosage_form)
            planned.append((func, name, pct, None, src, n))
            fraction_sum += pct / 100

    # 2 — 총중량. 사용자값 > 희석제 지정량으로 역산 > 기본식.
    diluent_name = excipient_pick.get("diluent")
    diluent_user_pct = user_pcts.get("diluent") if diluent_name else None
    diluent_user_mg = user_mgs.get("diluent") if diluent_name and diluent_user_pct is None else None
    if target_total_mg:
        total = target_total_mg
    elif diluent_user_pct is not None or diluent_user_mg is not None:
        total = _solve_total(
            api_mg,
            fixed_mg + (diluent_user_mg or 0.0),
            fraction_sum + (diluent_user_pct or 0.0) / 100,
        )
    else:
        total = default_total_mg(api_mg)

    # 2패스 — mg 중심 배분(반올림이 Σ를 흔들지 않게): 비율 역할은 %→mg, mg 역할은 그대로.
    allocs: list[Alloc] = []
    non_filler_mg = 0.0
    for func, name, pct, mg, src, n in planned:
        if mg is None:
            mg = round(pct / 100 * total, 3)
        non_filler_mg += mg
        allocs.append(Alloc(name, func, round(mg / total * 100, 3), src, n, mg=mg))

    # 희석제는 언제나 '남은 mg'(q.s.) — 지정량이 있어도 총중량이 이긴다. 차이가 크면 표시·경고.
    diluent_mg = round(total - api_mg - non_filler_mg, 3)   # 정확한 잔여(반올림 흡수)
    if diluent_name:
        if diluent_mg <= 0:
            raise InfeasibleAllocationError(
                f"insufficient diluent residual: {diluent_mg:.3f} mg"
            )
        source = "filler(q.s.)"
        requested_mg = diluent_user_mg
        if diluent_user_pct is not None:
            requested_mg = diluent_user_pct / 100 * total
        if requested_mg is not None:
            source = "user"
            if abs(diluent_mg - requested_mg) > max(1.0, 0.005 * total):
                source = "user_adjusted"
                warnings.append(
                    f"희석제 {diluent_name}: 지정 {requested_mg / total * 100:.2f}% → "
                    f"잔여 {diluent_mg / total * 100:.2f}% (총중량 {total:g} mg 고정)"
                )
        allocs.append(Alloc(diluent_name, "diluent", round(diluent_mg / total * 100, 3),
                            source, 0, mg=diluent_mg))
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

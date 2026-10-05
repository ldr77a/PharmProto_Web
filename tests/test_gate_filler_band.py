"""게이트1: 잔여 채움 희석제는 API 함량 구간별 분포로 심사한다 (Neo4j 불필요).

암로디핀 5 mg / 100 mg 정제처럼 API 가 5% 이하면 희석제 하나가 85% 를 넘는 것이 정상이다.
성분 전체 범위(MCC p95 62.9%)로 보면 실패하지만 같은 구간(API ≤5%)의 분포(p95 96.5%)로 보면 통과한다.
"""

from __future__ import annotations

from gates import allowable_range
from gates.formulation import Component, FormulationInput
from pharma_proto.knowledge import RangeStats
from tests.product.fakes import FakeKnowledge

MCC_GLOBAL = RangeStats(n=2104, lo=1, hi=99, mean=20, p5=2.87, p95=62.89, median=16.8)
MCC_LE5 = RangeStats(n=216, lo=10, hi=99, mean=50, p5=7.0, p95=96.5, median=47.0)


def _formulation(api_pct: float, filler_pct: float, *, filler: bool = True) -> FormulationInput:
    return FormulationInput(components=[
        Component("amlodipine besylate", role="api", mg=api_pct, pct=api_pct, function="api"),
        Component("magnesium stearate", role="excipient", mg=1, pct=1.0, function="lubricant"),
        Component("microcrystalline cellulose", role="excipient", mg=filler_pct, pct=filler_pct,
                  function="diluent", filler=filler),
    ], target_total_mg=100.0)


def test_low_dose_filler_passes_with_band_range():
    repository = FakeKnowledge(
        ranges={"microcrystalline cellulose": MCC_GLOBAL, "magnesium stearate": RangeStats(n=2900, p5=0.1, p95=2.0, median=0.96)},
        filler_ranges={("microcrystalline cellulose", "le5"): MCC_LE5},
    )
    result = allowable_range.check(_formulation(5.0, 86.0), repository=repository)

    assert result.status == "pass", result.details
    assert any("KG 잔여채움·API ≤5%" in line and "n=216" in line for line in result.details)


def test_same_share_fails_against_global_range_when_not_marked_as_filler():
    repository = FakeKnowledge(
        ranges={"microcrystalline cellulose": MCC_GLOBAL, "magnesium stearate": RangeStats(n=2900, p5=0.1, p95=2.0, median=0.96)},
        filler_ranges={("microcrystalline cellulose", "le5"): MCC_LE5},
    )
    result = allowable_range.check(_formulation(5.0, 86.0, filler=False), repository=repository)

    assert result.status == "fail" and "초과 (p95=62.89%" in result.reason


def test_filler_falls_back_to_global_range_without_band_data():
    repository = FakeKnowledge(
        ranges={"microcrystalline cellulose": MCC_GLOBAL, "magnesium stearate": RangeStats(n=2900, p5=0.1, p95=2.0, median=0.96)},
    )
    result = allowable_range.check(_formulation(5.0, 86.0), repository=repository)

    assert result.status == "fail"


def test_high_dose_filler_is_still_judged_in_its_own_band():
    repository = FakeKnowledge(
        ranges={"microcrystalline cellulose": MCC_GLOBAL, "magnesium stearate": RangeStats(n=2900, p5=0.1, p95=2.0, median=0.96)},
        filler_ranges={("*", "gt50"): RangeStats(n=356, lo=1, hi=60, mean=12, p5=2.1, p95=31.8, median=11.1)},
    )
    result = allowable_range.check(_formulation(60.0, 39.0), repository=repository)

    assert result.status == "fail" and "KG 잔여채움·API >50%" in result.reason

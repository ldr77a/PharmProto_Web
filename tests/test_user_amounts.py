"""피드백 3번 — 사용자가 적은 성분별 분량(mg·%)과 총중량이 조성표에 그대로 반영되는지."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from generation.dose_resolver import DoseResult
from generation.excipient_allocator import (
    InfeasibleAllocationError,
    allocate,
    default_total_mg,
)
from generation.generation_loop import run_generation
from generation.input_parser import AmountSpec, build_spec
from pharma_proto.knowledge import RangeStats
from pharma_proto.llm.schema import ParsedAmount, ParsedRequest
from tests.product.fakes import FakeKnowledge

_PICK = {
    "binder": "povidone",
    "disintegrant": "croscarmellose sodium",
    "lubricant": "magnesium stearate",
    "diluent": "mannitol",
}
_EXCIPIENTS = {role: [name] for role, name in _PICK.items()}


def _doses(mg: float = 500.0) -> list[DoseResult]:
    return [DoseResult("acetaminophen", mg, "user", "사용자 지정")]


def _by_function(allocs) -> dict:
    return {alloc.function: alloc for alloc in allocs}


def _allocate(**kwargs):
    kwargs.setdefault("repository", FakeKnowledge())
    kwargs.setdefault("dosage_form", "tablet")
    kwargs.setdefault("target_total_mg", None)
    return allocate(_doses(), _PICK, **kwargs)


def test_allocate_without_amounts_is_unchanged() -> None:
    """분량 지정이 없으면 재구성 전 구현과 수치까지 같아야 한다(회귀 기준: 2026-10-04 실측)."""
    comps, allocs, total, warnings = _allocate()

    assert total == 833.0 == default_total_mg(500.0)
    by = _by_function(allocs)
    for role in ("binder", "disintegrant", "lubricant"):
        assert (by[role].pct, by[role].mg, by[role].source, by[role].n) == (4.0, 33.32, "kg", 10)
    assert (by["diluent"].pct, by["diluent"].mg, by["diluent"].source) == (27.976, 233.04, "filler(q.s.)")
    assert round(sum(c.mg for c in comps), 3) == 833.0
    assert warnings == []

    _, allocs, total, _ = _allocate(target_total_mg=800)
    by = _by_function(allocs)
    assert total == 800
    assert by["binder"].mg == 32.0
    assert (by["diluent"].pct, by["diluent"].mg) == (25.5, 204.0)


def test_allocate_honors_user_pct_for_functional_role() -> None:
    _, allocs, _, _ = _allocate(target_total_mg=800, user_pcts={"disintegrant": 6.0})

    by = _by_function(allocs)
    disintegrant = by["disintegrant"]
    assert (disintegrant.pct, disintegrant.mg, disintegrant.source, disintegrant.n) == (6.0, 48.0, "user", 0)
    assert by["binder"].source == "kg"
    assert by["diluent"].mg == 800 - 500 - 48 - 32 - 32


def test_allocate_converts_user_mg_to_pct_at_total() -> None:
    _, allocs, _, _ = _allocate(target_total_mg=800, user_mgs={"lubricant": 8.0})

    lubricant = _by_function(allocs)["lubricant"]
    assert (lubricant.mg, lubricant.pct, lubricant.source) == (8.0, 1.0, "user")


def test_allocate_solves_total_when_diluent_pct_given_without_total() -> None:
    _, allocs, total, warnings = _allocate(user_pcts={"diluent": 30.0})

    by = _by_function(allocs)
    # API 500 mg + 기능성 3×4% + 희석제 30% → total = 500 / (1 − 0.42)
    assert total == pytest.approx(500 / 0.58, abs=0.001)
    assert by["diluent"].pct == pytest.approx(30.0, abs=0.01)
    assert by["diluent"].source == "user"
    assert warnings == []


def test_allocate_solves_total_from_diluent_mg_when_everything_is_in_mg() -> None:
    _, allocs, total, _ = _allocate(
        user_mgs={"binder": 20.0, "disintegrant": 30.0, "lubricant": 5.0, "diluent": 145.0},
    )

    assert total == 700.0
    by = _by_function(allocs)
    assert by["diluent"].mg == 145.0 and by["diluent"].source == "user"
    assert by["binder"].pct == pytest.approx(20 / 700 * 100, abs=0.001)


def test_allocate_keeps_user_total_and_flags_diluent_gap() -> None:
    _, allocs, total, warnings = _allocate(target_total_mg=800, user_pcts={"diluent": 50.0})

    by = _by_function(allocs)
    assert total == 800 and by["diluent"].pct == 25.5
    assert by["diluent"].source == "user_adjusted"
    assert any("희석제 mannitol" in w and "50.00%" in w and "25.50%" in w for w in warnings)


def test_allocate_raises_when_user_amounts_leave_no_residual() -> None:
    with pytest.raises(InfeasibleAllocationError):
        _allocate(target_total_mg=800, user_mgs={"binder": 400.0})
    with pytest.raises(InfeasibleAllocationError):
        _allocate(user_pcts={"diluent": 90.0})          # 3×4% + 90% > 100%


def test_run_generation_never_adjusts_user_total() -> None:
    """희석제가 KG 범위를 벗어나도 사용자 총중량은 ×0.85 재시도로 바꾸지 않는다."""
    spec = build_spec([("acetaminophen", 500.0)], _EXCIPIENTS, n_candidates=1, target_total_mg=800)

    out = run_generation(spec, repository=FakeKnowledge(), offline=True)

    assert len(out) == 1
    cand = out[0]
    assert cand.total_mg == 800 and cand.retries == 0
    assert cand.status == "unresolved"
    assert any("사용자 지정 총중량" in note for note in cand.notes)


def test_run_generation_downgrades_user_range_violation_to_warning() -> None:
    wide = FakeKnowledge(
        ranges={"mannitol": RangeStats(n=10, lo=10, hi=90, mean=40, p5=10, p95=90, median=40)},
    )
    spec = build_spec(
        [("acetaminophen", 500.0)], _EXCIPIENTS, n_candidates=1, target_total_mg=800,
        amounts={"croscarmellose sodium": (None, 15.0)},
    )

    cand = run_generation(spec, repository=wide, offline=True)[0]

    by = _by_function(cand.allocs)
    assert (by["disintegrant"].pct, by["disintegrant"].source) == (15.0, "user")
    gate1 = next(r for r in cand.gate_out["results"] if r.gate.startswith("게이트1"))
    assert gate1.status == "fail"                       # 칩에는 실패가 그대로 보인다
    assert cand.status == "warning"                     # 후보 배지만 '조건부'로
    assert any("사용자 지정 분량 1건" in note for note in cand.notes)


def test_run_generation_rekeys_ingredient_amounts_per_pick() -> None:
    spec = build_spec(
        [("acetaminophen", 500.0)], _EXCIPIENTS, n_candidates=1, target_total_mg=800,
        amounts={"스테아르산마그네슘": (8.0, None), "MCC": (None, 20.0)},
    )

    cand = run_generation(spec, repository=FakeKnowledge(), offline=True)[0]

    lubricant = _by_function(cand.allocs)["lubricant"]
    assert (lubricant.mg, lubricant.source) == (8.0, "user")
    assert "microcrystalline cellulose" in spec.user_amounts      # 후보에 없는 성분은 그대로 남는다


def test_parsed_request_amounts_normalize_into_spec() -> None:
    parsed = ParsedRequest.model_validate({
        "apis": [{"name": "acetaminophen", "dose_mg": 500}],
        "diluent": ["MCC"],
        "lubricant": ["magnesium stearate"],
        "amounts": [{"ingredient": "MCC", "pct": 40}, {"ingredient": "스테아르산마그네슘", "mg": 1}],
    })

    spec = parsed.to_domain()

    assert spec.user_amounts == {
        "microcrystalline cellulose": AmountSpec(mg=None, pct=40.0),
        "magnesium stearate": AmountSpec(mg=1.0, pct=None),
    }


def test_parsed_amount_treats_zero_as_absent_and_requires_one_value() -> None:
    amount = ParsedAmount.model_validate({"ingredient": "mannitol", "mg": 0, "pct": 5})
    assert amount.mg is None and amount.pct == 5

    with pytest.raises(ValidationError):
        ParsedAmount.model_validate({"ingredient": "mannitol", "mg": 0})


def test_amount_for_api_fills_missing_dose() -> None:
    parsed = ParsedRequest.model_validate({
        "apis": [{"name": "acetaminophen"}],
        "amounts": [{"ingredient": "acetaminophen", "mg": 500}],
    })

    spec = parsed.to_domain()

    assert spec.apis[0].dose_mg == 500.0
    assert spec.user_amounts == {}

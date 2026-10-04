"""게이트 2 — 제조성 대리지표. soft(경고만). 물리시험 대체 아님을 명시.

물리 데이터(경도·마손) 없이 "실제 제조된 배합들이 지킨 비율 규칙"에 따르는지로 근사한다:
  1) 결합제 존재    : binder 기능 성분이 있나. 없으면 경고(압축성 우려).
  2) 붕해-결합 균형 : disintegrant %합·binder %합이 KG 분포(p5~p95) 안인가.
  3) 활택제 상한    : lubricant %합이 KG p95 이하인가(과다→코팅/붕해 지연).
전부 hard 아님(조건부 경고). 출력에 "대리지표" 한계 명시.
"""

from __future__ import annotations

from gates.formulation import (  # type: ignore[import-not-found]
    FormulationInput,
    GateResult,
)
from gates.kg_util import function_for_component, load_function_seed  # type: ignore
from pharma_proto.knowledge import KnowledgeRepository

_PROV = "KG 대리지표: 기능별 %합 분포(p5~p95). 물리시험(경도·마손·용출) 대체 아님"


def _pct_sum_by_function(
    fi: FormulationInput,
    repository: KnowledgeRepository,
) -> dict[str, float]:
    seed = load_function_seed()
    sums: dict[str, float] = {}
    for c in fi.components:
        if c.pct is None or c.process_material:
            continue
        fn = function_for_component(repository, c, seed)
        if fn:
            sums[fn] = sums.get(fn, 0.0) + c.pct
    return sums


def check(
    fi: FormulationInput,
    *,
    repository: KnowledgeRepository | None = None,
    **_,
) -> GateResult:
    if repository is None:
        return GateResult("게이트2 제조성 대리지표", "skip", "KG 미연결", hard=False)

    sums = _pct_sum_by_function(fi, repository)
    warns, notes = [], []

    # 1) 결합제 존재
    if sums.get("binder", 0) <= 0:
        warns.append("결합제 없음 → 정제 압축성 우려")

    # 2)·3) 기능별 %합이 KG 분포 안인가
    for func in ("binder", "disintegrant", "lubricant"):
        s = sums.get(func)
        if s is None:
            continue
        role_sum = getattr(repository, "role_pct_sum_range", None)   # schema 2: 추정 역할 기준 %합 분포
        stats = role_sum(func) if callable(role_sum) else None
        if stats is None or stats.n < 5:
            stats = repository.function_pct_range(func)
        if stats.n < 5:
            notes.append(f"{func} 분포표본 부족(n={stats.n})")
            continue
        p5, p95 = stats.p5, stats.p95
        if p5 is None or p95 is None:
            notes.append(f"{func} 분포표본 부족(n={stats.n})")
            continue
        if s > p95:
            msg = "활택제 과다 → 코팅/붕해 지연" if func == "lubricant" else f"{func} %합 과다"
            warns.append(f"{msg} ({s:.2f}% > p95 {p95:.2f}%)")
        elif s < p5 and func != "lubricant":
            warns.append(f"{func} %합 부족 ({s:.2f}% < p5 {p5:.2f}%)")

    details = warns + notes
    if warns:
        return GateResult("게이트2 제조성 대리지표", "warning",
                          f"제조성 근사 경고 {len(warns)}건: {warns[0]} [대리지표]",
                          provenance=_PROV, hard=False, details=details)
    return GateResult("게이트2 제조성 대리지표", "pass",
                      "근사: 결합제 존재·기능 %합 KG 분포 내 [대리지표]",
                      provenance=_PROV, hard=False, details=details)

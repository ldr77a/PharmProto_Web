"""게이트 1 — 사용량 범위. 각 부형제 %가 KG 실제 배합의 p5~p95 안인가.

핵심(사용자 확인): 범위는 개별 CONTAINS 의 pct_min/max(배합 1건)가 아니라, **canonical_base 로
묶인 모든 CONTAINS.pct 를 집계**해서 나온다(정제 반영). 극단 이상치 제외 위해 p5~p95 사용.

표본 적으면(n<5) 하드 판정 대신 "신뢰도 낮음" 경고. 공정용매·노이즈는 제외.
잔여 채움(q.s.) 희석제는 성분 전체 범위가 아니라 같은 API 함량 구간의 "가장 큰 희석제 %" 분포로 심사한다
(저용량 정제는 희석제 하나가 80~95% 인 것이 정상, schema 3 lookup_filler_pct_ranges).
"""

from __future__ import annotations

from gates.formulation import (  # type: ignore[import-not-found]
    FormulationInput,
    GateResult,
)
from gates.kg_util import base_of  # type: ignore[import-not-found]
from pharma_proto.knowledge import KnowledgeRepository, RangeStats
from pharma_proto.knowledge.contracts import API_LOAD_BAND_LABELS, api_load_band

MIN_SAMPLES = 5


def check(
    fi: FormulationInput,
    *,
    repository: KnowledgeRepository | None = None,
    min_samples: int = MIN_SAMPLES,
    **_,
) -> GateResult:
    if repository is None:
        return GateResult("게이트1 사용량 범위", "skip", "KG 미연결", hard=True)

    hard_fail, warn, unknown, ok, details = [], [], [], [], []
    api_pct = sum(a.pct for a in fi.apis() if a.pct is not None)
    band = api_load_band(api_pct)
    filler_lookup = getattr(repository, "filler_pct_range", None)
    for c in fi.excipients():
        if c.process_material or c.pct is None:
            continue
        base = base_of(c.name)
        stats = RangeStats(n=0)
        basis = "KG"
        if getattr(c, "filler", False) and band is not None and callable(filler_lookup):
            # 잔여 채움 희석제의 % 는 API 함량의 산술 결과 → 같은 API 함량 구간의 '가장 큰 희석제 %' 분포와 비교(schema 3)
            stats = filler_lookup(c.name, band)
            basis = f"KG 잔여채움·{API_LOAD_BAND_LABELS.get(band, band)}"
        if stats.n == 0:
            stats = repository.pct_range(c.name)
            basis = "KG"
        n = stats.n
        if n == 0:
            unknown.append(f"{base}: KG 범위 근거 없음")
            continue
        p5, p95 = stats.p5, stats.p95
        if p5 is None or p95 is None:
            unknown.append(f"{base}: KG 범위 근거 없음")
            continue
        line = f"{base} {c.pct:.2f}% vs {basis}[p5~p95={p5:.2f}~{p95:.2f}%, n={n}]"
        if p5 <= c.pct <= p95:
            if n < min_samples:
                warn.append(f"{line} (범위내나 표본 {n}건 — 신뢰도 낮음)")
            else:
                ok.append(line)
        else:
            side = "초과" if c.pct > p95 else "미만"
            entry = (f"{base} {c.pct:.2f}% {side} (p{'95' if c.pct>p95 else '5'}={p95 if c.pct>p95 else p5:.2f}%, n={n}"
                     + (f", {basis}" if basis != "KG" else "") + ")")
            (warn if n < min_samples else hard_fail).append(entry)
    details = hard_fail + warn + unknown + ok + details

    if hard_fail:
        return GateResult("게이트1 사용량 범위", "fail",
                          f"범위 벗어남 {len(hard_fail)}건: {hard_fail[0]}",
                          provenance="KG 집계: canonical_base 별 CONTAINS.pct p5~p95",
                          hard=True, details=details)
    if warn:
        return GateResult("게이트1 사용량 범위", "warning",
                          f"주의 {len(warn)}건(범위밖 또는 표본부족): {warn[0]}",
                          provenance="KG 집계: canonical_base 별 CONTAINS.pct p5~p95",
                          hard=True, details=details)
    if unknown:
        return GateResult("게이트1 사용량 범위", "warning",
                          f"KG 범위 근거 없음 {len(unknown)}건: {unknown[0]}",
                          provenance="KG 집계: canonical_base 별 CONTAINS.pct p5~p95",
                          hard=True, details=details)
    return GateResult("게이트1 사용량 범위", "pass",
                      f"모든 부형제 % 가 KG 범위 내 ({len(ok)}건 확인)",
                      provenance="KG 집계: canonical_base 별 CONTAINS.pct p5~p95",
                      hard=True, details=details)

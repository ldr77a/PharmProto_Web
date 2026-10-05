"""Task D — 생성 루프(Agentic). 후보 조성 생성 → 5게이트 검증 → 재배분 재시도.

각 후보: 부형제 선택지를 달리(candidate i = 각 기능의 i번째 선택지) → "몇 가지" 충족.
hard fail 시 target 총중량을 조정해 재시도(희석제 % 를 범위로). 수렴 실패는 '미해결' 표시.
기존 gates/ 를 재사용(게이트 재구현 안 함).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from gates.formulation import FormulationInput  # type: ignore[import-not-found]
from gates.pipeline import run_pipeline  # type: ignore[import-not-found]
from generation.candidate_selector import complete_excipient_choices
from generation.dose_resolver import resolve_dose  # type: ignore[import-not-found]
from generation.excipient_allocator import (  # type: ignore[import-not-found]
    InfeasibleAllocationError,
    allocate,
)
from pharma_proto.knowledge import KnowledgeRepository

MAX_RETRIES = 3


@dataclass
class Candidate:
    idx: int
    pick: dict
    doses: list
    allocs: list
    components: list
    total_mg: float
    gate_out: dict
    status: str                 # pass | warning | unresolved
    notes: list = field(default_factory=list)
    retries: int = 0
    evidence_by_ingredient: dict = field(default_factory=dict)


def _evidence_for_components(repository: KnowledgeRepository, components: list) -> dict:
    lookup = getattr(repository, "ingredient_evidence", None)
    if not callable(lookup):
        return {}
    evidence: dict = {}
    for component in components:
        key = component.name.casefold()
        if key not in evidence:
            evidence[key] = lookup(component.name)
    return evidence


def _distinct_picks(spec, k: int) -> list[dict]:
    """서로 다른 부형제 조합 k 개(itertools.product 로 진짜 다른 조합). 후보 중복 방지."""
    funcs = [f for f, ch in spec.excipient_choices.items() if ch]
    lists = [spec.excipient_choices[f] for f in funcs]
    combos: list[dict] = []
    for index in range(k):
        # 역할 순서대로 index 번째 선택지를 쓰되, 앞 역할이 이미 쓴 성분(예: 활택제 talc 와 활택보조 talc)이면
        # 그 역할만 다음 선택지로 넘기고, 남는 선택지가 없으면 그 역할을 이 후보에서 뺀다.
        # 후보 1 이 사용자가 첫 번째로 적은 성분(희석제 mannitol 등)을 그대로 쓰도록 조합 전체를 버리지 않는다.
        used: set[str] = set()
        pick: dict = {}
        for func, choices in zip(funcs, lists, strict=True):
            chosen = next(
                (choices[(index + shift) % len(choices)] for shift in range(len(choices))
                 if choices[(index + shift) % len(choices)].casefold() not in used),
                None,
            )
            if chosen is None:
                continue
            used.add(chosen.casefold())
            pick[func] = chosen
        if pick and pick not in combos:
            combos.append(pick)
    if len(combos) == k:
        return combos
    for values in product(*lists):
        if len({value.casefold() for value in values}) != len(values):
            continue
        pick = dict(zip(funcs, values))
        if pick in combos:
            continue
        combos.append(pick)
        if len(combos) == k:
            break
    return combos


def _adjust_total(total: float, gate_out: dict, allocs: list) -> float | None:
    """게이트1이 희석제 % 로 실패하면 총중량 조정으로 범위 진입 시도. 없으면 None."""
    g1 = next((r for r in gate_out["results"] if r.gate.startswith("게이트1")), None)
    if not g1 or g1.status != "fail":
        return None
    diluent = next((a for a in allocs if a.function == "diluent"), None)
    if not diluent:
        return None
    violations = [
        str(detail)
        for detail in g1.details
        if "초과" in str(detail) or "미만" in str(detail)
    ]
    diluent_prefix = f"{diluent.name.casefold()} "
    if len(violations) != 1 or not violations[0].casefold().startswith(diluent_prefix):
        return None
    # 희석제 자체의 % 초과면 총중량↓(API%↑→잔여↓), 미만이면 총중량↑.
    if "초과" in violations[0]:
        return round(total * 0.85, 0)
    if "미만" in violations[0]:
        return round(total * 1.15, 0)
    return None


def _user_amounts_for_pick(spec, pick: dict) -> tuple[dict[str, float], dict[str, float]]:
    """성분 키의 사용자 분량(spec.user_amounts)을 이 후보의 역할 키로 옮긴다(% 와 mg 를 따로)."""
    amounts = getattr(spec, "user_amounts", None) or {}
    pcts: dict[str, float] = {}
    mgs: dict[str, float] = {}
    for role, name in pick.items():
        amount = amounts.get(name.casefold())
        if amount is None:
            continue
        if amount.pct is not None:
            pcts[role] = float(amount.pct)
        elif amount.mg is not None:
            mgs[role] = float(amount.mg)
    return pcts, mgs


def _user_range_violations(gate_out: dict, allocs: list) -> list[str] | None:
    """하드 실패가 게이트1 뿐이고 그 위반이 전부 사용자 지정 분량이면 그 세부 줄들을 돌려준다.

    사용자가 적은 값은 바꾸지 않으므로 '미해결' 대신 '조건부 후보'로 내리고 검토를 요청한다.
    다른 하드 실패가 섞여 있거나 자동 배분 성분의 위반이면 None(미해결 유지).
    """
    hard = gate_out.get("hard_fails") or []
    if not hard or any(not r.gate.startswith("게이트1") for r in hard):
        return None
    user_names = [a.name.casefold() for a in allocs if a.source in ("user", "user_adjusted")]
    if not user_names:
        return None
    violations = [
        str(detail) for detail in hard[0].details
        if "초과" in str(detail) or "미만" in str(detail)
    ]
    if not violations:
        return None
    for line in violations:
        if not any(line.casefold().startswith(f"{name} ") for name in user_names):
            return None
    return violations


def run_generation(
    spec,
    *,
    repository: KnowledgeRepository,
    offline: bool = True,
) -> list[Candidate]:
    standard = None
    out: list[Candidate] = []
    profile = complete_excipient_choices(spec, repository)
    doses = [
        resolve_dose(a, repository=repository, standard=standard) for a in spec.apis
    ]

    picks = _distinct_picks(spec, spec.n_candidates)
    for i, pick in enumerate(picks):
        if not pick:
            break
        total = spec.target_total_mg
        user_pcts, user_mgs = _user_amounts_for_pick(spec, pick)
        # 사용자가 총중량이나 희석제 분량을 정했으면 총중량을 흔들지 않는다(재배분 재시도 없음).
        total_fixed = total is not None or "diluent" in user_pcts or "diluent" in user_mgs
        cand = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                comps, allocs, total_mg, warns = allocate(
                    doses,
                    pick,
                    repository=repository,
                    target_total_mg=total,
                    user_pcts=user_pcts,
                    user_mgs=user_mgs,
                    dosage_form=spec.dosage_form,
                )
            except InfeasibleAllocationError:
                cand = None
                break
            fi = FormulationInput(components=comps, dosage_form=spec.dosage_form,
                                  target_total_mg=total_mg,
                                  profile_id=profile.profile_id,
                                  required_functions=profile.required_functions)
            gate_out = run_pipeline(fi, repository=repository, offline=offline)
            status = "unresolved" if gate_out["hard_fails"] else (
                "warning" if gate_out["warnings"] else "pass")
            user_notes: list[str] = []
            if status == "unresolved":
                user_violations = _user_range_violations(gate_out, allocs)
                if user_violations:
                    # 사용자 값은 바꾸지 않는다 — 칩에는 게이트1 실패가 그대로 남고 배지만 '조건부'.
                    status = "warning"
                    user_notes.append(
                        f"게이트1: 사용자 지정 분량 {len(user_violations)}건이 KG 범위 밖 — "
                        f"지정값 유지, 검토 필요: {user_violations[0]}"
                    )
            source_labels = {
                "kg": "DB 근거",
                "kg_role": "DB 역할별 근거",
                "kg+curated_default": "DB 근거 + 검토 기본값",
                "kg_role+curated_default": "DB 역할별 근거 + 검토 기본값",
                "curated_default": "검토 기본값",
            }
            selection_notes = [
                f"자동선정 {role}: {source_labels.get(source, source)}"
                for role, source in spec.selection_sources.items()
                if source != "user"
            ]
            cand = Candidate(
                i + 1,
                pick,
                doses,
                allocs,
                comps,
                total_mg,
                gate_out,
                status,
                notes=list(warns) + user_notes + selection_notes,
                retries=attempt,
                evidence_by_ingredient=_evidence_for_components(repository, comps),
            )
            if status != "unresolved":
                break
            if total_fixed:
                cand.notes.append("사용자 지정 총중량·분량 유지 — 재배분 없이 게이트 결과를 그대로 보고")
                break
            new_total = _adjust_total(total_mg, gate_out, allocs)
            if new_total is None or new_total == total:
                break
            total = new_total     # 재시도
        if cand:
            if cand.status == "unresolved":
                cand.notes.append("수렴 실패 — 게이트 하드 실패 잔존(재배분으로 미해결)")
            out.append(cand)
    return out

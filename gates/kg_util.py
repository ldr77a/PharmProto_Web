"""게이트용 KG 헬퍼 — legacy와 Resolution 집계를 함께 계산한다.

``canonical_base`` 집계는 전환 비교용 legacy로 유지한다. 새 숫자 집계는 검증된
MaterialGrade만 허용하며, 등급 불명 Substance와 미해결 이름은 생성 입력에서 제외한다.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pharma_proto.knowledge import KnowledgeRepository, UsageEvidence

_SEED_PATH = Path(__file__).resolve().parent.parent / "function_seed.json"


@lru_cache(maxsize=1)
def load_function_seed() -> dict[str, str]:
    data = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    return data.get("map", {})


def base_of(name: str) -> str:
    """성분명 → canonical_base(정제 규칙 재사용). KG 없이."""
    from cleaning.canonical_base import classify_base  # type: ignore[import-not-found]
    return classify_base(name).canonical_base


def function_for_component(
    repository: KnowledgeRepository | None,
    comp,
    seed: dict[str, str] | None = None,
) -> str | None:
    """성분 기능: 명시값 > repository > function_seed (API role은 기본값)."""
    if comp.function:
        return comp.function
    if comp.role == "api":
        return "api"
    if repository is not None:
        function = repository.function(comp.name)
        if function:
            return function
    seed = load_function_seed() if seed is None else seed
    low = base_of(comp.name).lower()
    for key in sorted(seed, key=len, reverse=True):
        if key in low:
            return seed[key]
    return None


def compatibility_usage(session, api: str, excipient: str) -> UsageEvidence:
    """Legacy session helper retained for admin and live integration tests."""
    rec = session.run(
        "MATCH (f:Formulation)-[:HAS_API|CONTAINS]->(a:Ingredient) "
        "WHERE toLower(a.canonical_name) CONTAINS $drug "
        "  AND coalesce(a.non_ingredient, false) = false "
        "MATCH (f)-[:CONTAINS]->(e:Ingredient) "
        "WHERE toLower(e.canonical_name) CONTAINS $exc "
        "  AND coalesce(e.non_ingredient, false) = false "
        "RETURN count(DISTINCT f) AS n, "
        "       collect(DISTINCT f.source_type)[..5] AS src",
        drug=api.lower(),
        exc=excipient.lower(),
    ).single()
    if not rec:
        return UsageEvidence(count=0, source_types=())
    return UsageEvidence(
        count=int(rec["n"]),
        source_types=tuple(rec["src"] or ()),
    )


def range_for_base(session, base: str) -> dict:
    """Legacy 비교용 canonical_base CONTAINS.pct 집계."""
    rec = session.run(
        """
        /* range_for_base */
        MATCH (f:Formulation)-[r:CONTAINS]->(i:Ingredient)
        WHERE i.canonical_base = $base AND r.pct IS NOT NULL
          AND coalesce(i.non_ingredient,false) = false
          AND coalesce(r.process_material,false) = false
        RETURN count(r) AS n, min(r.pct) AS lo, max(r.pct) AS hi, avg(r.pct) AS mean,
               percentileCont(r.pct,0.05) AS p5, percentileCont(r.pct,0.95) AS p95,
               percentileCont(r.pct,0.5) AS med
        """,
        base=base,
    ).single()
    return dict(rec) if rec else {"n": 0}


def identity_for_name(session, name: str) -> dict | None:
    """Return one approved target matched without using canonical_base."""

    rows = session.run(
        """
        /* identity_for_name */
        MATCH (i:Ingredient)-[:HAS_RESOLUTION]->(a:ResolutionAssertion)
              -[:RESOLVES_TO]->(target)
        WHERE a.status IN ['AUTO_SAFE', 'VERIFIED']
          AND (
            toLower(i.canonical_name) = toLower($name)
            OR toLower(coalesce(i.name, '')) = toLower($name)
            OR toLower(coalesce(i.normalized_key, '')) = toLower($name)
          )
        WITH DISTINCT
          CASE WHEN target:MaterialGrade THEN 'material_grade'
               WHEN target:Substance THEN 'substance' ELSE 'unknown' END AS target_kind,
          coalesce(target.material_id, target.substance_id) AS target_id,
          target.preferred_name AS preferred_name,
          coalesce(a.grade_unknown, false) AS grade_unknown,
          a.status AS status
        RETURN target_kind, target_id, preferred_name, grade_unknown, status
        ORDER BY target_kind, target_id
        """,
        name=name,
    ).data()
    if not rows:
        return None
    identities = {
        (str(row["target_kind"]), str(row["target_id"]))
        for row in rows
        if row.get("target_id")
    }
    if len(identities) != 1:
        return {
            "target_kind": None,
            "target_id": None,
            "preferred_name": None,
            "grade_unknown": True,
            "status": "CONFLICT",
            "target_count": len(identities),
        }
    row = dict(rows[0])
    row["target_count"] = 1
    return row


def range_for_resolution(session, target_id: str) -> dict:
    """Aggregate only an exact, approved MaterialGrade target."""

    rec = session.run(
        """
        /* range_for_resolution */
        MATCH (:Formulation)-[r:CONTAINS]->(i:Ingredient)
              -[:HAS_RESOLUTION]->(a:ResolutionAssertion)
              -[:RESOLVES_TO]->(g:MaterialGrade)
        WHERE g.material_id = $target_id
          AND a.status IN ['AUTO_SAFE', 'VERIFIED']
          AND a.grade_unknown = false
          AND r.pct IS NOT NULL
          AND coalesce(i.non_ingredient, false) = false
          AND coalesce(r.process_material, false) = false
        WITH DISTINCT r
        RETURN count(r) AS n, min(r.pct) AS lo, max(r.pct) AS hi,
               avg(r.pct) AS mean,
               percentileCont(r.pct,0.05) AS p5,
               percentileCont(r.pct,0.95) AS p95,
               percentileCont(r.pct,0.5) AS med
        """,
        target_id=target_id,
    ).single()
    return dict(rec) if rec else {"n": 0}


def range_for_name_dual(session, name: str) -> dict:
    """Calculate legacy and safe Resolution results without silent fallback."""

    legacy_base = base_of(name)
    legacy = range_for_base(session, legacy_base)
    identity = identity_for_name(session, name)
    resolution: dict
    eligible = False
    if identity is None:
        resolution = {"n": 0, "excluded_reason": "unresolved_identity"}
    elif identity.get("target_count") != 1 or identity.get("status") == "CONFLICT":
        resolution = {"n": 0, "excluded_reason": "conflicting_resolution"}
    elif identity.get("target_kind") != "material_grade":
        reason = "grade_unknown" if identity.get("grade_unknown") else "substance_not_grade"
        resolution = {"n": 0, "excluded_reason": reason}
    elif identity.get("grade_unknown"):
        resolution = {"n": 0, "excluded_reason": "grade_unknown"}
    else:
        resolution = range_for_resolution(session, str(identity["target_id"]))
        eligible = bool(resolution.get("n", 0))

    legacy_med = legacy.get("med")
    resolution_med = resolution.get("med")
    difference = {
        "n_delta": int(resolution.get("n", 0)) - int(legacy.get("n", 0)),
        "median_delta": (
            float(resolution_med) - float(legacy_med)
            if resolution_med is not None and legacy_med is not None
            else None
        ),
    }
    return {
        "name": name,
        "legacy_base": legacy_base,
        "legacy": legacy,
        "identity": identity,
        "resolution": resolution,
        "difference": difference,
        "eligible_for_generation": eligible,
    }


def aggregation_mode(explicit: str | None = None) -> str:
    """Return the staged aggregation mode; unsafe values fail closed."""

    mode = explicit or os.environ.get(
        "PHARMA_IDENTITY_AGGREGATION_MODE", "dual_legacy"
    )
    if mode not in {"legacy", "dual_legacy", "resolution"}:
        raise ValueError(f"unsupported identity aggregation mode: {mode}")
    return mode


def range_for_generation(session, name: str, *, mode: str | None = None) -> dict:
    """Staged numeric lookup used by gates/generation.

    ``dual_legacy`` calculates both paths but keeps legacy behavior until the
    coverage report passes. ``resolution`` never falls back for unresolved or
    grade-unknown inputs.
    """

    selected_mode = aggregation_mode(mode)
    if selected_mode == "legacy":
        result = dict(range_for_base(session, base_of(name)))
        result["aggregation_mode"] = "legacy"
        return result
    dual = range_for_name_dual(session, name)
    if selected_mode == "resolution":
        result = dict(dual["resolution"])
        result["aggregation_mode"] = "resolution"
        result["identity"] = dual["identity"]
        return result
    result = dict(dual["legacy"])
    result["aggregation_mode"] = "dual_legacy"
    result["dual_run"] = dual
    return result


def api_doses_for_name_resolution(session, name: str) -> list[str]:
    """Read API doses only through a VERIFIED UNII Substance."""

    identity = identity_for_name(session, name)
    if not identity or identity.get("target_count") != 1:
        return []
    if (
        identity.get("status") != "VERIFIED"
        or identity.get("target_kind") != "substance"
        or not str(identity.get("target_id") or "").startswith("unii:")
    ):
        return []
    result = session.run(
        """
        /* api_doses_for_resolution */
        MATCH (:Formulation)-[r:HAS_API]->(i:Ingredient)
              -[:HAS_RESOLUTION]->(a:ResolutionAssertion)
              -[:RESOLVES_TO]->(s:Substance)
        WHERE s.substance_id = $target_id
          AND a.status = 'VERIFIED'
          AND r.mg IS NOT NULL
          AND coalesce(i.non_ingredient, false) = false
        WITH DISTINCT r
        RETURN r.mg AS mg
        """,
        target_id=identity["target_id"],
    )
    return [str(value) for value in result.value() if value]


def function_pct_sum_range(session, func: str) -> dict:
    """기능(binder/disintegrant/lubricant)별 '배합당 %합' 분포. 게이트3 대리지표."""
    rec = session.run(
        """
        MATCH (f:Formulation)-[r:CONTAINS]->(i:Ingredient)-[:HAS_FUNCTION]->(fn:Function)
        WHERE r.pct IS NOT NULL AND fn.name = $func
          AND coalesce(i.non_ingredient,false) = false
        WITH f, sum(r.pct) AS s
        RETURN count(s) AS n, min(s) AS lo, max(s) AS hi, avg(s) AS mean,
               percentileCont(s,0.05) AS p5, percentileCont(s,0.95) AS p95
        """,
        func=func,
    ).single()
    return dict(rec) if rec else {"n": 0}


def function_of(session, comp, seed: dict[str, str] | None = None) -> str | None:
    """성분의 기능 해석: 명시 > KG HAS_FUNCTION(canonical_base) > 이름사전(function_seed)."""
    if comp.role == "api":
        return "api"
    if comp.function:
        return comp.function
    seed = load_function_seed() if seed is None else seed
    base = base_of(comp.name)
    if session is not None:
        rec = session.run(
            "MATCH (i:Ingredient)-[:HAS_FUNCTION]->(fn:Function) "
            "WHERE i.canonical_base = $base RETURN fn.name AS f, count(*) AS c "
            "ORDER BY c DESC LIMIT 1",
            base=base,
        ).single()
        if rec and rec["f"]:
            return rec["f"]
    # 이름사전 보조(긴 키 우선)
    low = base.lower()
    for key in sorted(seed, key=len, reverse=True):
        if key in low:
            return seed[key]
    return None

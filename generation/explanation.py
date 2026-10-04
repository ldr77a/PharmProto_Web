"""해설층 입력 — 후보 조성·출처·게이트·HPE6 근거·실사용 쌍을 LLM 에 넘길 JSON 으로 만든다.

LLM 은 이 입력을 읽고 해석만 한다(숫자 변경 금지). 입력에 없는 말은 basis=general 로 표시된다.
크기는 성분·근거 항목 수를 잘라 묶는다.
"""

from __future__ import annotations

from typing import Any

from generation.html_formatter import candidate_rows

_MAX_LIST = 6


def _clip(text: object, limit: int = 240) -> str:
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _evidence(evidence) -> dict[str, Any]:
    if evidence is None:
        return {}
    out: dict[str, Any] = {}
    if getattr(evidence, "monographs", ()):
        out["monographs"] = [
            {"name": m.name, "source": m.source_id, "pdf_page": m.pdf_start_page}
            for m in evidence.monographs[:2]
        ]
    if getattr(evidence, "use_ranges", ()):
        out["use_ranges"] = [
            {"function": u.function_name, "min_pct": u.min_pct, "max_pct": u.max_pct,
             "unit": u.unit, "dosage_form": u.dosage_form, "pdf_page": u.pdf_page}
            for u in evidence.use_ranges[:_MAX_LIST]
        ]
    if getattr(evidence, "incompatibilities", ()):
        out["incompatibilities"] = [
            {"target": i.target_name, "pdf_page": i.pdf_page} for i in evidence.incompatibilities[:8]
        ]
    if getattr(evidence, "stability", ()):
        out["stability"] = [
            {"statement": _clip(s.statement), "pdf_page": s.pdf_page} for s in evidence.stability[:2]
        ]
    if getattr(evidence, "properties", ()):
        out["properties"] = [
            {"name": p.property_name, "value": _clip(p.value_text, 160), "pdf_page": p.pdf_page}
            for p in evidence.properties[:_MAX_LIST]
        ]
    return out


def build_explanation_payload(spec, candidates, repository=None) -> dict[str, Any]:
    apis = [
        {"name": a.name, "dose_mg": getattr(a, "dose_mg", None)} for a in getattr(spec, "apis", [])
    ]
    request = {
        "apis": apis,
        "dosage_form": getattr(spec, "dosage_form", ""),
        "process": getattr(spec, "process", ""),
        "release_profile": getattr(spec, "release_profile", ""),
        "target_total_mg": getattr(spec, "target_total_mg", None),
        "profile_id": getattr(spec, "profile_id", ""),
        # 사용자가 고정한 분량 — 해설이 "왜 이 값인가"를 DB 가 아니라 사용자 지정으로 설명하게.
        "user_amounts": {
            name: {"mg": amount.mg, "pct": amount.pct}
            for name, amount in (getattr(spec, "user_amounts", None) or {}).items()
        },
    }
    usage_lookup = getattr(repository, "compatibility_usage", None)
    role_lookup = getattr(repository, "primary_role", None)
    out_candidates: list[dict[str, Any]] = []
    for cand in candidates:
        components = []
        for name, function, mg, pct, provenance, _green in candidate_rows(cand):
            row: dict[str, Any] = {
                "ingredient": name, "function": function, "mg": mg, "pct": pct,
                "provenance": provenance,
            }
            if callable(role_lookup) and function != "API":
                role = role_lookup(name)
                if role:
                    row["dictionary_primary_role"] = role
            if callable(usage_lookup) and function != "API":
                usage = [usage_lookup(api["name"], name) for api in apis]
                row["used_with_api_in_formulations"] = [
                    {"api": api["name"], "count": u.count, "sources": list(u.source_types)}
                    for api, u in zip(apis, usage, strict=False)
                ]
            components.append(row)
        gates = [
            {"gate": r.gate, "status": r.status, "reason": _clip(r.reason, 300),
             "details": [_clip(d, 200) for d in list(getattr(r, "details", []) or [])[:4]]}
            for r in cand.gate_out.get("results", [])
        ]
        evidence = {
            key: _evidence(value)
            for key, value in getattr(cand, "evidence_by_ingredient", {}).items()
        }
        evidence = {k: v for k, v in evidence.items() if v}
        out_candidates.append({
            "candidate_idx": cand.idx, "status": cand.status, "total_mg": cand.total_mg,
            "components": components, "gates": gates,
            "notes": [_clip(n, 200) for n in list(getattr(cand, "notes", []))[:10]],
            "hpe6_evidence": evidence,
        })
    return {
        "request": request,
        "candidates": out_candidates,
        "evidence_legend": {
            "KG 범위": "실제 배합(특허·승인 라벨) 집계 p5~p95, n=표본 수",
            "KG 역할별 범위": "같은 역할로 쓰인 배합만 집계",
            "HPE6∩KG": "Handbook of Pharmaceutical Excipients 6판 용도범위와 KG 범위의 교집합",
            "승인 라벨 용량 중앙값": "식약처·DailyMed 허가 라벨의 주성분 분량",
            "used_with_api_in_formulations": "이 API 와 같은 배합에 실제로 쓰인 횟수(출처별)",
        },
    }


__all__ = ["build_explanation_payload"]

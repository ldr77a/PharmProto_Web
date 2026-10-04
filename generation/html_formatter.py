"""후보 조성 → 웹 출력용 HTML 표. 성분명=영어, 기능·근거=한글, KG근거는 초록 강조.

table_formatter(markdown)와 같은 데이터를 HTML 로. 성분명은 이미 canonical(영문)이라 그대로,
role='api' 는 첫 글자만 대문자로 보기 좋게.
"""

from __future__ import annotations

import html
import re

_FUNC_KO = {"api": "API", "binder": "결합제", "disintegrant": "붕해제",
            "diluent": "희석제", "lubricant": "활택제", "glidant": "활택보조",
            "coating": "코팅", "film_forming_agent": "피막형성제",
            "plasticizer": "가소제", "opacifier": "불투명화제", "colorant": "착색제",
            "sweetener": "감미제", "flavoring_agent": "향미제",
            "taste_masking_agent": "맛차폐제", "wetting_agent": "습윤제",
            "solubilizer": "가용화제", "dissolution_enhancer": "용출개선제",
            "adsorbent": "흡착제", "anticaking_agent": "고결방지제",
            "stabilizer": "안정화제", "antioxidant": "항산화제",
            "preservative": "보존제", "buffer": "완충제",
            "acidifying_agent": "산성화제", "alkalizing_agent": "알칼리화제",
            "chelating_agent": "킬레이트제", "sustained_release_agent": "방출조절제",
            "granulation_aid": "과립화보조제", "moisture_control_agent": "수분조절제"}
_SRC_KO = {
    "user": ("사용자 지정", False), "hpe6": ("HPE6 용도범위", True),
    "hpe6+kg": ("HPE6∩KG 범위", True),
    "hpe6+kg_role": ("HPE6∩KG 역할별 범위", True),
    "kg": ("KG 범위", True),
    "kg_role": ("KG 역할별 범위", True),
    "standard": ("표준용량(사전)", False), "unknown": ("미상(지정 필요)", False),
    "function_default": ("기능 기본값(사전)", False),
    "filler(q.s.)": ("잔여 채움(q.s.→100%)", False),
}

_PROPERTY_PRIORITY = {
    "flowability": 0,
    "density": 1,
    "particle_size": 2,
    "moisture": 3,
    "solubility": 4,
    "melting_point": 5,
    "viscosity": 6,
    "ph": 7,
    "acidity_alkalinity": 8,
}


def _title_en(name: str) -> str:
    """성분명 영어 표기. 한 단어 소문자면 첫 글자 대문자, 이미 대문자·다단어면 유지."""
    return name[:1].upper() + name[1:] if name and name[0].islower() and " " not in name else (
        name[:1].upper() + name[1:] if name and name[0].islower() else name)


def _prov(cand, comp):
    if comp.role == "api":
        d = next((x for x in cand.doses if x.name == comp.name), None)
        if not d:
            return "-", False
        label, green = _SRC_KO.get(d.source, (d.source, False))
        return label + (f", n={d.n}" if d.n else ""), green
    a = next((x for x in cand.allocs if x.name == comp.name), None)
    if not a:
        return "-", False
    label, green = _SRC_KO.get(a.source, (a.source, False))
    return label + (f", n={a.n}" if a.n else ""), green


def candidate_rows(cand) -> list[tuple[str, str, float | None, float | None, str, bool]]:
    """후보 조성표의 화면·엑셀 공용 행 데이터."""
    rows = []
    for component in cand.components:
        provenance, green = _prov(cand, component)
        rows.append(
            (
                _title_en(component.name),
                _FUNC_KO.get(component.function or "", component.function or "-"),
                component.mg,
                component.pct,
                provenance,
                green,
            )
        )
    return rows


def _clip(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _page(value: int | None) -> str:
    return f"p.{value}" if value is not None else "page 미상"


def _evidence_html(cand) -> str:
    groups: list[str] = []
    for component in cand.components:
        evidence = cand.evidence_by_ingredient.get(component.name.casefold())
        if evidence is None:
            continue
        has_direct = any((
            evidence.monographs,
            evidence.use_ranges,
            evidence.properties,
            evidence.stability,
            evidence.incompatibilities,
        ))
        if not has_direct:
            continue

        lines: list[str] = []
        if evidence.monographs:
            monograph = evidence.monographs[0]
            pages = _page(monograph.pdf_start_page)
            if monograph.pdf_end_page not in (None, monograph.pdf_start_page):
                pages += f"–{monograph.pdf_end_page}"
            lines.append(
                f"모노그래프: {html.escape(monograph.name)} ({html.escape(pages)})"
            )
        if evidence.use_ranges:
            rendered_ranges = []
            for item in evidence.use_ranges[:2]:
                if item.min_pct is not None and item.max_pct is not None:
                    amount = f"{item.min_pct:g}–{item.max_pct:g}{item.unit}"
                else:
                    value = item.min_pct if item.min_pct is not None else item.max_pct
                    amount = f"{value:g}{item.unit}" if value is not None else item.unit
                rendered_ranges.append(
                    f"{item.function_name} {amount} ({_page(item.pdf_page)})"
                )
            lines.append("용도범위: " + html.escape(", ".join(rendered_ranges)))
        if evidence.incompatibilities:
            targets = ", ".join(
                item.target_name for item in evidence.incompatibilities[:8]
            )
            lines.append("부적합성 대상: " + html.escape(targets))
        if evidence.stability:
            item = evidence.stability[0]
            lines.append(
                "안정성: "
                + html.escape(_clip(item.statement, 260))
                + f" ({html.escape(_page(item.pdf_page))})"
            )
        if evidence.properties:
            properties = sorted(
                evidence.properties,
                key=lambda item: (
                    _PROPERTY_PRIORITY.get(item.property_name, 99),
                    item.property_name,
                    item.evidence_id,
                ),
            )[:4]
            values = "; ".join(
                f"{item.label or item.property_name}: {_clip(item.value_text, 140)}"
                for item in properties
            )
            lines.append("주요 물성: " + html.escape(values))

        rendered = "".join(f"<li>{line}</li>" for line in lines)
        groups.append(
            "<div class='evidence-group'><h5>"
            + html.escape(_title_en(component.name))
            + f"</h5><ul>{rendered}</ul></div>"
        )

    if not groups:
        return "<div class='evidence-empty'>HPE6 직접 근거 없음</div>"
    return (
        "<details class='evidence'><summary>HPE6 근거 보기</summary>"
        + "".join(groups)
        + "</details>"
    )


def candidate_html(cand) -> str:
    picks = ", ".join(f"{_FUNC_KO.get(f, f)}: {_title_en(n)}" for f, n in cand.pick.items())
    badge_cls = {"pass": "ok", "warning": "warn", "unresolved": "bad"}[cand.status]
    nwarn = len(cand.gate_out["warnings"])
    badge = {"pass": "✅ 배합 가능", "warning": f"⚠️ 조건부 후보 (주의 {nwarn}건)",
             "unresolved": "❌ 미해결 (하드 실패)"}[cand.status]

    rows = []
    for name, function, raw_mg, raw_pct, prov, green in candidate_rows(cand):
        mg = f"{raw_mg:.1f}" if raw_mg is not None else "-"
        pct = f"{raw_pct:.2f}" if raw_pct is not None else "-"
        rows.append(
            f"<tr><td class='ing'>{html.escape(name)}</td>"
            f"<td>{html.escape(function)}</td>"
            f"<td class='num'>{mg}</td><td class='num'>{pct}</td>"
            f"<td class='ev {'kg' if green else ''}'>{html.escape(prov)}</td></tr>")
    tot_mg = sum(c.mg for c in cand.components if c.mg) or 0
    tot_pct = sum(c.pct for c in cand.components if c.pct) or 0
    rows.append(
        f"<tr class='total'><td>합계</td><td></td><td class='num'>{tot_mg:.1f}</td>"
        f"<td class='num'>{tot_pct:.2f}</td><td>총중량 {cand.total_mg:.0f}mg</td></tr>")

    # 표시는 게이트 번호순(1→6). 실행 순서(4→5→6→1→3→2)와 무관하게 정렬.
    def _gnum(r):
        m = re.search(r"\d+", r.gate)
        return int(m.group()) if m else 99
    gate_syms = " ".join(
        f"<span class='g {r.status}'>{r.gate.split()[0]} {r.symbol.split()[0]}</span>"
        for r in sorted(cand.gate_out["results"], key=_gnum))
    warn_notes = "".join(
        f"<li>{html.escape(r.reason)}</li>"
        for r in cand.gate_out["results"] if r.status in ("warning", "fail"))
    selection_notes = "".join(f"<li>{html.escape(note)}</li>" for note in cand.notes)
    all_notes = warn_notes + selection_notes
    notes_html = f"<ul class='notes'>{all_notes}</ul>" if all_notes else ""
    evidence_html = _evidence_html(cand)

    return f"""
    <div class="card">
      <div class="card-head">
        <h3>조성 후보 {cand.idx}</h3>
        <div class="card-actions">
          <button class="download-xlsx secondary compact" type="button" data-candidate-index="{cand.idx}" disabled>엑셀 저장</button>
          <span class="badge {badge_cls}">{badge}</span>
        </div>
      </div>
      <div class="pick">{html.escape(picks)}</div>
      <table>
        <thead><tr><th>성분</th><th>기능</th><th>mg</th><th>%</th><th>근거</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      {evidence_html}
      <div class="gates">게이트 검증: {gate_syms}</div>
      {notes_html}
    </div>"""


def results_html(spec, candidates) -> str:
    if not candidates:
        return (
            "<div class='result-error'>유효한 조성 후보가 없습니다. "
            "총중량과 성분 함량 제약을 확인하세요.</div>"
        )
    apis = ", ".join(_title_en(a.name) for a in spec.apis)
    meta = (f"API: <b>{html.escape(apis)}</b> · 제형: {html.escape(spec.dosage_form)}"
            + (f" · 공정: {html.escape(spec.process)}" if spec.process else ""))
    if getattr(spec, "profile_id", ""):
        meta += f" · 프로필: {html.escape(spec.profile_id)}"
    cards = "".join(candidate_html(c) for c in candidates)
    return f"<div class='meta'>{meta} · 후보 {len(candidates)}개</div>{cards}"

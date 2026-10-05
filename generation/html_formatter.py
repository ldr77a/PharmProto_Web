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
    "user": ("사용자 지정", False), "user_adjusted": ("사용자 지정→잔여 조정", False),
    "hpe6": ("HPE6 용도범위", True),
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


def _source_key(cand, comp) -> str:
    """근거 라벨의 원래 source 키(클릭 설명 사전 data-help='src:<key>' 용)."""
    if comp.role == "api":
        d = next((x for x in cand.doses if x.name == comp.name), None)
        return d.source if d else ""
    a = next((x for x in cand.allocs if x.name == comp.name), None)
    return a.source if a else ""


def _help_button(key: str, css_class: str, label_html: str, title: str = "") -> str:
    """클릭하면 쉬운 말 설명이 뜨는 버튼(키보드 접근 가능). 설명 문장은 generation/help_text.py."""
    title_attr = f" title='{html.escape(title)}'" if title else ""
    return (
        f"<button type='button' class='{css_class}' data-help='{html.escape(key)}'{title_attr}>"
        f"{label_html}</button>"
    )


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


_KO_PARTICLES = ("은", "는", "이다", "이며", "이고", "이라면", "이라고", "이란", "이라", "이면", "인", "일", "임", "이", "가",
                 "을", "를", "의", "에서", "에게", "에", "으로", "로", "와", "과", "도", "라서", "였다", "입니다", "까지", "부터",
                 "보다", "처럼", "마다", "만")
_PARTICLE_GAP = re.compile(
    r"(?<=[A-Za-z0-9%)\]])\s+(?=(?:" + "|".join(_KO_PARTICLES) + r")(?=[\s,.;:!?)\]]|$))"
)
_STATUS_WORDS = {"pass": "통과", "warning": "경고", "fail": "실패", "unresolved": "미해결"}
_STATUS_RE = re.compile(r"(?<![A-Za-z_])(pass|warning|fail|unresolved)(?![A-Za-z_])")   # \b 는 한글을 단어로 봐서 못 끊는다


def tidy_ko(text: str) -> str:
    """LLM 문장의 표기 정리: 'status 는' → 'status는', '62.89% 를' → '62.89%를', 'pass 이다' → '통과이다'.

    모델이 영문 토큰 뒤 조사를 띄어 쓰는 습관을 화면에서 바로잡는다. 성분명·수치는 건드리지 않는다.
    """
    cleaned = _PARTICLE_GAP.sub("", text or "")
    return _STATUS_RE.sub(lambda m: _STATUS_WORDS[m.group(1)], cleaned)


def _basis_badge(basis: str) -> str:
    if basis == "evidence":
        return _help_button("basis:evidence", "basis ev", "근거", "입력된 DB·HPE6 근거를 인용한 문장")
    return _help_button(
        "basis:general", "basis gen", "일반 지식·검증 필요", "모델의 일반 제제학 지식. 사람이 확인해야 함"
    )


def _refs_html(refs) -> str:
    refs = [r for r in (refs or []) if str(r).strip()]
    if not refs:
        return ""
    return "<span class='refs'>" + html.escape(", ".join(str(r) for r in refs[:6])) + "</span>"


def _items_html(title: str, items) -> str:
    if not items:
        return ""
    lis = "".join(
        f"<li>{_basis_badge(item.basis)} {html.escape(tidy_ko(item.text))} {_refs_html(item.refs)}</li>"
        for item in items
    )
    return f"<div class='explain-section'><h5>{html.escape(title)}</h5><ul>{lis}</ul></div>"


def explanation_html(expl) -> str:
    """후보 하나의 해설. 문장마다 근거/일반지식 배지를 붙인다(숫자는 표의 것, 해설은 LLM)."""
    if expl is None:
        return ""
    parts = []
    if expl.summary:
        parts.append(f"<p class='explain-summary'>{html.escape(tidy_ko(expl.summary))}</p>")
    if expl.ingredient_notes:
        rows = "".join(
            "<tr>"
            f"<td class='ing'>{html.escape(note.ingredient)}</td>"
            f"<td>{_basis_badge(note.basis)} {html.escape(tidy_ko(note.rationale))} {_refs_html(note.refs)}"
            + (f"<div class='caution'>주의: {html.escape(tidy_ko(note.caution))}</div>" if note.caution else "")
            + "</td></tr>"
            for note in expl.ingredient_notes
        )
        parts.append(
            "<div class='explain-section'><h5>성분별 선택 이유</h5>"
            f"<table class='explain-table'><tbody>{rows}</tbody></table></div>"
        )
    parts.append(_items_html("위험 요소", expl.risks))
    parts.append(_items_html("공정 메모", expl.process_notes))
    parts.append(_items_html("실험으로 확인할 것", expl.verification_checklist))
    parts.append(_items_html("대안", expl.alternatives))
    body = "".join(parts)
    if not body:
        return ""
    return (
        "<details class='explain' open><summary>해설 (LLM · 숫자는 DB 근거, 문장마다 근거 여부 표시)</summary>"
        + body + "</details>"
    )


def followup_answer_html(question: str, items) -> str:
    """후속 질의응답 카드. 문장마다 근거/일반지식 배지(해설층과 같은 규칙, 숫자는 표의 것)."""
    lis = "".join(
        f"<li>{_basis_badge(item.basis)} {html.escape(item.text)} {_refs_html(item.refs)}</li>"
        for item in items
    )
    return (
        "<div class='card followup'>"
        f"<p class='followup-q'><span class='followup-label'>질문</span> {html.escape(question)}</p>"
        f"<ul class='followup-a'>{lis}</ul></div>"
    )


def followup_turn_html(question: str, changes, note: str = "") -> str:
    """요청을 고쳐 다시 생성했을 때의 기록 카드. 변경 목록은 서버가 두 요청을 비교해 만든다."""
    if changes:
        head = "요청을 수정해 다시 생성했습니다."
        body = "<ul class='followup-a'>" + "".join(f"<li>{html.escape(c)}</li>" for c in changes) + "</ul>"
    else:
        head = "변경할 내용이 없어 기존 결과를 유지합니다."
        body = ""
    note_html = f"<p class='followup-note'>{html.escape(note)}</p>" if note else ""
    return (
        "<div class='card followup refine'>"
        f"<p class='followup-q'><span class='followup-label'>질문</span> {html.escape(question)}</p>"
        f"<p class='followup-head'>{head}</p>{body}{note_html}</div>"
    )


def explanation_slot_html(candidate_idx: int) -> str:
    """해설이 아직 없는 후보의 자리. app.js 가 /api/explain 응답으로 채운다(후보 1은 자동, 나머지는 버튼)."""
    return (
        f"<div class='explain-slot' data-explain-index='{candidate_idx}'>"
        f"<button type='button' class='explain-btn secondary compact' data-explain-index='{candidate_idx}'>해설 보기</button>"
        "<span class='explain-status'></span></div>"
    )


def explanation_header_html(explanation) -> str:
    if explanation is None:
        return ""
    parts = [_items_html("API 프로파일", explanation.api_profile)]
    if explanation.disclaimer:
        parts.append(f"<p class='explain-disclaimer'>{html.escape(tidy_ko(explanation.disclaimer))}</p>")
    body = "".join(parts)
    return f"<div class='card explain-head'>{body}</div>" if body else ""


def candidate_html(cand, explanation=None) -> str:
    picks = ", ".join(f"{_FUNC_KO.get(f, f)}: {_title_en(n)}" for f, n in cand.pick.items())
    badge_cls = {"pass": "ok", "warning": "warn", "unresolved": "bad"}[cand.status]
    nwarn = len(cand.gate_out["warnings"])
    badge = {"pass": "게이트 통과", "warning": f"조건부 후보 (주의 {nwarn}건)",
             "unresolved": "미해결 (하드 실패)"}[cand.status]

    rows = []
    for component, (name, function, raw_mg, raw_pct, prov, green) in zip(
        cand.components, candidate_rows(cand), strict=True
    ):
        mg = f"{raw_mg:.1f}" if raw_mg is not None else "-"
        pct = f"{raw_pct:.2f}" if raw_pct is not None else "-"
        source_key = _source_key(cand, component)
        prov_html = (
            _help_button(f"src:{source_key}", "help-trigger", html.escape(prov))
            if source_key else html.escape(prov)
        )
        rows.append(
            f"<tr><td class='ing'>{html.escape(name)}</td>"
            f"<td>{html.escape(function)}</td>"
            f"<td class='num'>{mg}</td><td class='num'>{pct}</td>"
            f"<td class='ev {'kg' if green else ''}'>{prov_html}</td></tr>")
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
        _help_button(f"gate:{_gnum(r)}", f"g {r.status}", f"{r.gate.split()[0]} {r.symbol.split()[0]}")
        for r in sorted(cand.gate_out["results"], key=_gnum))
    warn_notes = "".join(
        f"<li>{html.escape(r.reason)}</li>"
        for r in cand.gate_out["results"] if r.status in ("warning", "fail"))
    selection_notes = "".join(f"<li>{html.escape(note)}</li>" for note in cand.notes)
    all_notes = warn_notes + selection_notes
    notes_html = f"<ul class='notes'>{all_notes}</ul>" if all_notes else ""
    evidence_html = _evidence_html(cand)
    explain_html = explanation_html(explanation) or explanation_slot_html(cand.idx)

    # 카드는 접이식: 머리줄(제목·상태·핵심 부형제·총중량)을 누르면 표·근거·해설이 접히고 펼쳐진다.
    # 인쇄 때는 app.js 의 beforeprint 가 접힌 것을 모두 펼친다.
    return f"""
    <details class="card candidate" id="candidate-{cand.idx}" open>
      <summary class="candidate-summary">
        <h3>조성 후보 {cand.idx}</h3>
        {_help_button(f"status:{cand.status}", f"badge {badge_cls}", html.escape(badge))}
        <span class="strip-picks">{html.escape(picks)}</span>
        <span class="strip-total">{cand.total_mg:.0f} mg</span>
      </summary>
      <div class="candidate-body">
        <div class="card-actions">
          <button class="download-xlsx secondary compact" type="button" data-candidate-index="{cand.idx}" disabled>엑셀 저장</button>
        </div>
        <table>
          <thead><tr><th>성분</th><th>기능</th><th>mg</th><th>%</th><th>근거</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        {evidence_html}
        <div class="gates">게이트 검증: {gate_syms}</div>
        {notes_html}
        {explain_html}
      </div>
    </details>"""


def _amount_text(name: str, amount) -> str:
    if getattr(amount, "pct", None) is not None:
        return f"{_title_en(name)} {amount.pct:g}%"
    return f"{_title_en(name)} {amount.mg:g} mg"


def _api_summary(spec, candidates) -> str:
    """API 와 확정 용량(출처 포함). 용량은 첫 후보의 DoseResult 에서 읽는다(KG·표준사전 폴백 반영)."""
    doses = list(getattr(candidates[0], "doses", None) or []) if candidates else []
    parts = []
    for api in getattr(spec, "apis", None) or []:
        dose = next((d for d in doses if d.name.casefold() == api.name.casefold()), None)
        if dose is not None and dose.mg:
            parts.append(f"{_title_en(api.name)} {dose.mg:g} mg ({dose.note})")
        elif getattr(api, "dose_mg", None):
            parts.append(f"{_title_en(api.name)} {api.dose_mg:g} mg (사용자 지정)")
        else:
            parts.append(f"{_title_en(api.name)} (용량 미상)")
    return ", ".join(parts) or "-"


def request_summary_html(spec, candidates) -> str:
    """LLM 이 읽어 낸 요청을 그대로 보여 준다 — 잘못 읽힌 성분·분량을 사용자가 바로 알아채게."""
    items: list[tuple[str, str, bool]] = [("주성분", _api_summary(spec, candidates), False)]
    items.append(("제형", getattr(spec, "dosage_form", "") or "-", False))
    if getattr(spec, "process", ""):
        items.append(("공정", spec.process, False))
    if getattr(spec, "release_profile", ""):
        items.append(("방출", spec.release_profile, False))
    total = getattr(spec, "target_total_mg", None)
    items.append(("총중량", f"{total:g} mg (사용자 지정)" if total else "자동 산출(API 함량 기준)", False))
    items.append(("후보 수", str(getattr(spec, "n_candidates", None) or len(candidates)), False))

    sources = getattr(spec, "selection_sources", None) or {}
    choices = getattr(spec, "excipient_choices", None) or {}
    named = [
        f"{_FUNC_KO.get(role, role)}: {', '.join(_title_en(n) for n in names)}"
        for role, names in choices.items()
        if names and sources.get(role, "user") == "user"
    ]
    if named:
        items.append(("지정 성분", " · ".join(named), False))

    amounts = getattr(spec, "user_amounts", None) or {}
    if amounts:
        reflected = {
            a.name.casefold()
            for c in candidates
            for a in getattr(c, "allocs", None) or []
            if a.source in ("user", "user_adjusted")
        }
        applied = [_amount_text(k, v) for k, v in amounts.items() if k in reflected]
        missing = [_amount_text(k, v) for k, v in amounts.items() if k not in reflected]
        if applied:
            items.append(("지정 분량", ", ".join(applied), False))
        if missing:
            items.append((
                "미반영 분량",
                ", ".join(missing) + " — 어느 후보에도 들어가지 않은 성분입니다. "
                "역할(예: 붕해제)을 함께 적어 주세요.",
                True,
            ))

    rows = "".join(
        f"<dt>{html.escape(label)}</dt><dd{' class=\"missing\"' if warn else ''}>{html.escape(value)}</dd>"
        for label, value, warn in items
    )
    return f"<div class='card request-summary'><h4>요청 해석</h4><dl>{rows}</dl></div>"


RESULT_FRAGMENT_START = "<!-- pharma:result -->"
RESULT_FRAGMENT_END = "<!-- /pharma:result -->"


def standalone_result_html(fragment: str, *, css_text: str, title: str, turns=()) -> str:
    """저장용 독립 HTML — CSS 를 안에 넣어 파일만 열어도 서식이 보인다(앱이 서빙하지 않으므로 CSP 무관).

    결과 조각은 마커로 감싸 두어 앱이 다시 열 때 그 부분만 잘라 쓴다. 후속 질의응답은 조각 뒤에 붙인다.
    """
    log = "".join(str(turn.get("html") or "") for turn in turns if isinstance(turn, dict))
    log_html = f"<section class='followup-log'><h2>후속 질의응답</h2>{log}</section>" if log else ""
    return (
        "<!doctype html>\n<html lang='ko' data-theme='light'>\n<head>\n<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        f"<title>{html.escape(title)}</title>\n"
        f"<style>\n{css_text}\n.print-only {{ display: block; }}\n"
        "main { width: min(960px, calc(100% - 32px)); margin: 24px auto 48px; }\n"
        ".followup-log h2 { font-size: 18px; margin: 24px 0 8px; }\n</style>\n</head>\n<body>\n<main>\n"
        f"{RESULT_FRAGMENT_START}{fragment}{RESULT_FRAGMENT_END}\n{log_html}\n"
        "<p class='notice review-notice'>연구 검토용 시제품입니다. 생성 결과는 반드시 사람이 검토해야 합니다.</p>\n"
        "</main>\n</body>\n</html>\n"
    )


def print_header_html(meta) -> str:
    """인쇄물·저장본 머리글(화면에서는 숨김): 요청, 생성 시각, DB 스냅샷, 모델, 면책."""
    if not meta:
        return ""
    rows = [
        (label, meta.get(key))
        for key, label in (("question", "요청"), ("generated_at", "생성 시각"),
                           ("snapshot_id", "DB 스냅샷"), ("model", "모델"))
        if meta.get(key)
    ]
    dl = "".join(f"<dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd>" for k, v in rows)
    return (
        "<header class='print-header print-only'>"
        "<p class='eyebrow'>PHARMA PROTO · LOCAL RESEARCH TOOL</p>"
        "<h2>신약 배합 생성기 결과</h2>"
        f"<dl>{dl}</dl>"
        "<p class='print-disclaimer'>연구 검토용 시제품의 출력입니다. 조성 수치는 지식 데이터베이스 근거로 "
        "계산되었고 해설은 LLM 이 작성했습니다. 최종 처방·제조 판정이 아니며 반드시 사람이 검토해야 합니다.</p>"
        "</header>"
    )


def results_html(spec, candidates, explanation=None, explanation_error: str | None = None,
                 meta=None) -> str:
    if not candidates:
        hint = "총중량과 성분 함량 제약을 확인하세요."
        if getattr(spec, "user_amounts", None) or getattr(spec, "target_total_mg", None):
            hint = ("지정한 총중량·분량으로는 희석제 잔여가 남지 않습니다. "
                    "총중량을 늘리거나 지정 분량을 줄여 다시 요청하세요.")
        return f"<div class='result-error'>유효한 조성 후보가 없습니다. {hint}</div>"
    apis = ", ".join(_title_en(a.name) for a in spec.apis)
    meta_line = (f"API: <b>{html.escape(apis)}</b> · 제형: {html.escape(spec.dosage_form)}"
                 + (f" · 공정: {html.escape(spec.process)}" if spec.process else ""))
    if getattr(spec, "profile_id", ""):
        meta_line += f" · 프로필: {html.escape(spec.profile_id)}"
    cards = "".join(
        candidate_html(c, explanation.for_candidate(c.idx) if explanation is not None else None)
        for c in candidates
    )
    notice = ""
    if explanation_error:
        notice = (
            "<div class='result-error'>해설 생성 실패 ("
            + html.escape(explanation_error)
            + "). 아래 표는 DB 근거만으로 생성되었습니다.</div>"
        )
    return (
        print_header_html(meta)
        + f"<div class='meta'>{meta_line} · 후보 {len(candidates)}개</div>"
        + request_summary_html(spec, candidates)
        + notice
        + f"<div id='explain-head-slot'>{explanation_header_html(explanation)}</div>"
        + cards
    )

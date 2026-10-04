"""Task A — 입력 파싱. 자연어 명령 → 구조화 스펙(FormulationSpec).

성분명은 한글→영문 사전 + canonical_base 로 정규화(KG 집계와 정렬). LLM 파싱은 선택
(parse_command_llm) — 없으면 FormulationSpec 을 직접 구성해 쓴다(결정적·테스트 가능).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class APISpec:
    name: str
    dose_mg: float | None = None


@dataclass(frozen=True)
class AmountSpec:
    """사용자가 적은 성분별 분량. 둘 다 있으면 pct 를 쓴다(총중량 없이도 확정되므로)."""

    mg: float | None = None
    pct: float | None = None


@dataclass
class FormulationSpec:
    apis: list[APISpec]
    dosage_form: str = "tablet"
    # 기능(function) → 후보 성분명 리스트. 예: {"binder":["hydroxypropyl cellulose","povidone"], ...}
    excipient_choices: dict[str, list[str]] = field(default_factory=dict)
    process: str = ""
    release_profile: str = ""
    n_candidates: int = 3
    target_total_mg: float | None = None
    profile_id: str = ""
    selection_sources: dict[str, str] = field(default_factory=dict)
    # 정규화된 성분명(casefold) → 사용자 지정 분량. 배분 때 후보별 역할 키로 옮겨 쓴다.
    user_amounts: dict[str, AmountSpec] = field(default_factory=dict)


# 한글/상표 → 영문 canonical (canonical_base 가 다시 통합). 최소 사전(확장 가능).
KO_EN: dict[str, str] = {
    "라베프라졸": "rabeprazole", "산화마그네슘": "magnesium oxide",
    "만니톨": "mannitol", "디만니톨": "mannitol", "d-만니톨": "mannitol", "d-mannitol": "mannitol",
    "유당": "lactose", "락토스": "lactose", "젖당": "lactose",
    "히프로멜로스": "hypromellose", "히드록시프로필메틸셀룰로스": "hypromellose",
    "히드록시프로필셀룰로스": "hydroxypropyl cellulose", "hpc": "hydroxypropyl cellulose",
    "l-hpc": "low-substituted hydroxypropyl cellulose",
    "저치환도히드록시프로필셀룰로스": "low-substituted hydroxypropyl cellulose",
    "포비돈": "povidone", "pvp-k30": "povidone", "pvp k30": "povidone", "pvpk30": "povidone",
    "전분글리콜산나트륨": "sodium starch glycolate", "ssg": "sodium starch glycolate",
    "크로스카르멜로스나트륨": "croscarmellose sodium",
    "스테아릴푸마르산나트륨": "sodium stearyl fumarate",
    "스테아르산마그네슘": "magnesium stearate",
    "미결정셀룰로스": "microcrystalline cellulose", "mcc": "microcrystalline cellulose",
    "탈크": "talc", "이산화티타늄": "titanium dioxide",
}


def _requested_candidate_count(text: str) -> int:
    patterns = (
        r"(\d+)\s*(?:개|가지)(?:의)?\s*(?:조성|배합)?\s*(?:후보|조합)",
        r"(?:조성|배합)?\s*(?:후보|조합)\s*(\d+)\s*개",
        r"(\d+)\s*(?:candidates?|formulations?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return max(1, min(int(match.group(1)), 5))
    return 3


def normalize_ingredient(name: str) -> str:
    """성분명 → 영문 canonical_base(정제 규칙 재사용). 한글은 사전 우선."""
    from cleaning.canonical_base import classify_base  # type: ignore[import-not-found]
    key = name.strip().lower()
    en = KO_EN.get(key, name.strip())
    return classify_base(en).canonical_base


def build_spec(apis, excipients: dict[str, list[str]], *, dosage_form="tablet",
               process="", release_profile="", n_candidates=3, target_total_mg=None,
               amounts=None) -> FormulationSpec:
    """구조화 입력으로 스펙 구성(성분명 정규화 포함). 테스트·데모용 결정적 경로.

    amounts: {성분명: (mg, pct) | AmountSpec}. 성분명은 역할 리스트와 같은 규칙으로 정규화되므로
    같은 성분이면 같은 키가 된다. API 이름과 겹치는 mg 는 그 API 의 용량이 비어 있을 때 채운다.
    """
    api_specs = [a if isinstance(a, APISpec) else APISpec(normalize_ingredient(a[0]),
                 a[1] if len(a) > 1 else None) if isinstance(a, tuple)
                 else APISpec(normalize_ingredient(a)) for a in apis]
    norm_ex = {fn: [normalize_ingredient(x) for x in xs] for fn, xs in excipients.items()}
    user_amounts: dict[str, AmountSpec] = {}
    for raw_name, value in (amounts or {}).items():
        amount = value if isinstance(value, AmountSpec) else AmountSpec(*value)
        if amount.mg is None and amount.pct is None:
            continue
        user_amounts[normalize_ingredient(raw_name).casefold()] = amount
    for api in api_specs:
        amount = user_amounts.get(api.name.casefold())
        if amount is not None and amount.mg is not None:
            if api.dose_mg is None:
                api.dose_mg = amount.mg
            user_amounts.pop(api.name.casefold())
    return FormulationSpec(apis=api_specs, dosage_form=dosage_form,
                           excipient_choices=norm_ex, process=process,
                           release_profile=release_profile,
                           n_candidates=n_candidates, target_total_mg=target_total_mg,
                           user_amounts=user_amounts)


def parse_command_llm(text: str) -> FormulationSpec:
    """Legacy helper retained outside the release app; uses the common service."""
    import os

    from pharma_proto.llm.service import LLMService

    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY is not configured")
    return LLMService().parse("gemini", "normal", key, text)

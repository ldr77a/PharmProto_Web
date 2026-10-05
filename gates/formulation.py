"""게이트 공용 타입 — 배합 입력과 게이트 결과.

배합(FormulationInput)을 5개 게이트가 공유한다. 각 게이트는 GateResult 를 돌려주고,
pipeline 이 종합한다. provenance(I5)·hard/soft 구분을 결과에 담는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Component:
    name: str                       # canonical_name(자유 입력 가능)
    role: str = "excipient"         # api | excipient
    mg: float | None = None
    pct: float | None = None
    function: str | None = None      # 명시 시 우선(없으면 KG/사전으로 해석)
    process_material: bool = False   # water/acetone 등 공정용매(범위·총합서 제외)
    filler: bool = False             # 잔여 채움(q.s.) 희석제: % 가 100−API−나머지로 정해지는 값(게이트1 은 API 함량 구간으로 심사)


@dataclass
class FormulationInput:
    components: list[Component]
    target_total_mg: float | None = None
    dosage_form: str = "tablet"
    profile_id: str = ""
    required_functions: tuple[str, ...] = ()

    def apis(self) -> list[Component]:
        return [c for c in self.components if c.role == "api"]

    def excipients(self) -> list[Component]:
        return [c for c in self.components if c.role != "api"]


@dataclass
class GateResult:
    gate: str                       # "게이트1 사용량 범위" 등
    status: str                     # pass | fail | warning | skip
    reason: str
    provenance: str = ""            # 근거(KG 집계/규칙 출처)
    hard: bool = True               # hard(fail=차단) vs soft(warning=조건부)
    details: list = field(default_factory=list)

    @property
    def symbol(self) -> str:
        return {"pass": "✅ pass", "fail": "❌ fail",
                "warning": "⚠️ warning", "skip": "➖ skip"}[self.status]

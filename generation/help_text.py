"""화면의 '이게 무슨 뜻이지?'에 답하는 쉬운 말 사전 — 근거 꼬리표, 게이트, 해설 배지, 후보 상태.

사이드바(Jinja)와 결과 카드의 클릭 설명(JS 팝오버)이 같은 문장을 쓰도록 한곳에 둔다.
IT·제제학 비전문가도 읽을 수 있게 쓴다. 숫자나 판정은 여기서 바꾸지 않는다.
키 규칙: 게이트 'gate:<번호>', 근거 'src:<source>', 해설 배지 'basis:<evidence|general>', 상태 'status:<status>'.
"""

from __future__ import annotations

GATES: tuple[dict[str, str], ...] = (
    {
        "key": "gate:1",
        "title": "게이트1 사용량 범위",
        "text": "각 부형제의 함량이 KG DB 내 실제 배합 데이터의 일반적인 사용범위(p5~p95)에 포함되는지 확인합니다. "
                "쉽게 말해, 실제 제품들에서 이 성분이 보통 쓰인 비율(하위 5%~상위 95%)과 비교해 너무 많거나 적으면 알려 줍니다.",
    },
    {
        "key": "gate:2",
        "title": "게이트2 제조성 대리지표",
        "text": "결합제 존재 여부 및 붕해제·활택제 등의 비율을 이용해 제조 가능성을 간접적으로 확인합니다. "
                "직접 실험한 값이 아니라 경험 규칙으로 보는 '대리지표'라서 막지 않고 주의로만 표시합니다.",
    },
    {
        "key": "gate:3",
        "title": "게이트3 총량 제약",
        "text": "전체 성분의 중량 합이 목표 총중량을 넘지 않는지 검증합니다. 정제 한 알의 무게가 목표보다 커지지 않았는지 보는 것입니다.",
    },
    {
        "key": "gate:4",
        "title": "게이트4 조성 합계",
        "text": "공정 중 제거되는 성분을 제외한 조성비 합계가 100±0.5%인지 확인합니다. 비율을 모두 더하면 100%가 되어야 정상입니다.",
    },
    {
        "key": "gate:5",
        "title": "게이트5 필수 기능 구성",
        "text": "제형 제조에 필요한 기능이 모두 포함됐는지 확인합니다. 예를 들어 정제에는 보통 희석제·결합제·붕해제·활택제가 필요합니다.",
    },
)

# 근거 꼬리표(html_formatter._SRC_KO 의 키와 같아야 한다 — tests/test_help_text.py 가 확인)
SOURCES: dict[str, dict[str, str]] = {
    "user": {
        "title": "사용자 지정",
        "text": "질문에 적은 값을 그대로 썼습니다. 데이터베이스의 통상 범위와 다를 수 있으니 게이트1 결과를 함께 보세요.",
    },
    "user_adjusted": {
        "title": "사용자 지정→잔여 조정",
        "text": "희석제는 나머지를 채우는 성분이라, 지정한 값 대신 총중량에 맞춘 잔여량을 썼습니다. 차이는 카드 아래 노트에 적혀 있습니다.",
    },
    "hpe6": {
        "title": "HPE6 용도범위",
        "text": "Handbook of Pharmaceutical Excipients 6판 모노그래프에 적힌, 이 역할로 쓸 때의 통상 사용 범위 가운데값입니다.",
    },
    "hpe6+kg": {
        "title": "HPE6∩KG 범위",
        "text": "HPE6 의 용도범위와 데이터베이스의 실제 배합 범위가 겹치는 구간의 가운데값입니다. 두 출처가 모두 뒷받침하는 값입니다.",
    },
    "hpe6+kg_role": {
        "title": "HPE6∩KG 역할별 범위",
        "text": "HPE6 용도범위와, 같은 역할로 쓰인 실제 배합만 모은 데이터베이스 범위가 겹치는 구간의 가운데값입니다.",
    },
    "kg": {
        "title": "KG 범위",
        "text": "우리 데이터베이스(특허·승인 라벨의 실제 배합)에서 이 성분이 쓰인 비율의 중앙값입니다. n 은 참고한 배합 수입니다.",
    },
    "kg_role": {
        "title": "KG 역할별 범위",
        "text": "우리 데이터베이스에서 이 성분이 같은 역할(예: 붕해제)로 쓰인 배합만 모아 낸 비율의 중앙값입니다. n 은 참고한 배합 수입니다.",
    },
    "standard": {
        "title": "표준용량(사전)",
        "text": "데이터베이스에 용량 근거가 없어 앱에 내장된 표준 용량 사전의 값을 썼습니다. 질문에 용량을 적으면 그 값이 우선합니다.",
    },
    "unknown": {
        "title": "미상(지정 필요)",
        "text": "용량 근거를 찾지 못했습니다. 질문에 용량(mg)을 직접 적어 주세요.",
    },
    "function_default": {
        "title": "기능 기본값(사전)",
        "text": "데이터베이스에 이 성분의 비율 근거가 없어 역할별 통상 범위의 가운데값을 썼습니다. 근거가 약하니 검토가 필요합니다.",
    },
    "filler(q.s.)": {
        "title": "잔여 채움(q.s.→100%)",
        "text": "희석제는 다른 성분을 모두 정한 뒤 남는 양으로 채워 합계가 100%가 되게 합니다(q.s., 적량).",
    },
}

BASIS: dict[str, dict[str, str]] = {
    "basis:evidence": {
        "title": "근거",
        "text": "입력된 데이터베이스·HPE6 근거를 인용한 문장입니다. 뒤에 붙은 꼬리표(예: KG 역할별 범위 n=1102)가 출처입니다.",
    },
    "basis:general": {
        "title": "일반 지식·검증 필요",
        "text": "AI 모델의 일반 제제학 지식으로 쓴 문장입니다. 이 프로그램의 데이터베이스가 뒷받침하지 않으므로 사람이 확인해야 합니다.",
    },
}

STATUS: dict[str, dict[str, str]] = {
    "status:pass": {
        "title": "게이트 통과",
        "text": "다섯 게이트에서 막힘(하드 실패)과 주의가 없습니다. 최종 제조 가능 판정이 아니라 검토의 출발점입니다.",
    },
    "status:warning": {
        "title": "조건부 후보",
        "text": "막힘은 없지만 주의 항목이 있습니다. 카드 아래 노트와 게이트 칩을 확인한 뒤 쓰세요.",
    },
    "status:unresolved": {
        "title": "미해결",
        "text": "하드 실패가 남아 총중량을 조정해도 풀리지 않았습니다. 성분이나 분량을 바꿔 다시 요청하세요.",
    },
}


def help_entries() -> dict[str, dict[str, str]]:
    """화면에 내려보낼 평면 사전 {key: {title, text}} — JS 팝오버가 data-help 키로 찾는다."""
    entries = {gate["key"]: {"title": gate["title"], "text": gate["text"]} for gate in GATES}
    entries.update({f"src:{key}": dict(value) for key, value in SOURCES.items()})
    entries.update({key: dict(value) for key, value in BASIS.items()})
    entries.update({key: dict(value) for key, value in STATUS.items()})
    return entries


__all__ = ["BASIS", "GATES", "SOURCES", "STATUS", "help_entries"]

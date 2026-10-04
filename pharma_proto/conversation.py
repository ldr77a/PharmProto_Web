"""후속 질문을 위한 대화 상태 — 프로세스 메모리에만 둔다(키 저장소와 같은 수명, 파일에 남지 않음).

요청의 진실은 ParsedRequest 다. run_generation 은 spec 을 제자리에서 바꾸므로 재생성은 언제나
parsed_request.to_domain() 으로 새 spec 을 만들어 돌린다(결정적 → 같은 요청이면 같은 표).
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MAX_TURNS = 10


@dataclass
class Conversation:
    conversation_id: str
    created: datetime
    provider: str
    tier: str
    question: str
    parsed_request: Any            # ParsedRequest | None (구형 가짜 서비스는 None → 후속 질문 불가)
    spec: Any                      # run_generation 뒤의 FormulationSpec(해설 payload 용, 재생성에는 안 씀)
    candidates: list
    explanation: Any
    explanation_error: str | None
    html: str
    downloads: list[dict]
    turns: list[dict] = field(default_factory=list)   # {"role": user|assistant, "kind": question|answer|refine, "text"}
    result_id: str | None = None                      # 저장본과 연결돼 있으면 그 id(저장 뒤 요청이 바뀌면 None)

    def add_turn(self, role: str, kind: str, text: str) -> None:
        self.turns.append({"role": role, "kind": kind, "text": text})
        del self.turns[:-MAX_TURNS]


class ConversationStore:
    """최근 대화 몇 개를 LRU 로 보관. 로그아웃·종료 때 비운다."""

    def __init__(self, *, max_entries: int = 20) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._entries: OrderedDict[str, Conversation] = OrderedDict()
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def create(self, **fields: Any) -> Conversation:
        conversation = Conversation(
            conversation_id=uuid.uuid4().hex,
            created=datetime.now(UTC),
            **fields,
        )
        with self._lock:
            self._entries[conversation.conversation_id] = conversation
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return conversation

    def get(self, conversation_id: str) -> Conversation | None:
        with self._lock:
            conversation = self._entries.get(conversation_id)
            if conversation is not None:
                self._entries.move_to_end(conversation_id)
            return conversation

    def replace(self, conversation: Conversation) -> None:
        with self._lock:
            self._entries[conversation.conversation_id] = conversation
            self._entries.move_to_end(conversation.conversation_id)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


__all__ = ["MAX_TURNS", "Conversation", "ConversationStore"]

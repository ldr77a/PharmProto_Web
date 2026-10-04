from __future__ import annotations

from pharma_proto.conversation import MAX_TURNS, ConversationStore


def _fields(**overrides):
    base = {
        "provider": "openai", "tier": "normal", "question": "질문",
        "parsed_request": None, "spec": None, "candidates": [],
        "explanation": None, "explanation_error": None, "html": "", "downloads": [],
    }
    base.update(overrides)
    return base


def test_store_creates_unique_ids_and_evicts_oldest_beyond_bound() -> None:
    store = ConversationStore(max_entries=2)

    first = store.create(**_fields())
    second = store.create(**_fields())
    third = store.create(**_fields())

    ids = {first.conversation_id, second.conversation_id, third.conversation_id}
    assert len(ids) == 3 and all(len(value) == 32 for value in ids)
    assert store.get(first.conversation_id) is None
    assert store.get(second.conversation_id) is second
    assert store.get(third.conversation_id) is third
    assert len(store) == 2


def test_recently_used_conversation_survives_eviction() -> None:
    store = ConversationStore(max_entries=2)
    first = store.create(**_fields())
    store.create(**_fields())

    assert store.get(first.conversation_id) is first      # 사용 → 최신으로
    store.create(**_fields())

    assert store.get(first.conversation_id) is first


def test_store_get_unknown_returns_none_and_clear_empties() -> None:
    store = ConversationStore()
    conversation = store.create(**_fields())

    assert store.get("f" * 32) is None
    store.clear()

    assert store.get(conversation.conversation_id) is None
    assert len(store) == 0


def test_turns_are_bounded() -> None:
    conversation = ConversationStore().create(**_fields())

    for index in range(MAX_TURNS + 5):
        conversation.add_turn("user", "question", str(index))

    assert len(conversation.turns) == MAX_TURNS
    assert conversation.turns[-1] == {"role": "user", "kind": "question", "text": str(MAX_TURNS + 4)}

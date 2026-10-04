import pytest

from pharma_proto.llm.memory_keys import MemoryKeyStore


def test_memory_key_store_retains_only_process_local_values():
    store = MemoryKeyStore()
    marker = "sk-test-do-not-persist-123456789"

    store.set("openai", marker)

    assert store.get("openai") == marker
    assert store.configured("openai") is True
    assert marker not in repr(store)
    assert marker not in str(store)
    store.clear()
    assert store.get("openai") is None


def test_memory_key_store_rejects_unknown_provider_and_blank_key():
    store = MemoryKeyStore()
    with pytest.raises(ValueError):
        store.set("unknown", "secret")
    with pytest.raises(ValueError):
        store.set("openai", "   ")

"""피드백 4번 — 화면 색 선택값은 브라우저가 아니라 서버의 preferences.json 에(비밀 아닌 허용 키만)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pharma_proto.llm.memory_keys import MemoryKeyStore
from pharma_proto.preferences import PreferenceStore
from tests.product.snapshot_fixtures import write_test_snapshot


def test_store_defaults_when_file_is_missing_or_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    store = PreferenceStore(path)

    assert store.load() == {"theme": "light"}
    path.write_text("{not json", encoding="utf-8")
    assert store.load() == {"theme": "light"}
    path.write_text("[1, 2]", encoding="utf-8")
    assert store.load() == {"theme": "light"}


def test_store_updates_only_allowed_keys_and_values(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "preferences.json"
    store = PreferenceStore(path)

    assert store.update({"theme": "dark"}) == {"theme": "dark"}
    assert json.loads(path.read_text(encoding="utf-8")) == {"theme": "dark"}
    assert not path.with_suffix(".json.tmp").exists()

    for bad in ({"theme": "neon"}, {"api_key": "x"}, {"token": "x"}, {"font": "big"}, {"theme": None}):
        with pytest.raises(ValueError):
            store.update(bad)
    assert store.load() == {"theme": "dark"}


def test_store_drops_unknown_or_secret_shaped_keys_from_file(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"theme": "light", "token": "abc", "font": 1}), encoding="utf-8")

    assert PreferenceStore(path).load() == {"theme": "light"}


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    database, manifest = write_test_snapshot(tmp_path / "release")
    from pharma_proto.app import create_app

    return create_app({"SNAPSHOT_PATH": database, "MANIFEST_PATH": manifest, "KEY_STORE": MemoryKeyStore()})


def test_preferences_round_trip_and_first_paint_theme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(tmp_path, monkeypatch).test_client()

    assert client.get("/api/preferences").get_json() == {"theme": "light"}      # 기본은 밝은 화면
    first = client.get("/").get_data(as_text=True)
    assert 'data-theme="light"' in first and 'aria-label="어두운 화면으로 전환"' in first

    put = client.put("/api/preferences", json={"theme": "dark"})

    assert (put.status_code, put.get_json()) == (200, {"theme": "dark"})
    page = client.get("/").get_data(as_text=True)
    assert 'data-theme="dark"' in page and 'aria-label="밝은 화면으로 전환"' in page and ">인쇄<" in page
    saved = tmp_path / "local" / "PharmaProto" / "preferences.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_preferences_reject_bad_values_and_extra_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _app(tmp_path, monkeypatch).test_client()

    neon = client.put("/api/preferences", json={"theme": "neon"})
    extra = client.put("/api/preferences", json={"theme": "dark", "api_key": "x"})

    assert (neon.status_code, neon.get_json()) == (400, {"error": "REQUEST-001"})
    assert (extra.status_code, extra.get_json()) == (400, {"error": "REQUEST-001"})
    assert client.get("/api/preferences").get_json() == {"theme": "light"}

"""이름 오타 수정(Phrama → Pharma, 2026-10-05) 뒤에도 옛 `PhramaProto` 폴더의 사용자 데이터를 이어 쓴다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pharma_proto.llm.memory_keys import MemoryKeyStore
from tests.product.snapshot_fixtures import write_test_snapshot


def _create_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    database, manifest = write_test_snapshot(tmp_path / "release")
    from pharma_proto.app import create_app

    return create_app({"SNAPSHOT_PATH": database, "MANIFEST_PATH": manifest, "KEY_STORE": MemoryKeyStore()})


def test_legacy_user_data_moves_even_after_bootstrap_created_the_new_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "local" / "PhramaProto"
    old_result = legacy / "results" / "20261001T000000Z-aaaaaaaa"
    old_result.mkdir(parents=True)
    (old_result / "request.json").write_text("{}", encoding="utf-8")
    (legacy / "preferences.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    (legacy / "cache").mkdir()
    (legacy / "cache" / "smiles.json").write_text("{}", encoding="utf-8")
    (legacy / "runtime" / "venv").mkdir(parents=True)
    new = tmp_path / "local" / "PharmaProto"
    (new / "logs").mkdir(parents=True)   # start.bat 의 bootstrap 이 앱보다 먼저 만든다
    (new / "tools").mkdir()
    (new / "results" / "20261005T000000Z-bbbbbbbb").mkdir(parents=True)   # 이름 수정 뒤 새로 저장한 작업

    client = _create_app(tmp_path, monkeypatch).test_client()

    assert sorted(path.name for path in (new / "results").iterdir()) == [
        "20261001T000000Z-aaaaaaaa", "20261005T000000Z-bbbbbbbb",
    ]
    assert (new / "results" / "20261001T000000Z-aaaaaaaa" / "request.json").is_file()
    assert client.get("/api/preferences").get_json() == {"theme": "dark"}
    assert (new / "cache" / "smiles.json").is_file()
    assert (legacy / "runtime" / "venv").is_dir() and not (new / "runtime").exists()   # 실행 환경은 옮기지 않는다


def test_new_folder_data_wins_over_legacy_copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = tmp_path / "local" / "PhramaProto"
    (legacy / "results" / "20261001T000000Z-aaaaaaaa").mkdir(parents=True)
    (legacy / "results" / "20261001T000000Z-aaaaaaaa" / "request.json").write_text('{"old": 1}', encoding="utf-8")
    (legacy / "preferences.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    new = tmp_path / "local" / "PharmaProto"
    (new / "results" / "20261001T000000Z-aaaaaaaa").mkdir(parents=True)
    (new / "results" / "20261001T000000Z-aaaaaaaa" / "request.json").write_text('{"new": 1}', encoding="utf-8")
    (new / "preferences.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8")

    client = _create_app(tmp_path, monkeypatch).test_client()

    assert client.get("/api/preferences").get_json() == {"theme": "light"}
    saved = new / "results" / "20261001T000000Z-aaaaaaaa" / "request.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == {"new": 1}
    assert (legacy / "preferences.json").is_file()   # 겹치는 옛 사본은 지우지 않고 남겨 둔다

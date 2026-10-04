from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from gates.smiles_resolver import SmilesResolver


ROOT = Path(__file__).resolve().parents[2]
# 이 suite 를 돌리는 인터프리터를 그대로 쓴다. 고정된 .venv 경로는 OS 마다 다르다.
PYTHON = Path(sys.executable)


# DB 저장소 전용 테스트(ingest/collect import)는 Phrama_Proto 로 남겼다.


def test_default_smiles_cache_is_owned_by_local_application_data(tmp_path, monkeypatch):
    local_app_data = tmp_path / "사용자 로컬 데이터"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    resolver = SmilesResolver(offline=True)

    expected = local_app_data / "PhramaProto" / "cache" / "smiles.json"
    assert resolver._path == expected
    assert not expected.exists()

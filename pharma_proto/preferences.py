"""비밀이 아닌 화면 설정만 담는 작은 JSON 저장소 — LOCALAPPDATA/PharmaProto/preferences.json.

허용 키·허용 값만 읽고 쓴다. 키 이름이 비밀처럼 보이면(key|secret|token|password) 거부한다.
파일이 없거나 깨졌으면 기본값으로 동작하고, 쓰기 실패(OSError)는 호출자가 코드로만 기록한다.
브라우저 저장소를 쓰지 않는 규칙(키가 브라우저에 남지 않게) 때문에 테마 선택값도 여기에 둔다.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from pathlib import Path

THEMES = ("system", "light", "dark")      # 'system' 은 예전 저장값 호환용(OS 설정을 따름)
ALLOWED: dict[str, tuple[str, ...]] = {"theme": THEMES}
DEFAULTS: dict[str, str] = {"theme": "light"}   # 기본은 밝은 화면
_SECRET_SHAPE = re.compile(r"key|secret|token|password", re.IGNORECASE)


def _accepts(name: str, value: object) -> bool:
    return name in ALLOWED and not _SECRET_SHAPE.search(name) and value in ALLOWED[name]


class PreferenceStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @staticmethod
    def validate(values: Mapping[str, object]) -> dict[str, str]:
        clean: dict[str, str] = {}
        for name, value in values.items():
            if not _accepts(name, value):
                raise ValueError("unsupported preference")
            clean[name] = str(value)
        return clean

    def _read(self) -> dict[str, str]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return dict(DEFAULTS)
        if not isinstance(raw, Mapping):
            return dict(DEFAULTS)
        out = dict(DEFAULTS)
        for name, value in raw.items():
            if _accepts(name, value):
                out[name] = str(value)
        return out

    def load(self) -> dict[str, str]:
        with self._lock:
            return self._read()

    def update(self, values: Mapping[str, object]) -> dict[str, str]:
        """허용된 값만 합쳐 저장하고 전체 설정을 돌려준다. 임시 파일에 쓴 뒤 바꿔치기(부분 쓰기 방지)."""
        clean = self.validate(values)
        with self._lock:
            current = self._read()
            current.update(clean)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self._path)
            return current


__all__ = ["ALLOWED", "DEFAULTS", "THEMES", "PreferenceStore"]

"""성분명 → SMILES 확보·캐시 (게이트2 Task B).

- 1) 로컬 캐시(`00_Data/pharma_raw/_smiles_cache.json`) → 있으면 즉시 반환(무료).
- 2) 없으면 PubChem PUG-REST 이름→SMILES 조회 후 캐시 저장.
- 실패 시 캐시에 null 기록(그 성분은 규칙 판정 스킵) — 재조회 방지.

★프리플라이트 수정: 지시서의 `/property/CanonicalSMILES/` 는 현재 PubChem에서 null 을 반환한다.
  현행 API는 `/property/SMILES/`(또는 ConnectivitySMILES)로 SMILES 를 준다. 그쪽을 쓴다.

rate limit: 요청 간 0.2s 지연, 실패 1회 재시도. 네트워크는 이 단계만.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def _default_cache_path() -> Path:
    local_root = Path(os.environ.get("LOCALAPPDATA", Path.cwd() / ".runtime"))
    return local_root / "PharmaProto" / "cache" / "smiles.json"

_PUBCHEM = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
            "{name}/property/SMILES/JSON")

# 오프라인/결정성 보장용 시드(논문 검증 사례 분자). PubChem 없이도 3개 정답이 재현되게.
# 값은 PubChem 실측(2026-07). 무기 부형제(talc 등)는 반응성 무관이라 시드 불필요.
_SEED_SMILES: dict[str, str] = {
    "amlodipine": "CCOC(=O)C1=C(NC(=C(C1C2=CC=CC=C2Cl)C(=O)OC)C)COCCN",
    "aspirin": "CC(=O)OC1=CC=CC=C1C(=O)O",
    "chlorpromazine": "CN(C)CCCN1C2=CC=CC=C2SC2=CC=C(Cl)C=C21",
    "metformin": "CN(C)C(=N)N=C(N)N",
    "lactose": "OCC1OC(OC2C(O)C(O)C(O)OC2CO)C(O)C(O)C1O",
    "lactose monohydrate": "OCC1OC(OC2C(O)C(O)C(O)OC2CO)C(O)C(O)C1O.O",
    "magnesium stearate": "CCCCCCCCCCCCCCCCCC(=O)[O-].CCCCCCCCCCCCCCCCCC(=O)[O-].[Mg+2]",
    "povidone": "C=CN1CCCC1=O",  # 반복단위 대표(불순물 판정은 이름사전이 담당)
    "talc": None,               # 무기물(Mg3Si4O10(OH)2) — 반응성 SMARTS 대상 아님
    "magnesium oxide": "[Mg+2].[O-2]",
}


class SmilesResolver:
    def __init__(self, *, cache_path: Path | None = None, delay: float = 0.2,
                 offline: bool = False) -> None:
        self._path = cache_path or _default_cache_path()
        self._delay = delay
        self._offline = offline
        self._persist = cache_path is not None or not offline
        self._cache: dict[str, str | None] = {}
        existed = self._path.exists()
        if existed:
            self._cache = json.loads(self._path.read_text(encoding="utf-8"))
        # 시드는 캐시에 없을 때만 채운다(사용자 캐시 우선).
        added = False
        for k, v in _SEED_SMILES.items():
            if k not in self._cache:
                self._cache[k] = v
                added = True
        # 시드를 디스크에 영속화(지시서가 _smiles_cache.json 을 산출물로 명시).
        if self._persist and (added or not existed):
            self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _norm(name: str) -> str:
        return name.strip().lower()

    def resolve(self, name: str) -> str | None:
        """canonical_name → SMILES(없으면 None). 캐시 우선, 없으면 PubChem."""
        key = self._norm(name)
        if key in self._cache:
            return self._cache[key]
        smiles = None if self._offline else self._fetch(key)
        self._cache[key] = smiles
        if self._persist:
            self._save()
        return smiles

    def _fetch(self, name: str) -> str | None:
        import httpx
        from urllib.parse import quote

        url = _PUBCHEM.format(name=quote(name, safe=""))
        for attempt in (1, 2):
            try:
                time.sleep(self._delay)
                r = httpx.get(url, timeout=20.0)
                if r.status_code == 200:
                    props = r.json().get("PropertyTable", {}).get("Properties", [{}])[0]
                    val = props.get("SMILES") or props.get("ConnectivitySMILES")
                    if val:
                        return val
                if r.status_code == 404:
                    return None            # 이름 못 찾음 — 재시도 무의미
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    print(f"[smiles] {name}: fetch failed {exc}")
        return None

    def resolve_many(self, names: list[str]) -> dict[str, str | None]:
        return {n: self.resolve(n) for n in names}

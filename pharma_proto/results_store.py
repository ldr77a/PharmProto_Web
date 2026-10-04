"""저장된 작업 — LOCALAPPDATA/PhramaProto/results/<YYYYMMDDTHHMMSSZ>-<conversation_id[:8]>/.

사용자가 '이 결과 저장'을 눌렀을 때만 쓴다(자동 저장 없음). 폴더마다:
  request.json      요청·스냅샷·모델·앱 버전(API 키는 절대 넣지 않는다)
  result.html       독립 실행형 페이지 — CSS 를 안에 넣어 파일만 열어도 서식이 보인다
  explanation.json  해설층 출력(재개 때 LLM 을 다시 부르지 않으려고)
  followup.json     후속 질의응답 기록
  조성_후보_N.xlsx   생성 때 이미 만든 엑셀 바이트 그대로
앱은 result.html 을 서빙하지 않고 JSON 으로만 돌려준다. id 는 정규식으로 검증하고 루트 아래인지
확인한다. 응답·로그에 경로를 쓰지 않는다(호출자 책임).
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from generation.html_formatter import (
    RESULT_FRAGMENT_END,
    RESULT_FRAGMENT_START,
    standalone_result_html,
)

REQUEST_SCHEMA = 1
_ID_RE = re.compile(r"^\d{8}T\d{6}Z(?:-\d+)?-[0-9a-f]{8}$")
_PREVIEW_LIMIT = 80


@dataclass(frozen=True)
class SavedResultSummary:
    id: str
    saved_at: str
    question_preview: str
    api_names: list[str]
    n_candidates: int
    snapshot_id: str


@dataclass(frozen=True)
class SavedResult:
    id: str
    saved_at: str
    question: str
    turns: list[dict[str, Any]]
    parsed_request: dict[str, Any] | None
    html: str
    downloads: list[dict[str, Any]]
    snapshot_id: str
    explanation: dict[str, Any] | None
    explanation_error: str | None
    provider: str
    tier: str
    model: str


def _preview(text: str) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= _PREVIEW_LIMIT else compact[: _PREVIEW_LIMIT - 1].rstrip() + "…"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fragment_of(page: str) -> str:
    start = page.find(RESULT_FRAGMENT_START)
    end = page.find(RESULT_FRAGMENT_END)
    if start < 0 or end < 0 or end < start:
        return ""
    return page[start + len(RESULT_FRAGMENT_START):end]


class ResultsStore:
    def __init__(self, root: Path | str, *, css_text: str, app_version: str) -> None:
        self._root = Path(root)
        self._css_text = css_text
        self._app_version = app_version

    # --- 경로 안전 -----------------------------------------------------------------------
    def _dir_for(self, result_id: str) -> Path | None:
        if not isinstance(result_id, str) or not _ID_RE.match(result_id):
            return None
        path = self._root / result_id
        if path.resolve().parent != self._root.resolve():
            return None
        return path

    # --- 쓰기 -------------------------------------------------------------------------------
    def save(
        self,
        *,
        conversation_id: str,
        question: str,
        turns: list[dict[str, Any]],
        parsed_request: dict[str, Any] | None,
        snapshot_id: str,
        provider: str,
        tier: str,
        model: str,
        html: str,
        downloads: list[dict[str, Any]],
        explanation: dict[str, Any] | None,
        explanation_error: str | None,
        api_names: list[str],
        n_candidates: int,
        saved_at: datetime | None = None,
    ) -> str:
        """임시 폴더에 전부 쓴 뒤 이름을 바꾼다(부분 저장본 방지). 같은 초에 겹치면 -2, -3…"""
        moment = saved_at or datetime.now(UTC)
        stamp = moment.strftime("%Y%m%dT%H%M%SZ")
        suffix = conversation_id[:8]
        self._root.mkdir(parents=True, exist_ok=True)
        result_id = f"{stamp}-{suffix}"
        counter = 1
        while (self._root / result_id).exists():
            counter += 1
            result_id = f"{stamp}-{counter}-{suffix}"

        files = [
            {"candidate_idx": int(item["candidate_idx"]), "filename": f"조성_후보_{int(item['candidate_idx'])}.xlsx"}
            for item in downloads
        ]
        request = {
            "schema": REQUEST_SCHEMA,
            "id": result_id,
            "conversation_id": conversation_id,
            "saved_at": moment.isoformat(timespec="seconds"),
            "question": question,
            "parsed_request": parsed_request,
            "snapshot_id": snapshot_id,
            "provider": provider,
            "tier": tier,
            "model": model,
            "app_version": self._app_version,
            "api_names": list(api_names),
            "n_candidates": int(n_candidates),
            "explanation_error": explanation_error,
            "downloads": files,
        }
        temporary = self._root / f".tmp-{uuid.uuid4().hex}"
        temporary.mkdir()
        try:
            _write_json(temporary / "request.json", request)
            _write_json(temporary / "explanation.json", explanation)
            _write_json(temporary / "followup.json", list(turns))
            (temporary / "result.html").write_text(
                self._page(html, turns, request), encoding="utf-8"
            )
            for item, meta in zip(downloads, files, strict=True):
                (temporary / meta["filename"]).write_bytes(base64.b64decode(item["content_base64"]))
            temporary.rename(self._root / result_id)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return result_id

    def _page(self, fragment: str, turns: list[dict[str, Any]], request: dict[str, Any]) -> str:
        return standalone_result_html(
            fragment,
            css_text=self._css_text,
            title=f"신약 배합 생성기 결과 · {request.get('saved_at', '')}",
            turns=turns,
        )

    def append_turns(self, result_id: str, turns: list[dict[str, Any]]) -> bool:
        """저장 뒤에 이어진 질의응답을 같은 폴더에 반영한다(followup.json + result.html)."""
        path = self._dir_for(result_id)
        if path is None or not (path / "request.json").is_file():
            return False
        request = _read_json(path / "request.json")
        fragment = _fragment_of((path / "result.html").read_text(encoding="utf-8"))
        _write_json(path / "followup.json", list(turns))
        (path / "result.html").write_text(self._page(fragment, list(turns), request), encoding="utf-8")
        return True

    # --- 읽기 -------------------------------------------------------------------------------
    def list(self) -> list[SavedResultSummary]:
        if not self._root.is_dir():
            return []
        items: list[SavedResultSummary] = []
        for folder in self._root.iterdir():
            if not folder.is_dir() or not _ID_RE.match(folder.name):
                continue
            try:
                request = _read_json(folder / "request.json")
                items.append(SavedResultSummary(
                    id=folder.name,
                    saved_at=str(request.get("saved_at", "")),
                    question_preview=_preview(str(request.get("question", ""))),
                    api_names=[str(name) for name in request.get("api_names", [])],
                    n_candidates=int(request.get("n_candidates", 0)),
                    snapshot_id=str(request.get("snapshot_id", "")),
                ))
            except (OSError, ValueError, TypeError, AttributeError):
                continue   # 손상된 폴더는 목록에서 뺀다(지우지는 않는다)
        items.sort(key=lambda item: item.id, reverse=True)   # id 앞부분이 시각 → 최신순
        return items

    def load(self, result_id: str) -> SavedResult | None:
        path = self._dir_for(result_id)
        if path is None or not (path / "request.json").is_file():
            return None
        try:
            request = _read_json(path / "request.json")
            page = (path / "result.html").read_text(encoding="utf-8")
            explanation = _read_json(path / "explanation.json") if (path / "explanation.json").is_file() else None
            turns = _read_json(path / "followup.json") if (path / "followup.json").is_file() else []
            downloads = []
            for meta in request.get("downloads", []):
                file = path / str(meta["filename"])
                if file.resolve().parent != path.resolve() or not file.is_file():
                    continue
                downloads.append({
                    "candidate_idx": int(meta["candidate_idx"]),
                    "filename": str(meta["filename"]),
                    "content_base64": base64.b64encode(file.read_bytes()).decode("ascii"),
                })
        except (OSError, ValueError, TypeError, KeyError):
            return None
        parsed = request.get("parsed_request")
        return SavedResult(
            id=path.name,
            saved_at=str(request.get("saved_at", "")),
            question=str(request.get("question", "")),
            turns=list(turns) if isinstance(turns, list) else [],
            parsed_request=parsed if isinstance(parsed, dict) else None,
            html=_fragment_of(page),
            downloads=downloads,
            snapshot_id=str(request.get("snapshot_id", "")),
            explanation=explanation if isinstance(explanation, dict) else None,
            explanation_error=request.get("explanation_error"),
            provider=str(request.get("provider", "")),
            tier=str(request.get("tier", "")),
            model=str(request.get("model", "")),
        )

    def delete(self, result_id: str) -> bool:
        path = self._dir_for(result_id)
        if path is None or not path.is_dir():
            return False
        shutil.rmtree(path)
        return True


__all__ = ["REQUEST_SCHEMA", "ResultsStore", "SavedResult", "SavedResultSummary"]

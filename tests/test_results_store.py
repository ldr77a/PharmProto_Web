"""피드백 9번 — 저장된 작업 폴더(수동 저장): 파일 구성, 목록, 열기, 삭제, 경로 안전."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pharma_proto.results_store import ResultsStore

_CSS = ":root { --bg: #fff; }\n.print-only { display: none; }"
_XLSX = b"PK\x03\x04fake-xlsx"


def _store(tmp_path: Path) -> ResultsStore:
    return ResultsStore(tmp_path / "results", css_text=_CSS, app_version="0.1.0")


def _save(store: ResultsStore, **overrides) -> str:
    fields = {
        "conversation_id": "a" * 32,
        "question": "아세트아미노펜 500 mg 정제",
        "turns": [{"role": "user", "kind": "question", "text": "아세트아미노펜 500 mg 정제"}],
        "parsed_request": {"apis": [{"name": "acetaminophen", "dose_mg": 500}]},
        "snapshot_id": "fixture-snapshot",
        "provider": "openai", "tier": "normal", "model": "gpt-5.6-terra",
        "html": "<header class='print-header print-only'>머리글</header><div class='card'>표</div>",
        "downloads": [{"candidate_idx": 1, "filename": "조성_후보_1.xlsx",
                       "content_base64": base64.b64encode(_XLSX).decode("ascii")}],
        "explanation": {"candidates": [], "disclaimer": "검토용."},
        "explanation_error": None,
        "api_names": ["acetaminophen"],
        "n_candidates": 1,
    }
    fields.update(overrides)
    return store.save(**fields)


def test_save_writes_standalone_html_xlsx_and_request_without_keys(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result_id = _save(store)

    assert re.fullmatch(r"\d{8}T\d{6}Z-aaaaaaaa", result_id)
    folder = tmp_path / "results" / result_id
    assert sorted(p.name for p in folder.iterdir()) == [
        "explanation.json", "followup.json", "request.json", "result.html", "조성_후보_1.xlsx",
    ]
    page = (folder / "result.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and "data-theme='light'" in page
    assert _CSS in page and ".print-only { display: block; }" in page       # 파일만 열어도 서식·머리글이 보인다
    assert "<!-- pharma:result -->" in page and "반드시 사람이 검토" in page
    assert (folder / "조성_후보_1.xlsx").read_bytes() == _XLSX
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    assert request["schema"] == 1 and request["id"] == result_id
    assert request["snapshot_id"] == "fixture-snapshot" and request["app_version"] == "0.1.0"
    assert request["downloads"] == [{"candidate_idx": 1, "filename": "조성_후보_1.xlsx"}]
    assert not any("key" in name.casefold() for name in request)
    assert not list((tmp_path / "results").glob(".tmp-*"))


def test_list_is_newest_first_and_skips_corrupt_or_foreign_entries(tmp_path: Path) -> None:
    store = _store(tmp_path)
    older = _save(store, saved_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC), question="첫째 작업")
    newer = _save(store, saved_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC), question="둘째 작업",
                  conversation_id="b" * 32)
    corrupt = tmp_path / "results" / "20261002T000000Z-cccccccc"
    corrupt.mkdir()
    (corrupt / "request.json").write_text("{broken", encoding="utf-8")
    (tmp_path / "results" / "not-a-result").mkdir()

    items = store.list()

    assert [item.id for item in items] == [newer, older]
    assert items[0].question_preview == "둘째 작업"
    assert items[0].api_names == ["acetaminophen"] and items[0].n_candidates == 1
    assert items[0].saved_at == "2026-10-03T09:00:00+00:00"


def test_list_is_empty_before_anything_is_saved(tmp_path: Path) -> None:
    assert _store(tmp_path).list() == []
    assert not (tmp_path / "results").exists()


def test_same_second_saves_get_distinct_ids(tmp_path: Path) -> None:
    store = _store(tmp_path)
    moment = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

    first = _save(store, saved_at=moment)
    second = _save(store, saved_at=moment)

    assert first == "20261004T120000Z-aaaaaaaa"
    assert second == "20261004T120000Z-2-aaaaaaaa"
    assert {item.id for item in store.list()} == {first, second}


def test_load_returns_fragment_downloads_turns_and_explanation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result_id = _save(store)

    saved = store.load(result_id)

    assert saved is not None
    assert saved.html == "<header class='print-header print-only'>머리글</header><div class='card'>표</div>"
    assert saved.downloads[0]["filename"] == "조성_후보_1.xlsx"
    assert base64.b64decode(saved.downloads[0]["content_base64"]) == _XLSX
    assert saved.turns[0]["kind"] == "question"
    assert saved.parsed_request["apis"][0]["name"] == "acetaminophen"
    assert saved.explanation == {"candidates": [], "disclaimer": "검토용."}
    assert (saved.provider, saved.tier, saved.model) == ("openai", "normal", "gpt-5.6-terra")


def test_append_turns_updates_followup_and_html(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result_id = _save(store)
    turns = [
        {"role": "user", "kind": "question", "text": "왜?"},
        {"role": "assistant", "kind": "answer", "text": "근거.", "html": "<div class='card followup'>근거.</div>"},
    ]

    assert store.append_turns(result_id, turns) is True

    saved = store.load(result_id)
    assert saved is not None and len(saved.turns) == 2
    page = (tmp_path / "results" / result_id / "result.html").read_text(encoding="utf-8")
    assert "<div class='card followup'>근거.</div>" in page and "후속 질의응답" in page
    assert saved.html.endswith("<div class='card'>표</div>")             # 결과 조각은 그대로
    assert store.append_turns("20990101T000000Z-deadbeef", []) is False


def test_results_saved_before_the_name_fix_keep_their_table(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result_id = _save(store)
    page_path = tmp_path / "results" / result_id / "result.html"
    old_page = page_path.read_text(encoding="utf-8").replace("pharma:result", "phrama:result")   # 2026-10-05 이전 표지
    page_path.write_text(old_page, encoding="utf-8")

    assert store.load(result_id).html.endswith("<div class='card'>표</div>")
    assert store.append_turns(result_id, [{"role": "user", "kind": "question", "text": "왜?"}]) is True
    assert store.load(result_id).html.endswith("<div class='card'>표</div>")   # 덧붙여 써도 표가 사라지지 않는다


@pytest.mark.parametrize(
    "bad",
    ["../x", "..\\x", "/etc/passwd", "20261004T120000Z-ZZZZZZZZ", "a" * 300,
     "20261004T120000Z-aaaaaaaa/../..", "", "20261004T120000Z-aaaaaaa"],
)
def test_invalid_ids_are_rejected_without_touching_disk(tmp_path: Path, bad: str) -> None:
    store = _store(tmp_path)

    assert store.load(bad) is None
    assert store.delete(bad) is False
    assert store.append_turns(bad, []) is False
    assert not (tmp_path / "results").exists()


def test_location_hint_hides_real_paths_outside_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pharma_proto.results_store.os.name", "posix")
    outside = _store(tmp_path).location_hint()
    assert str(tmp_path) not in outside and "PharmaProto/results" in outside

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    under_home = ResultsStore(tmp_path / "Library" / "PharmaProto" / "results", css_text=_CSS, app_version="0.1.0")
    assert under_home.location_hint() == "~/Library/PharmaProto/results"

    monkeypatch.setattr("pharma_proto.results_store.os.name", "nt")
    assert _store(tmp_path).location_hint() == r"%LOCALAPPDATA%\PharmaProto\results"


def test_open_folder_creates_root_and_calls_opener(tmp_path: Path) -> None:
    store = _store(tmp_path)
    opened: list[Path] = []

    store.open_folder(opener=opened.append)

    assert opened == [tmp_path / "results"] and (tmp_path / "results").is_dir()


def test_delete_removes_folder_and_unknown_returns_false(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result_id = _save(store)

    assert store.delete(result_id) is True
    assert not (tmp_path / "results" / result_id).exists()
    assert store.delete(result_id) is False
    assert store.list() == []

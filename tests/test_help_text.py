"""피드백 6번 — 화면의 근거 꼬리표·게이트·배지마다 쉬운 말 설명이 있고, 사이드바와 같은 문장을 쓴다."""

from __future__ import annotations

from generation.help_text import BASIS, GATES, SOURCES, STATUS, help_entries
from generation.html_formatter import _SRC_KO


def test_every_provenance_label_has_a_plain_language_explanation() -> None:
    assert set(SOURCES) == set(_SRC_KO)
    for key, (label, _green) in _SRC_KO.items():
        assert SOURCES[key]["title"] == label
        assert len(SOURCES[key]["text"]) > 20


def test_help_entries_cover_gates_sources_basis_and_status() -> None:
    entries = help_entries()

    assert [gate["key"] for gate in GATES] == ["gate:1", "gate:2", "gate:3", "gate:4", "gate:5"]
    assert {gate["key"] for gate in GATES} <= set(entries)
    assert {f"src:{key}" for key in SOURCES} <= set(entries)
    assert set(BASIS) == {"basis:evidence", "basis:general"} and set(BASIS) <= set(entries)
    assert set(STATUS) == {"status:pass", "status:warning", "status:unresolved"} and set(STATUS) <= set(entries)
    assert all(entry["title"] and entry["text"] for entry in entries.values())

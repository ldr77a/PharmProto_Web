from __future__ import annotations

from pharma_proto.diagnostics import configure_safe_logging


def test_safe_log_rotates_and_contains_only_allowlisted_fields(tmp_path):
    diagnostics = configure_safe_logging(
        tmp_path,
        max_bytes=180,
        backup_count=2,
    )

    for index in range(20):
        diagnostics.record(
            event="llm_error",
            code="LLM-UPSTREAM-001",
            provider="openai",
            model="gpt-5.6-terra",
            snapshot_id="snapshot-safe",
            request_id=f"request-{index}",
        )
    diagnostics.close()

    files = sorted(tmp_path.glob("app.log*"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert len(files) >= 2
    assert "LLM-UPSTREAM-001" in text
    assert "snapshot-safe" in text
    assert "traceback" not in text.casefold()
    assert "question" not in text.casefold()
    assert "api_key" not in text.casefold()


def test_diagnostics_summary_exposes_versions_counts_and_recent_codes(tmp_path):
    diagnostics = configure_safe_logging(tmp_path)
    diagnostics.record(event="llm_error", code="LLM-RATE-001", provider="gemini")

    summary = diagnostics.summary(
        repository_health={
            "status": "ok",
            "snapshot_id": "snapshot-1",
            "schema_version": 1,
            "node_count": 2,
            "relationship_count": 1,
        },
        provider_status={"openai": True, "gemini": False, "claude": False},
    )

    assert summary == {
        "app_version": "0.2.0",
        "database": {
            "status": "ok",
            "snapshot_id": "snapshot-1",
            "schema_version": 1,
            "node_count": 2,
            "relationship_count": 1,
        },
        "providers": {"openai": True, "gemini": False, "claude": False},
        "recent_error_codes": ["LLM-RATE-001"],
    }

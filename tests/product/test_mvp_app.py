from __future__ import annotations

from pathlib import Path

import pytest

from generation.input_parser import build_spec
from pharma_proto.errors import AppError
from pharma_proto.llm.memory_keys import MemoryKeyStore
from pharma_proto.llm.resilience import LLMFailure
from tests.product.snapshot_fixtures import write_test_snapshot


class FakeLLMService:
    def __init__(self, failure: LLMFailure | None = None):
        self.failure = failure
        self.calls = []

    def parse(self, provider, tier, api_key, question):
        self.calls.append((provider, tier, api_key, question))
        if self.failure is not None:
            raise self.failure
        return build_spec(
            [("acetaminophen", 500.0)],
            {
                "binder": ["povidone"],
                "disintegrant": ["croscarmellose sodium"],
                "diluent": ["mannitol"],
                "lubricant": ["magnesium stearate"],
            },
            dosage_form="tablet",
            process="direct compression",
            n_candidates=1,
        )


def _app(tmp_path, monkeypatch, *, service=None):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local app data"))
    database, manifest = write_test_snapshot(tmp_path / "release data")
    from pharma_proto.app import create_app

    return create_app(
        {
            "SNAPSHOT_PATH": database,
            "MANIFEST_PATH": manifest,
            "KEY_STORE": MemoryKeyStore(),
            "LLM_SERVICE": service or FakeLLMService(),
        }
    )


def test_app_health_and_diagnostics_expose_only_safe_status(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()

    health = client.get("/health")
    diagnostics = client.get("/api/diagnostics")

    assert health.status_code == 200
    assert health.get_json() == {
        "status": "ok",
        "app_version": "0.1.0",
        "snapshot_id": "fixture-snapshot",
        "schema_version": 2,
        "node_count": 2,
        "relationship_count": 1,
        "providers": {"openai": False, "gemini": False, "claude": False},
    }
    assert diagnostics.status_code == 200
    assert diagnostics.get_json()["recent_error_codes"] == []
    assert "path" not in diagnostics.get_data(as_text=True).casefold()


def test_key_then_generate_returns_existing_generation_html_without_leaking_key(
    tmp_path, monkeypatch
):
    service = FakeLLMService()
    app = _app(tmp_path, monkeypatch, service=service)
    client = app.test_client()
    marker = "temporary-secret-marker-123456"

    key_response = client.post(
        "/api/key", json={"provider": "openai", "api_key": marker}
    )
    generation = client.post(
        "/api/generate",
        json={
            "provider": "openai",
            "tier": "normal",
            "question": "아세트아미노펜 500 mg 속방정제를 직접타정법으로 제조해라.",
        },
    )

    assert key_response.get_json() == {"provider": "openai", "configured": True}
    assert generation.status_code == 200
    assert "조성 후보 1" in generation.get_json()["html"]
    combined = key_response.get_data(as_text=True) + generation.get_data(as_text=True)
    assert marker not in combined
    assert service.calls[0][0:2] == ("openai", "normal")
    assert "Set-Cookie" not in generation.headers


def test_provider_failure_returns_specific_safe_code_and_diagnostics(tmp_path, monkeypatch):
    service = FakeLLMService(
        LLMFailure(
            "LLM-AUTH-001",
            False,
            request_id="request-safe-1",
            status_code=401,
        )
    )
    app = _app(tmp_path, monkeypatch, service=service)
    client = app.test_client()
    client.post("/api/key", json={"provider": "openai", "api_key": "tempo" + "rary"})

    response = client.post(
        "/api/generate",
        json={"provider": "openai", "tier": "normal", "question": "question"},
    )

    assert response.status_code == 401
    assert response.get_json() == {"error": "LLM-AUTH-001"}
    diagnostics = client.get("/api/diagnostics").get_json()
    assert diagnostics["recent_error_codes"] == ["LLM-AUTH-001"]
    assert "request-safe-1" not in response.get_data(as_text=True)


def test_app_rejects_extra_request_fields_and_missing_key(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()

    invalid = client.post(
        "/api/key",
        json={"provider": "openai", "api_key": "secret", "extra": True},
    )
    missing = client.post(
        "/api/generate",
        json={"provider": "openai", "tier": "normal", "question": "question"},
    )

    assert invalid.status_code == 400
    assert invalid.get_json() == {"error": "REQUEST-001"}
    assert missing.status_code == 400
    assert missing.get_json() == {"error": "LLM-KEY-001"}


class _SyrupLLMService(FakeLLMService):
    def parse(self, provider, tier, api_key, question):
        return build_spec([("acetaminophen", 500.0)], {}, dosage_form="syrup", n_candidates=1)


def test_unsupported_dosage_form_returns_request_form_code(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, service=_SyrupLLMService())
    client = app.test_client()
    client.post("/api/key", json={"provider": "openai", "api_key": "tempo" + "rary"})

    response = client.post(
        "/api/generate",
        json={"provider": "openai", "tier": "normal", "question": "아세트아미노펜 시럽"},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "REQUEST-FORM-001"}
    assert client.get("/api/diagnostics").get_json()["recent_error_codes"] == ["REQUEST-FORM-001"]


def test_all_responses_have_local_security_headers(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    response = app.test_client().get("/")

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "connect-src 'self'" in response.headers["Content-Security-Policy"]


def test_corrupt_snapshot_prevents_app_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    database, manifest = write_test_snapshot(tmp_path / "release")
    database.write_bytes(b"broken")
    from pharma_proto.app import create_app

    with pytest.raises(AppError) as caught:
        create_app({"SNAPSHOT_PATH": database, "MANIFEST_PATH": manifest})
    assert caught.value.code == "DB-INTEGRITY-001"


def test_static_javascript_uses_no_browser_persistence():
    root = Path(__file__).resolve().parents[2]
    text = (root / "pharma_proto" / "static" / "app.js").read_text(encoding="utf-8")
    assert "localStorage" not in text
    assert "sessionStorage" not in text
    assert "document.cookie" not in text

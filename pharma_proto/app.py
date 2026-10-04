"""SQLite-only Flask application for the researcher Release ZIP."""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from flask import Flask, jsonify, render_template, request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from werkzeug.exceptions import HTTPException

from generation.explanation import build_explanation_payload
from generation.generation_loop import run_generation
from generation.html_formatter import results_html
from generation.oral_solid_profiles import UnsupportedDosageForm
from pharma_proto import __version__
from pharma_proto.diagnostics import SafeDiagnostics, configure_safe_logging
from pharma_proto.errors import (
    APP_START_ERROR,
    LLM_KEY_ERROR,
    REQUEST_ERROR,
    REQUEST_FORM_ERROR,
    AppError,
)
from pharma_proto.excel_export import candidate_workbook
from pharma_proto.knowledge.sqlite_repository import SQLiteKnowledgeRepository
from pharma_proto.llm.catalog import MODEL_CATALOG, model_for
from pharma_proto.llm.memory_keys import MemoryKeyStore
from pharma_proto.llm.resilience import LLMFailure
from pharma_proto.llm.service import LLMService

_ROOT = Path(__file__).resolve().parents[1]


class _KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "gemini", "claude"]
    api_key: str = Field(min_length=1, max_length=500)


class _GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "gemini", "claude"]
    tier: Literal["cheap", "normal", "good"] = "normal"
    question: str = Field(min_length=1, max_length=4000)


def _provider_status(store: MemoryKeyStore) -> dict[str, bool]:
    return {provider: store.configured(provider) for provider in MODEL_CATALOG}


def _parse_body(model_type):
    try:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TypeError
        return model_type.model_validate(body)
    except (ValidationError, TypeError, ValueError):
        raise AppError(REQUEST_ERROR, 400) from None


def shutdown_app_resources(app: Flask) -> None:
    repository = app.extensions.get("knowledge_repository")
    if repository is not None:
        repository.close()
    key_store = app.extensions.get("key_store")
    if key_store is not None:
        key_store.clear()
    diagnostics = app.extensions.get("diagnostics")
    if diagnostics is not None:
        diagnostics.close()


def create_app(overrides: Mapping[str, Any] | None = None) -> Flask:
    supplied = dict(overrides or {})
    snapshot_path = Path(
        supplied.pop("SNAPSHOT_PATH", _ROOT / "release-data" / "knowledge.sqlite")
    )
    manifest_path = Path(
        supplied.pop("MANIFEST_PATH", _ROOT / "release-data" / "manifest.json")
    )
    key_store = supplied.pop("KEY_STORE", None) or MemoryKeyStore()
    llm_service = supplied.pop("LLM_SERVICE", None) or LLMService()
    if supplied:
        raise TypeError("unsupported application override")

    local_root = Path(os.environ.get("LOCALAPPDATA", str(_ROOT / ".runtime"))) / "PhramaProto"
    diagnostics: SafeDiagnostics = configure_safe_logging(local_root / "logs")
    try:
        repository = SQLiteKnowledgeRepository.open(snapshot_path, manifest_path)
    except Exception:
        diagnostics.record(event="startup_error", code="DB-INTEGRITY-001")
        diagnostics.close()
        raise

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(TRUSTED_HOSTS=["127.0.0.1", "localhost"])
    app.extensions["knowledge_repository"] = repository
    app.extensions["key_store"] = key_store
    app.extensions["llm_service"] = llm_service
    app.extensions["diagnostics"] = diagnostics

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self'; script-src 'self'; "
            "style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    def index():
        return render_template("index.html", model_catalog=MODEL_CATALOG)

    @app.get("/health")
    def health():
        status = repository.health()
        return jsonify(
            status="ok",
            app_version=__version__,
            snapshot_id=status["snapshot_id"],
            schema_version=status["schema_version"],
            node_count=status["node_count"],
            relationship_count=status["relationship_count"],
            providers=_provider_status(key_store),
        )

    @app.get("/api/diagnostics")
    def diagnostic_summary():
        return jsonify(
            diagnostics.summary(
                repository_health=repository.health(),
                provider_status=_provider_status(key_store),
            )
        )

    @app.post("/api/key")
    def configure_key():
        body = _parse_body(_KeyRequest)
        try:
            key_store.set(body.provider, body.api_key)
        except ValueError:
            raise AppError(REQUEST_ERROR, 400) from None
        return jsonify(provider=body.provider, configured=True)

    def _snapshot_id() -> str:
        return str(repository.health()["snapshot_id"])

    def _record_llm_failure(failure: LLMFailure, provider: str, model: str) -> None:
        diagnostics.record(
            event="llm_error",
            code=failure.code,
            provider=provider,
            model=model,
            snapshot_id=_snapshot_id(),
            request_id=failure.request_id,
            provider_code=failure.provider_code,
            provider_status=failure.provider_status,
            provider_reason=failure.provider_reason,
        )

    def _llm_failure(failure: LLMFailure, provider: str, model: str):
        """LLM 호출 실패 → 코드만 담은 응답(본문·키·경로 없음)."""
        _record_llm_failure(failure, provider, model)
        return jsonify(error=failure.code), failure.status_code

    def _generate_candidates(spec, *, provider: str, model: str):
        """결정적 생성. 비고형 제형은 안내 코드로 거절한다(500 이 아니라 400)."""
        try:
            candidates = run_generation(spec, repository=repository, offline=True)
        except UnsupportedDosageForm:
            raise AppError(REQUEST_FORM_ERROR, 400) from None
        diagnostics.record(
            event="generation_complete",
            provider=provider,
            model=model,
            snapshot_id=_snapshot_id(),
        )
        return candidates

    def _explain_or_none(provider: str, tier: str, api_key: str, model: str, spec, candidates):
        """해설층: 숫자는 DB 가 정했고 LLM 은 해석만 한다. 실패해도 표는 그대로 돌려준다."""
        explain = getattr(llm_service, "explain", None)
        if not candidates or not callable(explain):
            return None, None
        try:
            explanation = explain(
                provider,
                tier,
                api_key,
                build_explanation_payload(spec, candidates, repository),
            )
        except LLMFailure as failure:
            _record_llm_failure(failure, provider, model)
            return None, failure.code
        diagnostics.record(
            event="explanation_complete",
            provider=provider,
            model=model,
            snapshot_id=_snapshot_id(),
        )
        return explanation, None

    def _downloads(candidates) -> list[dict[str, Any]]:
        return [
            {
                "candidate_idx": candidate.idx,
                "filename": f"조성_후보_{candidate.idx}.xlsx",
                "content_base64": base64.b64encode(
                    candidate_workbook(candidate)
                ).decode("ascii"),
            }
            for candidate in candidates
        ]

    @app.post("/api/generate")
    def generate():
        body = _parse_body(_GenerateRequest)
        api_key = key_store.get(body.provider)
        if api_key is None:
            raise AppError(LLM_KEY_ERROR, 400)
        model = model_for(body.provider, body.tier)
        try:
            spec = llm_service.parse(
                body.provider,
                body.tier,
                api_key,
                body.question,
            )
        except LLMFailure as failure:
            return _llm_failure(failure, body.provider, model)
        candidates = _generate_candidates(spec, provider=body.provider, model=model)
        explanation, explanation_error = _explain_or_none(
            body.provider, body.tier, api_key, model, spec, candidates
        )
        return jsonify(
            html=results_html(spec, candidates, explanation, explanation_error),
            downloads=_downloads(candidates),
        )

    @app.errorhandler(AppError)
    def app_error(error: AppError):
        diagnostics.record(event="request_error", code=error.code)
        return jsonify(error=error.code), error.status_code

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException):
        diagnostics.record(event="http_error", code=REQUEST_ERROR)
        return jsonify(error=REQUEST_ERROR), error.code

    @app.errorhandler(Exception)
    def unexpected_error(_: Exception):
        diagnostics.record(event="unexpected_error", code=APP_START_ERROR)
        return jsonify(error=APP_START_ERROR), 500

    return app


__all__ = ["create_app", "shutdown_app_resources"]

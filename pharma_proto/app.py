"""SQLite-only Flask application for the researcher Release ZIP."""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from flask import Flask, jsonify, render_template, request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from werkzeug.exceptions import HTTPException

from generation.explanation import build_explanation_payload, build_followup_payload
from generation.generation_loop import run_generation
from generation.html_formatter import (
    followup_answer_html,
    followup_turn_html,
    results_html,
)
from generation.oral_solid_profiles import UnsupportedDosageForm
from pharma_proto import __version__
from pharma_proto.conversation import ConversationStore
from pharma_proto.diagnostics import SafeDiagnostics, configure_safe_logging
from pharma_proto.errors import (
    APP_START_ERROR,
    CONVERSATION_ERROR,
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
from pharma_proto.llm.schema import request_changes
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


class _FollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "gemini", "claude"]
    tier: Literal["cheap", "normal", "good"] = "normal"
    conversation_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
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
    conversations = app.extensions.get("conversation_store")
    if conversations is not None:
        conversations.clear()
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

    conversations = ConversationStore()   # 후속 질문용 대화 상태 — 메모리에만, 로그아웃·종료 때 비운다
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(TRUSTED_HOSTS=["127.0.0.1", "localhost"])
    app.extensions["knowledge_repository"] = repository
    app.extensions["key_store"] = key_store
    app.extensions["llm_service"] = llm_service
    app.extensions["diagnostics"] = diagnostics
    app.extensions["conversation_store"] = conversations

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

    def _render(provider: str, tier: str, api_key: str, model: str, spec) -> dict[str, Any]:
        """생성 → 해설 → HTML·엑셀. generate 와 followup(refine)·resume 가 같은 경로를 탄다."""
        candidates = _generate_candidates(spec, provider=provider, model=model)
        explanation, explanation_error = _explain_or_none(
            provider, tier, api_key, model, spec, candidates
        )
        return {
            "spec": spec,
            "candidates": candidates,
            "explanation": explanation,
            "explanation_error": explanation_error,
            "html": results_html(spec, candidates, explanation, explanation_error),
            "downloads": _downloads(candidates),
        }

    @app.post("/api/generate")
    def generate():
        body = _parse_body(_GenerateRequest)
        api_key = key_store.get(body.provider)
        if api_key is None:
            raise AppError(LLM_KEY_ERROR, 400)
        model = model_for(body.provider, body.tier)
        # 스키마 객체(ParsedRequest)를 돌려주는 서비스면 그것을 보관한다 — 후속 질문이 이 요청을 고쳐 쓴다.
        parse_request = getattr(llm_service, "parse_request", None)
        try:
            if callable(parse_request):
                parsed = parse_request(body.provider, body.tier, api_key, body.question)
                spec = parsed.to_domain()
            else:
                parsed = None
                spec = llm_service.parse(body.provider, body.tier, api_key, body.question)
        except LLMFailure as failure:
            return _llm_failure(failure, body.provider, model)
        rendered = _render(body.provider, body.tier, api_key, model, spec)
        conversation = conversations.create(
            provider=body.provider,
            tier=body.tier,
            question=body.question,
            parsed_request=parsed,
            **rendered,
        )
        conversation.add_turn("user", "question", body.question)
        return jsonify(
            html=rendered["html"],
            downloads=rendered["downloads"],
            conversation_id=conversation.conversation_id,
        )

    @app.post("/api/followup")
    def followup():
        body = _parse_body(_FollowUpRequest)
        api_key = key_store.get(body.provider)
        if api_key is None:
            raise AppError(LLM_KEY_ERROR, 400)
        conversation = conversations.get(body.conversation_id)
        if conversation is None or conversation.parsed_request is None:
            raise AppError(CONVERSATION_ERROR, 404)
        followup_call = getattr(llm_service, "followup", None)
        if not callable(followup_call):
            raise AppError(REQUEST_ERROR, 400)
        model = model_for(body.provider, body.tier)
        payload = build_followup_payload(
            previous_request=conversation.parsed_request.model_dump(mode="json"),
            question=body.question,
            spec=conversation.spec,
            candidates=conversation.candidates,
            repository=repository,
            explanation=conversation.explanation,
            turns=conversation.turns,
        )
        try:
            reply = followup_call(body.provider, body.tier, api_key, payload)
        except LLMFailure as failure:
            return _llm_failure(failure, body.provider, model)
        diagnostics.record(
            event="followup_complete",
            provider=body.provider,
            model=model,
            snapshot_id=_snapshot_id(),
        )
        if reply.action == "refine":
            changes = request_changes(conversation.parsed_request, reply.request)
            if changes:
                # 재생성은 항상 새 요청에서 — run_generation 이 spec 을 바꾸므로 이전 spec 은 재사용하지 않는다.
                rendered = _render(body.provider, body.tier, api_key, model, reply.request.to_domain())
                conversation.parsed_request = reply.request      # 성공한 뒤에만 대화를 갱신한다
                for key, value in rendered.items():
                    setattr(conversation, key, value)
                conversation.result_id = None
            conversation.add_turn("user", "question", body.question)
            conversation.add_turn("assistant", "refine", "\n".join(changes) or "변경 없음")
            conversations.replace(conversation)
            return jsonify(
                conversation_id=conversation.conversation_id,
                action="refine",
                changed=bool(changes),
                html=conversation.html,
                downloads=conversation.downloads,
                answer_html=followup_turn_html(body.question, changes, reply.note),
            )
        conversation.add_turn("user", "question", body.question)
        conversation.add_turn("assistant", "answer", " ".join(item.text for item in reply.answer))
        conversations.replace(conversation)
        return jsonify(
            conversation_id=conversation.conversation_id,
            action="answer",
            html=conversation.html,
            downloads=conversation.downloads,
            answer_html=followup_answer_html(body.question, reply.answer),
        )

    @app.post("/api/logout")
    def logout():
        """메모리의 API 키와 대화를 모두 지운다(파일에는 애초에 없다)."""
        key_store.clear()
        conversations.clear()
        return jsonify(ok=True)

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

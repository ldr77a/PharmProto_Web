"""Stable, safe error values for local HTTP responses."""

from dataclasses import dataclass

APP_START_ERROR = "APP-START-001"
DB_INTEGRITY_ERROR = "DB-INTEGRITY-001"
DB_VERSION_ERROR = "DB-VERSION-001"
REQUEST_ERROR = "REQUEST-001"
LLM_KEY_ERROR = "LLM-KEY-001"
LLM_AUTH_ERROR = "LLM-AUTH-001"
LLM_RATE_ERROR = "LLM-RATE-001"
LLM_TIMEOUT_ERROR = "LLM-TIMEOUT-001"
LLM_UPSTREAM_ERROR = "LLM-UPSTREAM-001"
LLM_RESPONSE_ERROR = "LLM-RESPONSE-001"
RELEASE_BUILD_ERROR = "RELEASE-BUILD-001"
APP_ALREADY_RUNNING_ERROR = "APP-ALREADY-RUNNING-001"
REQUEST_FORM_ERROR = "REQUEST-FORM-001"          # 지원하지 않는 제형(경구 고형제 외)
CONVERSATION_ERROR = "CONVERSATION-001"          # 만료·미지의 대화 id
RESULTS_NOT_FOUND_ERROR = "RESULTS-001"          # 저장된 작업 없음
RESULTS_IO_ERROR = "RESULTS-IO-001"              # 저장·삭제 실패
RESULTS_SNAPSHOT_ERROR = "RESULTS-SNAPSHOT-001"  # 다른 스냅샷으로 만든 저장본 재개
PREFERENCES_IO_ERROR = "PREFERENCES-IO-001"      # 화면 설정 파일 쓰기 실패


@dataclass(frozen=True)
class AppError(Exception):
    """An error whose public representation never includes private detail."""

    code: str
    status_code: int = 500

    def __str__(self) -> str:
        return self.code

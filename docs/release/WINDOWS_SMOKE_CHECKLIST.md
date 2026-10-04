# Windows 11 x64 Release ZIP 수동 점검표

자동시험이 통과한 ZIP만 이 표로 점검한다. 각 항목은 비관리자 Windows 11 x64 계정에서 수행하고, 실패한 ZIP은 배포하지 않는다.

## 시험 정보

- 시험자:
- 시험 일시:
- Windows 버전/빌드:
- ZIP 파일명:
- Snapshot ID / schema version:
- SHA-256:

## 설치·시작

- [ ] 관리자 권한이 없는 계정으로 로그인했다.
- [ ] 이전 `PhramaProto` 프로세스가 없는 깨끗한 상태에서 시작했다.
- [ ] ZIP을 공백과 한글이 포함된 새 폴더에 풀었다.
- [ ] Windows Defender가 켜진 상태에서 `start.bat`을 실행했다.
- [ ] 첫 실행에서 uv 0.12.0과 CPython 3.12.13의 검증·설치가 완료됐다.
- [ ] 브라우저가 `http://127.0.0.1:<동적 포트>/`만 열었다.
- [ ] 방화벽에 외부 수신 허용을 요구하지 않았다.

## 데이터·기능

- [ ] 화면의 Snapshot ID, schema version, 노드 수, 관계 수가 manifest와 일치한다.
- [ ] SQLite 파일이 읽기 전용으로 열리며 앱 실행으로 DB 해시가 바뀌지 않는다.
- [ ] 지원하지 않는 schema ZIP은 `DB-VERSION-001`로 시작을 거부한다.
- [ ] 공급자별 API 키 입력 후 경구 고형제 질문으로 후보 표가 출력된다.
- [ ] 프로그램 종료·재실행 후 API 키가 다시 필요하다.

## 네트워크·장애

- [ ] 사내 proxy와 인증서가 있는 망에서 첫 실행 다운로드 결과를 기록했다.
- [ ] 인터넷이 끊긴 상태의 첫 실행은 `APP-START-001`과 bootstrap log 위치를 표시한다.
- [ ] 실행 후 공급자 연결을 끊으면 `LLM-UPSTREAM-001` 또는 `LLM-TIMEOUT-001`만 표시한다.
- [ ] 잘못된 키는 `LLM-AUTH-001`, 제한 응답은 `LLM-RATE-001`로 표시한다.
- [ ] `NO_PROXY=127.0.0.1,localhost` 환경에서도 health probe가 성공한다.

## 운영·복구

- [ ] 실행 중 `start.bat`을 다시 열면 새 서버를 만들지 않고 기존 화면을 연다.
- [ ] `%LOCALAPPDATA%\PhramaProto\logs\app.log`가 회전하며 질문, 응답, API 키가 없다.
- [ ] `/api/diagnostics`에 app/snapshot/schema/provider 상태와 공개 오류 코드만 보인다.
- [ ] 현재 폴더를 수정하지 않고 이전 검증 ZIP을 새 폴더에 풀어 롤백할 수 있다.
- [ ] 이전 ZIP과 새 ZIP을 각각 실행했을 때 각자의 Snapshot ID가 정확히 표시된다.

## 판정

- [ ] 모든 필수 항목 통과
- [ ] 실패 항목과 공개 오류 코드 기록 완료
- 최종 판정: `배포 가능 / 배포 금지`
- 비고:

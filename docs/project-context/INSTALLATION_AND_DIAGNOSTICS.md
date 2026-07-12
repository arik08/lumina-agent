> 생성일: 2026-07-12

# 설치, 운영 진단과 PostgreSQL 전환 준비

## 목적

이 문서는 Lumina를 Windows 또는 Linux에서 설치하고, 비밀값을 출력하지 않는 정적·연결 진단을 실행하며, 실제 운영 PostgreSQL 전환 전에 호환성을 확인하는 절차입니다. PostgreSQL 서버나 회사 인증서는 저장소가 자동 설치하지 않습니다.

## Windows 설치

일반 대화형 설치는 다음 진입점을 사용합니다.

```powershell
installer.bat
```

설치기는 dependency, data directory, `.env`, Alembic migration과 Frontend build를 준비합니다. 기존 `.env`는 통째로 덮어쓰지 않으며 사용자가 P-GPT 설정을 명시적으로 선택한 경우에만 해당 key를 갱신합니다. API Key, employee number와 company code는 숨김 입력으로 받고 완료 메시지나 오류에 값을 다시 표시하지 않습니다.

네트워크를 사용하지 않는 CI 설치 예시는 다음과 같습니다.

```powershell
installer.bat -NonInteractive -SkipPgpt -NoNetwork
```

`-NoNetwork`는 `uv`와 `npm`도 offline mode로 실행합니다. 필요한 dependency가 로컬 cache에 없으면 원격으로 조용히 전환하지 않고 설치가 실패합니다.

파일·DB·dependency를 변경하지 않는 installer dry-run은 다음과 같습니다.

```powershell
installer.bat -NonInteractive -SkipPgpt -NoNetwork -ValidateOnly
```

P-GPT를 CI에서 설정할 때 credential은 명령행 인자가 아니라 process environment 또는 기존 `.env`로 전달합니다.

```powershell
$env:PGPT_API_KEY = "<secret>"
$env:PGPT_EMPLOYEE_NO = "<secret>"
$env:PGPT_COMPANY_CODE = "30"
installer.bat -NonInteractive -ConfigurePgpt -NoNetwork -CompanyCaPath "C:\approved\company-ca.crt"
```

회사 CA가 필수인 profile은 `-RequireCompanyCa`를 함께 사용합니다. 설정된 파일이 없거나 PEM 검증에 실패하면 설치기는 성공처럼 종료하지 않습니다. 공개 CA와 회사 CA가 결합된 bundle은 `data/certs/runtime/combined-ca.pem`에 atomic write되고 Python, Node, curl, pip용 CA 환경에 동일하게 적용됩니다.

P-GPT 연결 검사는 명시적 opt-in입니다.

```powershell
installer.bat -ConfigurePgpt -PgptNetworkCheck
```

## Office/PDF Artifact 렌더 검증 도구

DOCX, XLSX와 PPTX의 실제 페이지 검증에는 **LibreOffice**와 **Poppler**가 모두 필요하고, PDF의 실제 페이지 검증에는 **Poppler**가 필요합니다.

| 형식 | 필수 로컬 실행 파일 | 검증 경로 |
|---|---|---|
| DOCX / XLSX / PPTX | `soffice` 또는 `libreoffice`, `pdftoppm` | 격리된 LibreOffice profile에서 PDF 변환 후 PNG 페이지 렌더 |
| PDF | `pdftoppm` | PDF를 PNG 페이지로 직접 렌더 |
| HTML | 없음 | 현재 단계에서는 active content, URL과 문서 구조만 검증하며 브라우저 렌더 검증은 보류 |

Windows에서는 LibreOffice와 Poppler의 실제 `.exe`가 `PATH`에 있어야 합니다. `.bat` 또는 `.cmd` wrapper는 shell 실행을 요구하므로 Artifact renderer로 인정하지 않습니다. Linux에서는 배포판의 LibreOffice와 `poppler-utils` package를 설치하고 다음 명령이 성공하는지 확인합니다.

```powershell
Get-Command soffice,pdftoppm
```

```bash
command -v libreoffice
command -v pdftoppm
```

설치기는 이 시스템 package를 자동 설치하거나 네트워크에서 내려받지 않습니다. 도구가 없으면 OpenXML/PDF 구조, 링크, 수식과 페이지 metadata 검증은 계속하지만 결과를 완전 통과로 표시하지 않습니다. `validationStatus`는 `structural_passed`, `renderVerified`는 `false`, warnings에는 `render_verification_pending`과 누락된 renderer가 기록됩니다. 운영 배포 전에는 실제 배포 이미지 또는 서버에서 두 실행 파일을 설치하고 조건부 integration test가 통과하는지 확인해야 합니다.

LibreOffice는 매 검증마다 새 임시 user profile과 최고 macro 보안 수준으로 실행하며 shell, 사용자 profile, application secret과 표준 출력·오류 출력을 상속하지 않습니다. 입력과 생성 파일은 관리되는 임시 디렉터리 밖으로 나갈 수 없고 timeout 뒤 process tree와 임시 디렉터리를 정리합니다. 매크로가 포함된 OpenXML package와 외부 resource relationship은 렌더 전에 거부합니다.

## Python 진단 CLI

기본 진단은 네트워크를 사용하지 않습니다.

```powershell
uv run --project apps/server python -m lumina.diagnostics --no-network
uv run --project apps/server python -m lumina.diagnostics --no-network --pgpt
uv run --project apps/server python -m lumina.diagnostics --no-network --database
```

P-GPT 연결 진단은 다음처럼 별도로 opt-in합니다.

```powershell
uv run --project apps/server python -m lumina.diagnostics --network --pgpt
```

결과는 public CA, company CA, combined trust, endpoint configuration, credential completeness, DNS, TCP connect, TLS, authentication, endpoint와 provider 단계로 분리됩니다. credential, Authorization envelope, endpoint URL과 응답 본문은 출력하지 않습니다. 실패 단계가 있으면 process exit code는 0이 아닙니다.

Linux에서도 같은 module을 사용합니다.

```bash
uv run --project apps/server python -m lumina.diagnostics --no-network --pgpt \
  --company-ca /run/secrets/lumina/company-ca.crt --require-company-ca
```

## PostgreSQL offline 호환성

실제 서버 없이 PostgreSQL dialect로 Alembic head SQL, JSON column과 partial index를 확인합니다.

```powershell
powershell -ExecutionPolicy Bypass -File devtools/check_postgres_compat.ps1
```

이 검사는 compile 전용 placeholder URL을 사용하며 PostgreSQL에 연결하지 않습니다.

## 개발 검증

Backend 회귀 테스트는 저장소 루트에서 다음 명령으로 실행합니다. migration 검증은 특정 과거 revision을 완료 상태로 가정하지 않고 repository의 현재 Alembic head까지 올라간 상태를 확인합니다.

```powershell
$env:PYTHONPYCACHEPREFIX = "$PWD\.cache\pycache"
uv run --project apps/server pytest -c apps/server/pyproject.toml
```

Frontend는 빠른 Node 단위 테스트를 먼저 실행한 뒤 TypeScript와 production bundle을 검증합니다.

```powershell
npm --prefix apps/web test
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

Frontend 단위 테스트에는 UI helper와 주요 화면의 소스 계약 검사가 포함됩니다. 실제 UI를 만들거나 수정한 경우에는 이 결과만으로 완료하지 않고 Codex 앱 브라우저에서 주요 화면, 텍스트 겹침·잘림과 콘솔 오류를 직접 확인합니다.

전체 Backend 테스트에서 다음 항목은 로컬 실행 조건이 없으면 skip될 수 있습니다.

- PDF 실제 렌더 검증: 실행 가능한 `pdftoppm` 필요
- DOCX·XLSX·PPTX 실제 렌더 검증: LibreOffice와 `pdftoppm` 필요
- PostgreSQL migration 통합 테스트: 전용 `LUMINA_TEST_POSTGRES_URL`과 `LUMINA_TEST_POSTGRES_ALLOW_MIGRATIONS=1` 필요

브라우저 QA나 API 검증을 위해 서비스를 실행할 때는 사용자 기본 포트 `5252`, `5253`을 점유하거나 종료하지 않습니다. 기본 테스트 포트는 Frontend `15252`, Backend `15253`이며 이미 사용 중이면 `5252`, `5253`을 제외한 다른 빈 포트를 선택합니다. 테스트가 시작한 process만 종료하고 기존 listener는 유지합니다.

## 운영 DATABASE_URL smoke

반드시 빈 전용 검증 DB 또는 승인된 migration 대상에만 실행합니다. 실제 운영 credential은 명령행에 쓰지 않고 process environment나 Secret mount로 전달합니다.

```powershell
$env:DATABASE_URL = "postgresql+psycopg://<user>:<secret>@<host>/<dedicated-db>"
powershell -ExecutionPolicy Bypass -File devtools/check_postgres_compat.ps1 -Connect
```

Linux:

```bash
export DATABASE_URL='postgresql+psycopg://<user>:<secret>@<host>/<dedicated-db>'
uv run --project apps/server python -m lumina.diagnostics \
  --network --database --require-postgres
```

연결 smoke는 `SELECT 1`과 현재 Alembic revision이 repository head인지 확인할 뿐 migration을 자동 실행하지 않습니다. migration은 별도로 다음 명령을 사용합니다.

```powershell
uv run --project apps/server alembic -c apps/server/alembic.ini upgrade head
```

CI에 전용 PostgreSQL이 있을 때만 `LUMINA_TEST_POSTGRES_URL`과 `LUMINA_TEST_POSTGRES_ALLOW_MIGRATIONS=1`을 함께 설정하면 migration을 적용하는 optional integration test가 활성화됩니다. URL만 설정해서는 실행되지 않으며, 이 변수는 절대로 일반 운영 DB를 가리키면 안 됩니다.

## Health와 로그

- `GET /api/health/live`: process와 local executor 생존 상태
- `GET /api/health/ready`: DB `SELECT 1`과 요청 처리 준비 상태
- HTTP log는 request ID와 route template을 구조화 JSON으로 남기고 password, token, employee/company identifier와 Secret reference를 redaction합니다.
- P-GPT와 PostgreSQL 진단은 URL, header, credential과 원문 응답을 log 또는 Run event에 넣지 않습니다.

실제 P-GPT network, 회사 proxy/TLS inspection과 PostgreSQL server 검증은 해당 환경의 credential과 명시적 opt-in이 있을 때만 완료할 수 있습니다.

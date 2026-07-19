# Lumina 개발 도구

이 폴더에는 Lumina의 Windows 설치·실행·종료, 진단, 테스트와 CodeGraph 유지보수에 사용하는 PowerShell 스크립트가 있습니다. 일반 사용자는 저장소 루트의 `installer.bat`, `run_lumina.bat`, `run_lumina_dev.bat`를 사용하고, 아래 `.ps1` 파일은 진단이나 개발 자동화가 필요할 때 직접 실행합니다.

## 빠른 명령

```powershell
# 실행 중인 이 저장소의 Lumina Frontend, Backend와 supervisor 모두 종료
powershell -NoProfile -ExecutionPolicy Bypass -File devtools/stop_lumina.ps1

# 실제 종료 대상을 변경 없이 미리 확인
powershell -NoProfile -ExecutionPolicy Bypass -File devtools/stop_lumina.ps1 -WhatIf

# PostgreSQL dialect 호환성만 오프라인으로 검사
powershell -NoProfile -ExecutionPolicy Bypass -File devtools/check_postgres_compat.ps1

# CodeGraph 상태에 맞춰 증분 갱신 또는 재인덱싱
powershell -NoProfile -ExecutionPolicy Bypass -File devtools/update_codegraph.ps1
```

## 스크립트 목록

### `check_postgres_compat.ps1`

SQLite 개발 환경에서 PostgreSQL 이전 가능성을 확인하는 진단 진입점입니다. 기본 실행은 임시 PostgreSQL URL을 사용해 migration과 dialect 호환성을 오프라인으로 검사하며 실제 DB에는 연결하지 않습니다. `-Connect`를 주면 `DATABASE_URL`의 전용 검증 DB에 실제로 연결하고, `-EnvFile`로 읽을 환경 파일을 지정할 수 있습니다.

### `install_lumina.ps1`

`installer.bat`가 호출하는 실제 설치기입니다. Python 3.13·Node.js·npm·uv 요구 조건을 확인하고, `.env`와 데이터 디렉터리 준비, Python/Frontend 의존성 설치, 회사 CA trust bundle 생성, Alembic migration, Frontend build를 수행합니다. Codex Provider 선택 설치(`-InstallCodex`/`-SkipCodex`), P-GPT 설정, 회사 CA 필수 여부, 네트워크 차단 설치, 파일을 바꾸지 않는 `-ValidateOnly` 같은 설치 옵션도 이 파일이 처리합니다. 일반 설치는 이 파일보다 루트의 `installer.bat` 사용을 권장합니다.

### `LuminaCache.Env.ps1`

Python bytecode, mypy, Ruff, pytest cache를 저장소의 `.cache/` 아래로 모으는 공용 환경 설정 helper입니다. 설치기, 런처와 PostgreSQL 진단이 dot-source해서 사용하며 단독 실행용이 아닙니다.

### `LuminaInstall.Env.ps1`

`.env`에서 값을 안전하게 읽고 갱신하는 `Get-LuminaDotEnvValue`, `Set-LuminaDotEnvValue` helper를 제공합니다. 따옴표와 역슬래시를 처리하고 UTF-8(BOM 없음)으로 기록합니다. 설치기가 내부적으로 사용하며 단독 실행용이 아닙니다.

### `LuminaInstall.Frontend.ps1`

Windows에서 실행 중인 Vite/Node가 `node_modules`의 native `.node` 파일을 잠갔는지 검사합니다. 잠긴 파일이 있으면 `npm ci` 전에 설치를 중단하고 관련 Node PID 또는 종료 안내를 표시해 불완전한 의존성 교체를 막습니다. 설치기가 내부적으로 사용하며 단독 실행용이 아닙니다.

### `LuminaLauncher.Input.ps1`

런처의 수동 하드 리셋 입력을 판별하는 공용 helper입니다. `r`, `R`, 한글 IME의 `ㄱ`, 물리 R 키를 같은 재시작 요청으로 처리합니다. `run_lumina.ps1`, 실패 후 재시작 프롬프트와 테스트가 함께 사용합니다.

### `run_lumina.ps1`

`run_lumina.bat`와 `run_lumina_dev.bat`의 실제 Windows supervisor입니다. `.env`의 Frontend/Backend 포트를 읽고 production 또는 `-Development` 모드로 프로세스를 시작합니다. readiness와 프로세스 종료를 감시하고, 장애 시 backoff를 적용해 자동 복구하며, `r`/`R`/`ㄱ` 입력 시 Frontend와 Backend를 하드 리셋합니다. 로그, PID, 원자적 상태 JSON과 monitoring event도 `data/logs/`에 관리합니다. 기존 포트가 다른 프로그램 소유이면 그 프로세스를 종료하지 않고 오류로 중단합니다.

### `run_lumina.tests.ps1`

Windows 런처의 회귀 테스트입니다. 하드 리셋 키, child process 환경 격리, Lumina 프로세스 식별, process-tree 종료, supervisor PID/시작 시각 검증, 준비 단계와 자동 복구 정책, 로그 보존, 상태 JSON의 원자성과 secret 마스킹을 검사합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File devtools/run_lumina.tests.ps1
```

### `stop_lumina.ps1`

이 저장소에서 백그라운드로 실행 중인 Lumina production/development launcher, PowerShell supervisor, FastAPI Backend와 Vite Frontend를 모두 종료합니다. 포트 번호나 실행 파일 이름만으로 판단하지 않고 저장소의 정확한 launcher·server·Vite 경로와 명령행을 함께 확인하므로, 다른 프로젝트의 Python/Node 프로세스와 다른 프로그램이 소유한 포트는 건드리지 않습니다. 가장 위의 Lumina 부모 프로세스에서 자식 트리를 종료한 뒤 남은 프로세스를 다시 확인하고, 종료가 확인되면 오래된 supervisor PID 파일을 정리합니다. `-WhatIf`로 대상을 미리 볼 수 있습니다.

### `stop_lumina.tests.ps1`

종료 스크립트의 회귀 테스트입니다. 이 저장소의 launcher/Backend/Frontend만 식별하는지, 같은 module 이름을 쓰는 다른 경로와 일반 개발용 Python/Node를 제외하는지, 중첩된 프로세스를 하나의 root로 합치는지, 실제 테스트 parent/child process tree가 모두 종료되는지 검사합니다. 실행 중인 Lumina runtime 자체는 종료하지 않습니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File devtools/stop_lumina.tests.ps1
```

### `update_codegraph.ps1`

저장소의 CodeGraph 인덱스를 현재 CLI 상태에 맞춰 갱신합니다. 인덱스가 없으면 초기화하고, extraction version 변경으로 재인덱싱이 권장되면 전체 index를 다시 만들며, 그 외에는 증분 sync를 실행합니다. 마지막에 JSON 상태와 `.codegraph/codegraph.db` 갱신 시각을 출력합니다.

### `Wait-LuminaLauncherRestart.ps1`

`run_lumina_dev.bat`가 개발 런처 종료 후 호출하는 단일 키 입력 helper입니다. 공용 하드 리셋 키가 입력되면 exit code `75`를 반환해 batch launcher가 다시 시작하도록 하고, 다른 키나 입력할 수 없는 detached console에서는 정상 종료합니다. 단독 실행용이 아닙니다.

## 안전 원칙

- `stop_lumina.ps1`은 이 저장소 경로가 명령행에서 확인되는 Lumina runtime만 종료합니다. 일반적인 `python.exe`, `node.exe`, 포트 listener 전체를 일괄 종료하지 않습니다.
- 실제 운영 DB에 연결하는 `check_postgres_compat.ps1 -Connect`는 비어 있거나 migration이 승인된 전용 검증 DB에서만 실행합니다.
- 설치와 진단 명령에 API key, 비밀번호, 인증 토큰을 인자로 넣지 말고 process environment 또는 Git에서 제외된 `.env`를 사용합니다.
- 테스트 중에는 사용자 기본 포트 `5252`, `5253`을 점유하거나 종료하지 않습니다. 격리 포트 `15252`, `15253` 또는 다른 빈 포트를 사용합니다.

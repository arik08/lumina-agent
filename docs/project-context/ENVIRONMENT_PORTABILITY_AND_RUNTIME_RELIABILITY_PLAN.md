# Lumina 환경 이식성·시작·실행 신뢰성 개선안

> 작성일: 2026-07-14  
> 상태: 구현 전 설계 기준  
> 비교 대상: 현재 Lumina, `.examples/MyHarness`, `.examples/hermes-agent`  
> 목표: 집·회사·개발 PC가 달라도 설치 결과와 실행 상태를 설명할 수 있고, 일시 장애는 복구하되 영구 오류는 빠르고 정확하게 멈추는 Lumina

## 1. 결론

현재 반복되는 문제의 중심은 인증서, 포트, Provider 중 어느 하나가 아니다. **설치·업데이트·시작·준비 판정·Provider 연결·Run 복구의 책임과 성공 조건이 하나의 신뢰성 계약으로 묶여 있지 않은 것**이 근본 원인이다.

현재 코드에서 확인한 대표적인 실패 사슬은 다음과 같다.

```text
run_lumina.ps1 실행
  ├─ 매번 DB migration
  ├─ production이면 매번 Frontend build
  ├─ Backend 시작
  │    └─ 모든 환경에서 Codex warmup을 먼저 기다림
  ├─ /api/health/ready
  │    └─ DB만 확인하고 executor="ready"를 고정 반환
  ├─ 사용자가 실제 P-GPT/Codex 요청
  │    └─ 이때 처음 CA·proxy·credential·실제 transport 문제가 드러날 수 있음
  └─ 실패
       ├─ transient 여부와 관계없이 Run 실패 처리 가능
       └─ supervisor는 1초 후 전체 시작 절차 반복
```

이 구조에서는 개별 버그를 여러 번 고쳐도 다음 환경에서 다른 단계가 무너진다. 따라서 이번 개선은 특정 오류 패치가 아니라 아래 다섯 계약을 먼저 고정해야 한다.

1. **Prepare와 Run을 분리한다.** 설치·의존성 동기화·빌드·migration은 준비 단계이고, 정상 실행과 자동 재시작에는 포함하지 않는다.
2. **Ready는 실제 상태만 말한다.** DB, schema, Worker, trust, 선택된 필수 Provider 경로 중 하나라도 준비되지 않았으면 전역 readiness가 성공하면 안 된다.
3. **환경 차이를 profile로 명시한다.** 집과 회사의 CA·proxy·필수 Provider 정책을 우연한 파일 발견과 흩어진 환경 변수에 맡기지 않는다.
4. **일시 오류와 영구 오류를 다르게 다룬다.** retryable 정보, 응답 시작 여부, `Retry-After`를 기준으로 bounded retry를 수행하고 설정·인증 오류는 즉시 멈춘다.
5. **모든 실패는 한 번에 진단 가능해야 한다.** 사용자가 로그 여러 개를 찾아다니지 않아도 마지막 실패 단계, 안정적인 오류 코드, 해결 명령을 확인할 수 있어야 한다.

## 2. 조사 범위와 판단 기준

### 2.1 직접 확인한 Lumina 경로

- 설치: `installer.bat`, `devtools/install_lumina.ps1`
- 실행·감시: `devtools/run_lumina.ps1`, `devtools/run_lumina.tests.ps1`
- 애플리케이션 수명주기·health: `apps/server/src/lumina/main.py`
- Worker·Run 실패 처리: `apps/server/src/lumina/agent/executor.py`
- Provider 오류 계약: `apps/server/src/lumina/providers/errors.py`
- TLS/CA: `apps/server/src/lumina/http_client.py`
- P-GPT transport: `apps/server/src/lumina/providers/pgpt/adapter.py`
- 설정: `apps/server/src/lumina/config.py`
- 기존 기준 문서: `INSTALLATION_AND_DIAGNOSTICS.md`, `PGPT_CORPORATE_NETWORK.md`, `AGENT_LOOP.md`, `LUMINA_DETAILED_DESIGN.md`

### 2.2 직접 비교한 MyHarness 경로

- `run_myharness_web.bat`
- `scripts/run_myharness_web_server.ps1`
- `src/myharness/__init__.py`
- `src/myharness/utils/certificates.py`
- `src/myharness/config/settings.py`
- `src/myharness/api/openai_client.py`

### 2.3 직접 비교한 HERMES 경로

- `apps/desktop/electron/backend-command.ts`
- `apps/desktop/electron/backend-ready.ts`
- `apps/desktop/electron/backend-probes.ts`
- `apps/desktop/electron/gateway-ws-probe.ts`
- `hermes_cli/doctor.py`
- `hermes_constants.py`
- `hermes_logging.py`
- `scripts/install.ps1`
- 루트 및 Desktop `AGENTS.md`의 운영 계약

이 문서의 `확인`은 현재 저장소 코드로 증명한 사실을 뜻한다. `가설`은 회사망·proxy·실제 credential이 있어야 최종 재현할 수 있는 항목이다. 가설을 확인된 사실처럼 취급하지 않는다.

## 3. 비교 결과

| 영역 | 현재 Lumina | MyHarness에서 유효한 점 | HERMES에서 유효한 점 | Lumina 결정 |
|---|---|---|---|---|
| 설치와 실행 | 설치 스크립트가 있으나 production 실행 때도 build·migration 수행 | 의존성과 `dist/index.html`이 없을 때만 설치·빌드 | installer가 단계별 JSON 결과와 소요 시간을 남김 | 설치/업데이트와 실행을 완전히 분리하고 설치 manifest를 남긴다 |
| 런타임 선택 | `uv`, Node, CWD와 `.env`가 사실상 전제 | 여러 Python 후보를 실제 import 가능 여부로 확인 | 후보 파일 존재가 아니라 import/`--version` probe로 검증 | 실행 파일 경로와 버전을 manifest에 고정하고 시작 전에 빠르게 재검증한다 |
| 환경 상태 | 단일 `.env`에 배포 동작과 secret이 혼재 | 앱 로컬 `.myharness`와 active provider profile 사용 | `HERMES_HOME`/profile을 단일 resolver로 정하고 config와 secret을 분리 | `home`/`corporate` deployment profile을 도입하고 secret은 별도 유지한다 |
| CA 초기화 | transport 생성 시 lazy 초기화, 기본 root는 `Path.cwd()` | package import 초기에 회사 CA를 적용하고 집에서는 없으면 건너뜀 | doctor와 installer가 cert/runtime을 명시적으로 점검 | startup에서 선택 profile의 trust를 1회 초기화하고 모든 client가 같은 결과를 사용한다 |
| readiness | DB 질의 후 executor를 고정 `ready`로 반환 | 직접 대응 구현은 제한적 | 실제 runtime leg와 WebSocket leg까지 검사하고 불일치를 노출 | global ready와 capability probe를 분리하되 둘 다 실제 경로를 검사한다 |
| 시작 대기 | 60초 고정 | 단순 supervisor | Windows cold start를 고려한 90초 announcement와 child exit/error 동시 감시 | 측정 기반 단계별 deadline을 사용하고 `ready` announcement를 명시한다 |
| Provider retry | 오류에 `retryable`이 있으나 상위 Run 실패 경로에서 소실 가능 | 429/5xx/timeout을 bounded retry하고 사용자에게 retry event 표시 | 복구 단계와 exhausted 상태를 분리 | 공용 retry policy를 만들고 응답 전까지만 자동 재요청한다 |
| supervisor | 영구 오류도 1초마다 무한 재시작 | 3초 재시작이지만 build는 반복하지 않음 | bounded recovery와 명시적 degraded/exhausted 상태를 중시 | 지수 backoff·restart budget·circuit open을 적용한다 |
| 진단 | installer validate와 operational diagnostics가 있으나 실제 실행 계약을 모두 덮지 않음 | 시작 화면에 경로·로그·실패 원인을 비교적 직접 표시 | 광범위한 `doctor --fix`, profile-aware rotating log | `lumina doctor`와 redacted support bundle을 제품 계약으로 만든다 |
| 호환성 | launcher와 설치기가 각자 도구를 해석 | 현재 환경에서 동작하는 실용적 fallback | 새 명령 실패 시에만 좁고 테스트된 legacy fallback | fallback은 한 곳에서만, 실제 probe와 제거 기한을 포함해 관리한다 |

## 4. 확인된 근본 원인

### P0-1. 정상 실행과 복구 루프 안에서 build와 migration이 반복된다

**확인 근거**

- `devtools/run_lumina.ps1:444-456`의 `Start-LuminaProcesses`가 시작할 때마다 `alembic upgrade head`를 실행한다.
- production이면 같은 함수에서 `npm run build`도 매번 실행한다.
- `devtools/run_lumina.ps1:591-599`는 시작 또는 health 실패 후 1초만 기다리고 같은 시작 절차를 반복한다.

**증상 연결**

- 집에서 시작이 오래 걸리고, 일시적인 Backend 실패가 전체 build 비용으로 증폭된다.
- Node/npm/파일 잠금/백신 검사 중 하나가 불안정하면 Backend 문제처럼 보인다.
- 영구 설정 오류일 때 CPU·disk·로그를 계속 소비하면서 진짜 첫 오류가 뒤로 밀린다.

**왜 기존 국소 수정만으로 부족한가**

프로세스 정리 속도와 포트 충돌을 고쳐도 재시작이 비싼 작업을 포함하는 한 체감 지연은 남는다. 시작 경로의 책임을 바꾸지 않고 timeout만 늘리면 실패 판정이 늦어질 뿐이다.

**목표 계약**

- `install/update`: dependency sync, frontend build, migration, manifest 기록을 담당한다.
- `run`: manifest/schema/import를 읽기 전용으로 검증하고 process를 시작한다.
- schema가 뒤처졌으면 자동 재시작 루프에서 migration하지 않고 `UPDATE_REQUIRED`로 한 번 멈춘다.
- 개발 모드의 자동 migration/build는 별도 명시 옵션으로만 허용한다.

### P0-2. `/api/health/ready`가 실제 Worker 준비 상태를 증명하지 않는다

**확인 근거**

- `apps/server/src/lumina/main.py:188-192`는 DB `SELECT 1` 뒤 `executor: "ready"`를 고정 반환한다.
- 같은 파일의 liveness 응답은 `local_run_executor.started`를 실제로 읽으므로 두 endpoint의 의미가 서로 다르다.
- 현재 launcher의 healthy 판정은 이 readiness와 Frontend HTTP 성공을 사용한다.

**증상 연결**

화면은 열리지만 첫 질문에서만 오류가 나거나, 회사에서 “서버는 정상”인데 P-GPT가 동작하지 않는 거짓 양성이 가능하다.

**목표 계약**

```text
/api/health/live
  프로세스 event loop가 살아 있는가

/api/health/startup
  phase, elapsed_ms, last_error_code, progress를 반환

/api/health/ready
  DB 연결 + schema head + executor started + recovery 완료
  + active deployment profile이 요구한 trust/capability 준비 완료

/api/health/capabilities/{provider}
  선택 Provider의 실제 DNS/TLS/auth/request 또는 stream leg 검사
```

선택되지 않은 optional Provider 장애는 전역 readiness를 막지 않는다. 반대로 corporate profile이 P-GPT를 필수로 선언했다면 단순 HTTP health가 아니라 실제 P-GPT leg가 통과해야 한다.

### P0-3. Provider가 알려 준 `retryable` 의미가 Run 실패 경계에서 사라진다

**확인 근거**

- `apps/server/src/lumina/providers/errors.py:12-22`의 `ProviderRequestError`는 `stage`, `status_code`, `retryable`을 가진다.
- 그러나 `apps/server/src/lumina/agent/executor.py:447-459`의 상위 실행 경계는 모든 `ProviderError`를 설정 오류 또는 요청 오류로 바꾼 뒤 Run을 실패시킨다.
- Codex adapter 일부에는 “아직 출력이 없을 때 한 번 재시도”하는 국소 정책이 있지만 Provider 공통 계약은 아니다.

**증상 연결**

집의 불안정한 네트워크나 회사 proxy의 일시 429/502/503/timeout이 사용자에게 즉시 최종 실패로 보일 수 있다. 반대로 launcher의 무한 재시작은 Provider 요청 하나가 아니라 서비스 전체를 다시 띄우므로 복구 범위가 너무 크다.

**목표 계약**

- 공용 `ProviderRetryPolicy`가 `stage`, HTTP status, `retryable`, 출력 시작 여부를 함께 판단한다.
- timeout/transport/429/502/503은 최대 2회, jitter를 포함한 bounded backoff로 재시도한다.
- 429는 `Retry-After`를 우선한다.
- configuration/auth/permission/invalid request는 재시도하지 않는다.
- 사용자에게 `retry_scheduled`, attempt, next_delay, stable error code를 Run event로 보여 준다.
- **첫 token/event 이후에는 요청 전체를 자동 재전송하지 않는다.** 부분 응답과 tool side effect 중복을 막기 위해 checkpoint/resume가 가능할 때만 이어가고, 아니면 부분 결과를 보존한 채 명확히 중단한다.

### P0-4. 집과 회사의 차이가 명시적 profile이 아니라 파일·환경 변수 발견 순서에 의존한다

**확인 근거**

- `apps/server/src/lumina/config.py`의 단일 Settings가 runtime 동작, Provider 선택값, secret 환경 변수를 함께 읽는다.
- `apps/server/src/lumina/http_client.py:91-123`은 기본 root를 `Path.cwd()`로 잡고 그 위치의 `.env`와 `data/certs`를 해석한다.
- 현재 공식 launcher는 repository root를 working directory로 주므로 동작하지만, 서비스 등록·다른 launcher·다른 CWD에서는 동일 설정이 다른 경로로 해석될 수 있다.
- trust 초기화는 `apps/server/src/lumina/providers/pgpt/adapter.py:102`처럼 실제 transport가 필요할 때 lazy하게 일어난다.

**가설과 확인 방법**

- 회사에서만 실패하는 일부 사례는 stale absolute CA path, proxy, DNS, TLS, auth 중 하나일 가능성이 높다.
- 현재 자료만으로 어느 하나를 확정할 수 없다. corporate profile로 `doctor --network`를 실행해 `dns → tcp → tls → auth → request → stream` 단계별로 확인해야 한다.

**목표 계약**

- active deployment profile은 `LUMINA_PROFILE` 하나로 선택하고 기본값은 `home`이다.
- 비밀이 아닌 배포 설정은 `data/config/runtime.yaml`에 저장한다. 이 파일은 Git 제외 대상이며, 버전 관리되는 `config/runtime.example.yaml`을 schema 예제로 둔다.
- API key·employee number·token은 기존 secret 저장소/환경 변수에 남기고 runtime yaml에는 값이 아니라 secret reference만 둔다.
- deployment profile은 CA·proxy·필수 capability·bind 같은 **시작 전 환경 정책**만 소유한다. 사용자별 Provider·Model·Effort 선택의 원본은 기존 원칙대로 서버 DB이며 runtime yaml에 복제하지 않는다.
- 경로 해석은 CWD가 아니라 하나의 `LuminaPaths` resolver가 담당한다.
- profile별 기본과 fallback은 다음처럼 고정한다.

| 항목 | `home` 기본 | `corporate` 기본 |
|---|---|---|
| company CA | optional, 없으면 public CA | P-GPT가 필수면 required |
| P-GPT | optional | required 또는 관리자가 명시한 optional |
| proxy | 없음 | profile의 명시 설정만 사용 |
| Web Search | optional capability | allowlist/proxy 진단 후 활성 |
| 실패 fallback | public CA로 정상 진행 | required CA/P-GPT 실패를 숨기지 않고 not-ready |

corporate에서 home으로 조용히 fallback하거나, stale CA 경로 오류를 “회사 CA 없음”으로 삼켜서는 안 된다.

### P0-5. 선택 Provider와 무관하게 Codex warmup이 전체 Backend 시작 경로를 점유한다

**확인 근거**

- `apps/server/src/lumina/agent/executor.py:309-317`은 test 외 모든 환경에서 Worker recovery 전에 `codex_provider.warmup()`을 기다린다.
- 실패는 warning으로 건너뛰지만 느린 warmup은 앱 lifespan 완료와 readiness 도달을 지연시킨다.

**증상 연결**

P-GPT만 사용하는 회사 환경이나 다른 Provider를 선택한 환경도 Codex App Server/model discovery 지연을 함께 부담한다. cache hit와 실제 startup latency가 다르게 보이는 이유가 된다.

**목표 계약**

- active profile과 최근 사용 Provider만 background warmup 후보가 된다.
- Worker recovery와 HTTP bind를 warmup에서 분리한다.
- optional warmup은 global readiness를 막지 않고 startup phase/metric에 별도로 보인다.
- required Provider의 warmup 실패만 해당 capability 또는 profile readiness를 막는다.

### P1-1. installer 성공 여부를 다음 실행이 증명할 manifest가 없다

현재 installer는 도구 확인, `uv sync`, npm install/build, migration, diagnostics를 수행한다. 그러나 다음 실행은 “어느 Python/Node를 사용했고 lock/build/schema가 무엇이었는지”를 하나의 결과물로 확인하지 않는다.

다음과 같은 비밀 없는 `install-manifest.json`을 `data/runtime/`에 원자적으로 기록해야 한다.

```json
{
  "schema_version": 1,
  "lumina_version": "0.1.0",
  "source_revision": "<git-or-release-revision>",
  "uv_lock_digest": "<sha256>",
  "python_executable": "<normalized-path>",
  "python_version": "3.x",
  "node_executable": "<normalized-path>",
  "node_version": "20.x",
  "frontend_build_digest": "<sha256>",
  "alembic_head": "<revision>",
  "profile": "home",
  "completed_at": "<utc>"
}
```

정상 실행은 이 manifest를 수 밀리초 수준으로 검증한다. 불일치가 있으면 임의로 설치를 시작하지 않고 `INSTALL_INCOMPLETE`, `RUNTIME_CHANGED`, `FRONTEND_BUILD_STALE`, `UPDATE_REQUIRED` 중 정확한 코드로 멈춘다.

### P1-2. 기존 launcher 테스트가 운영 실패 계약을 보호하지 않는다

`devtools/run_lumina.tests.ps1`은 현재 다음을 잘 보호한다.

- IME에서도 수동 reset 키 인식
- 관리 대상 process 판별
- 빠른 process tree 종료
- PID 재사용을 피하는 supervisor identity
- reset 시 Frontend/Backend 재시작

그러나 다음은 아직 계약 테스트가 아니다.

- 정상 `run`에서 npm build와 migration을 호출하지 않는지
- 영구 오류 시 restart budget이 소진되고 멈추는지
- transient crash에만 backoff 재시작하는지
- ready가 실제 executor 상태를 반영하는지
- foreign process가 포트를 점유했을 때 종료하지 않는지
- 60초를 넘는 정상 cold start를 중복 process로 오판하지 않는지

## 5. 목표 구조

### 5.1 Prepare/Run 경계

```text
install 또는 update (명시적, 변경 가능)
  resolve runtime
  → sync locked dependencies
  → build frontend once
  → migrate once
  → offline diagnostics
  → optional profile network diagnostics
  → atomic install manifest

run (빠름, 원칙적으로 읽기 전용)
  load paths/profile
  → validate manifest/import/schema/ports
  → start backend
  → backend announces bound port + startup phase
  → start/serve frontend
  → actual readiness
  → bounded supervision
```

release 배포에서는 Frontend build 결과를 release artifact에 포함해 회사 PC에서 npm build가 필요 없게 하는 것이 최종 형태다. source 개발 설치만 build를 허용한다.

### 5.2 Startup state machine

```text
PREFLIGHT
  ├─ failure: CONFIGURATION_FAILED / UPDATE_REQUIRED → 재시작하지 않음
  ↓
BINDING
  ├─ failure: PORT_IN_USE_FOREIGN → 재시작하지 않음
  ↓
RECOVERING_WORKER
  ├─ transient DB lock → bounded retry
  ↓
INITIALIZING_TRUST
  ├─ required CA failure → not-ready, 재시작하지 않음
  ↓
CHECKING_REQUIRED_CAPABILITIES
  ├─ transient network → bounded retry/degraded
  ├─ auth failure → 재시작하지 않음
  ↓
READY
  ├─ child crash → supervisor budget 안에서 재시작
  └─ 반복 crash → EXHAUSTED, 사용자 명시 재시도 대기
```

각 phase는 `started_at`, `elapsed_ms`, `attempt`, `error_code`, `help_action`을 구조화 로그와 `/api/health/startup`에 동일하게 기록한다.

### 5.3 Supervisor 정책

- restart delay: `1s → 2s → 5s → 10s`, jitter 포함
- budget 초안: 5분 동안 최대 3회; 성공적으로 10분 유지하면 budget reset
- configuration/auth/schema/foreign-port 오류는 0회 재시작
- child crash, 일시 DB lock 등만 budget 대상
- budget 소진 시 창을 닫거나 무한 loop하지 말고 `EXHAUSTED` 상태와 마지막 실패·로그·`lumina doctor` 명령을 보여 준다.
- `R` 수동 재시도는 budget을 명시적으로 초기화하되 build/migration은 수행하지 않는다.
- 직접 띄운 process와 identity가 확인된 이전 Lumina supervisor만 종료한다. 포트를 쓴다는 이유만으로 foreign process를 종료하지 않는다.
- desktop-managed local profile은 HERMES처럼 `port 0`과 ready announcement를 사용할 수 있다. LAN 고정 주소가 필요한 profile은 명시 포트를 유지하며 충돌 시 자동으로 다른 포트를 골라 공유 URL을 바꾸지 않는다.

### 5.4 설정과 path의 단일 원본

`LuminaPaths`는 다음 위치를 한 번만 결정한다.

- install root
- runtime/data/log/cache root
- active profile config
- company CA와 generated bundle
- frontend distribution
- supervisor PID/ready file

우선순위는 `명시 CLI → 단일 profile selector → runtime config → platform default`로 고정한다. 환경 변수마다 별도 fallback을 만들지 않는다. 후보 경로는 파일 존재만 확인하지 말고 필요한 import, version, write permission 또는 handshake까지 검증한 뒤 선택한다.

### 5.5 Trust와 HTTP client의 단일 초기화

- app bootstrap에서 `TrustManager.initialize(profile=...)`를 정확히 한 번 실행한다.
- 결과 `TrustProfile`과 `ssl.SSLContext`를 process scope dependency로 등록한다.
- Provider, MCP, Web Search, readiness probe가 같은 context와 같은 settings snapshot을 사용한다.
- Python, Node, npm이 필요한 설치 단계는 같은 trust source로부터 각 runtime용 환경을 파생한다.
- TLS 오류를 `verify=False`로 우회하지 않는다.
- `TLS_COMPAT_MODE`는 profile의 명시 설정과 진단 근거가 있을 때만 사용하고, 적용 여부를 secret 없이 기록한다.

### 5.6 Provider 복구 경계

| 오류 | 자동 retry | 전역 서비스 restart | 사용자 표시 |
|---|---:|---:|---|
| DNS/transport/timeout, 출력 전 | 최대 2회 | 아니요 | attempt와 다음 대기 |
| 429 | `Retry-After` 기반 최대 2회 | 아니요 | rate limit |
| 502/503, 출력 전 | 최대 2회 | 아니요 | upstream unavailable |
| TLS certificate | 아니요 | 아니요 | trust 단계와 CA 경로 출처 |
| 401/403 | 아니요 | 아니요 | credential/permission |
| 잘못된 model/request | 아니요 | 아니요 | configuration/request |
| 출력 후 연결 종료 | blind retry 금지 | 아니요 | 부분 결과 보존 + resume 가능 여부 |
| Worker process crash | Run recovery 계약 적용 | budget 내 Backend만 | recovered/interrupted |

Provider fallback은 “실패하면 아무 모델이나 사용”이 아니다. 조직 정책과 데이터 경계를 바꿀 수 있으므로 관리자가 허용한 fallback chain이 있고 사용자에게 Provider 변경이 보일 때만 수행한다.

## 6. `lumina doctor`와 support bundle

### 6.1 명령 계약

```text
lumina doctor                         # 빠른 offline 기본 진단
lumina doctor --profile home
lumina doctor --profile corporate --network
lumina doctor --provider pgpt --stream
lumina doctor --json
lumina doctor --fix                   # 안전하고 되돌릴 수 있는 항목만
lumina support-bundle --redact
```

### 6.2 최소 진단 항목

1. install manifest 존재·schema·lock/build digest
2. 실제 Python/uv/Node/npm 경로, 버전, 필수 import
3. repository 이동 또는 stale absolute path
4. data/log/cache 쓰기 권한과 여유 공간
5. DB 연결, Alembic current/head, SQLite lock/WAL 상태
6. supervisor identity, port owner, Backend/Frontend child 상태
7. active profile과 설정 출처; secret은 존재 여부만 표시
8. public/company CA 출처, bundle 생성, 만료, SSL context 생성
9. corporate network의 DNS/TCP/TLS/auth/request/stream 단계
10. Provider model 설정과 실제 catalog/readiness 불일치
11. 최근 startup phase별 시간과 stable error code
12. Run queue/recovery 상태와 마지막 interrupted 원인

`--fix`는 runtime directory 생성, stale PID 제거, 재생성 가능한 CA bundle/cache 갱신, 안전한 DB checkpoint처럼 범위가 명확한 작업만 수행한다. credential 변경, CA 신뢰 우회, DB 파괴, Provider 자동 전환은 하지 않는다.

support bundle에는 다음만 포함한다.

- manifest와 profile의 비밀 없는 필드
- doctor JSON
- 로그 tail과 startup timeline
- OS/runtime 버전, process/port metadata
- 오류 코드와 stack trace의 민감값 제거본

API key, token, employee number, 전체 `.env`, 사용자 문서 내용과 원문 prompt는 포함하지 않는다.

## 7. 구현 순서

### Slice 0 — 실패를 먼저 측정한다

**변경 후보**

- `apps/server/src/lumina/main.py`
- `apps/server/src/lumina/diagnostics/`
- `devtools/run_lumina.ps1`
- 신규 startup event/error code 모듈

**작업**

- startup phase와 소요 시간 기록
- readiness가 실제 `executor.started`를 반영하도록 최소 수정
- launcher가 첫 실패 원인과 phase를 별도 state JSON에 보존
- 현재 home/corporate cold·warm start baseline 수집

**완료 조건**

- 한 번의 실패로 “어느 단계에서 몇 ms 후 왜 실패했는지”를 JSON과 사람이 읽는 출력에서 동일하게 확인한다.
- 기존 secret redaction 테스트가 새 로그 필드에도 적용된다.

### Slice 1 — 실행에서 build·migration을 제거한다

**변경 후보**

- `devtools/install_lumina.ps1`
- `devtools/run_lumina.ps1`
- `devtools/run_lumina.tests.ps1`
- 신규 install manifest 모듈/스크립트

**작업**

- installer stage 결과와 manifest를 원자적으로 기록
- `run`은 manifest/schema/build를 검증만 수행
- production restart loop에서 npm과 Alembic 제거
- 영구 오류 분류, exponential backoff, restart budget 구현
- Windows에서 npm 실행 파일은 installer와 동일하게 `npm.cmd` resolver 사용

**완료 조건**

- 정상 시작과 자동 재시작 테스트에서 npm/Alembic 호출 횟수가 0이다.
- update 명령에서는 각 단계가 정확히 1회이고 실패 stage부터 재실행할 수 있다.
- 영구 오류 fixture는 한 번 실패 후 멈추고, transient crash fixture는 budget 안에서만 복구한다.

### Slice 2 — deployment profile·path·trust를 단일화한다

**변경 후보**

- `apps/server/src/lumina/config.py`
- `apps/server/src/lumina/http_client.py`
- `apps/server/src/lumina/main.py`
- `apps/server/src/lumina/providers/pgpt/adapter.py`
- 신규 `paths.py`, runtime profile schema와 example

**작업**

- `home`/`corporate` profile schema, 저장 위치, 기본, fallback 구현
- CWD 비의존 `LuminaPaths`
- startup trust 초기화와 process-scope client factory
- required/optional capability가 readiness에 반영되도록 구성

**완료 조건**

- repository를 다른 경로로 이동해도 상대 설정이 같은 파일을 가리킨다.
- home에서 회사 CA가 없을 때 정상 시작한다.
- corporate required CA가 없거나 stale하면 정확히 not-ready가 되고 public CA로 숨겨 넘어가지 않는다.
- readiness와 실제 P-GPT transport가 같은 settings/trust snapshot digest를 보고한다.

### Slice 3 — Provider 공용 retry와 부분 응답 안전성

**변경 후보**

- `apps/server/src/lumina/providers/errors.py`
- 신규 provider retry policy
- `apps/server/src/lumina/agent/executor.py`
- Provider adapter 테스트와 Run event 테스트

**작업**

- retry decision table 구현
- `retry_scheduled` event 저장·replay
- 출력 시작 여부와 tool side effect를 retry 판단에 포함
- adapter별 국소 retry를 공용 정책과 충돌하지 않게 정리

**완료 조건**

- 출력 전 503은 정해진 횟수 후 성공하거나 stable code로 실패한다.
- 401/403/configuration 오류는 즉시 실패한다.
- 첫 token 뒤 연결 종료 fixture는 요청을 중복 전송하지 않는다.
- 재접속 후 retry 진행 상태가 snapshot/event replay로 복원된다.

### Slice 4 — doctor, support bundle, 실제 capability probe

**변경 후보**

- `apps/server/src/lumina/diagnostics/`
- 신규 CLI entrypoint
- Provider별 diagnostic probe
- installer/launcher의 doctor 연결

**작업**

- offline/network/stream 진단 모드
- `--json`, 안전한 `--fix`, redacted support bundle
- HTTP endpoint가 아니라 사용자 실행과 같은 인증·TLS·stream leg probe

**완료 조건**

- 아래 환경 행렬의 모든 실패가 서로 다른 stable code와 해결 action을 낸다.
- support bundle secret scanner가 API key, token, employee number fixture를 검출하지 못해야 통과한다.

### Slice 5 — release 설치와 운영 승격

- prebuilt Frontend를 포함한 versioned release artifact 제공
- `uv.lock`/npm lock digest와 artifact checksum 검증
- Windows clean VM, 회사망 runner, Linux service profile의 CI smoke test
- upgrade/rollback 시 DB migration 전 backup과 호환성 검사
- 한 release 동안 legacy launcher fallback을 측정한 뒤 제거 기한 확정

## 8. 필수 환경 검증 행렬

| 시나리오 | 기대 결과 |
|---|---|
| 깨끗한 집 PC, company CA 없음, P-GPT optional | public CA로 빠르게 ready; P-GPT만 unavailable |
| 회사에서 만든 stale absolute CA 설정을 집으로 복사 | profile/path 오류를 정확히 표시; 무한 재시작 없음 |
| 회사 PC, valid CA, P-GPT required | DNS→TLS→auth→stream 실제 leg 통과 후 ready |
| 회사 PC, required CA 누락 | `TRUST_CA_REQUIRED`; public CA fallback 없이 멈춤 |
| 회사 proxy가 TLS를 차단 | `NETWORK_TLS`와 peer/CA 출처 표시; credential 오류로 오분류 금지 |
| credential 만료 | `PROVIDER_AUTH`; retry와 서비스 restart 없음 |
| foreign process가 포트 점유 | owner 정보를 표시하고 foreign process를 종료하지 않음 |
| Windows 백신으로 cold start 60초 초과 | phase progress가 갱신되는 동안 중복 child 생성 없음 |
| DB schema가 binary보다 뒤처짐 | `UPDATE_REQUIRED`; runtime loop에서 migration하지 않음 |
| Codex 미설치, P-GPT만 required | global ready 가능; Codex capability만 unavailable |
| P-GPT 미설정, Codex만 required | global ready 가능; P-GPT probe가 시작을 지연하지 않음 |
| 출력 전 503 후 회복 | bounded retry event 뒤 같은 Run 성공 |
| 첫 token 뒤 연결 종료 | blind replay 없이 부분 결과 보존 및 중단/재개 안내 |
| Backend crash 중 queued Run 존재 | DB snapshot 기준 recovery; 같은 Session 중복 실행 없음 |
| 영구 config 오류로 Backend 즉시 종료 | restart budget을 소비하지 않고 한 번 멈춤 |
| repository 전체를 다른 경로로 이동 | path resolver와 manifest 재검증; CWD 차이로 CA/data가 바뀌지 않음 |
| 네트워크 완전 차단 설치 검증 | offline 항목만 통과, network 항목은 명시적 skipped |

## 9. 초기 SLO와 측정 원칙

다음 숫자는 현재 보장값이 아니라 Slice 0에서 baseline을 얻은 뒤 조정할 초기 목표다.

- warm `run`의 launcher 자체 overhead p95: 2초 이하
- home profile warm Backend ready p95: 10초 이하
- production 자동 재시작 중 build/migration 횟수: 0
- 영구 오류 감지 후 최종 상태 표시: 5초 이내
- startup 실패의 stable error code 보유율: 100%
- retryable Provider 오류의 사용자-visible retry event 보유율: 100%
- support bundle secret fixture 누출: 0건

Provider 실제 응답 시간은 launcher startup과 분리해 측정한다. cache hit, App Server warmup, model discovery, DNS/TLS/auth, first-token을 하나의 “응답 시간”으로 뭉치지 않는다.

## 10. 그대로 복사하지 않을 것

### MyHarness에서 복사하지 않을 점

- 포트를 점유했다는 이유만으로 다른 process까지 종료하는 방식
- supervisor의 무한 재시작
- `C:\POSCO_CA.crt` 하나에 종속된 회사망 판별
- 부분 stream이 이미 나간 뒤 전체 요청을 재전송할 수 있는 retry 형태
- 설정과 credential을 장기적으로 한 파일 계층에 계속 추가하는 방식

MyHarness에서 취할 것은 “없을 때만 설치·빌드”, 조기 CA 초기화, 앱 로컬 상태, active profile, bounded retry와 retry event다.

### HERMES에서 복사하지 않을 점

- Lumina 규모에 필요하지 않은 방대한 설치 stage와 모든 optional 도구 검사
- Electron 전용 process 소유 모델을 Web/LAN 배포에 그대로 적용하는 것
- 오래된 runtime compatibility fallback을 목적 없이 유지하는 것

HERMES에서 취할 것은 단일 resolver, 실제 import/연결 probe, 명시적 ready announcement, cold-start tolerant deadline, 단계별 installer 결과, `doctor --fix`, profile-aware log, bounded recovery 상태다.

## 11. 구현 시 반드시 함께 바꿀 문서

- `INSTALLATION_AND_DIAGNOSTICS.md`: install/update/run 경계와 doctor 명령
- `PGPT_CORPORATE_NETWORK.md`: deployment profile, trust startup, 실제 capability readiness
- `AGENT_LOOP.md`: Provider retry event와 부분 응답 복구 규칙
- `LUMINA_DETAILED_DESIGN.md`: 배포 topology, health 의미, runtime manifest, SLO
- 루트 `README.md`: home/corporate 최소 시작 절차와 실패 시 첫 명령

기존 문서가 말하는 “Trust Manager를 Provider보다 먼저 초기화한다”, “readiness가 실제 준비 상태를 반영한다”는 방향은 맞다. 구현이 그 계약을 아직 완전히 지키지 못하는 지점을 위 순서로 닫아야 한다.

## 12. 완료 정의

이 개선은 특정 PC에서 한 번 실행됐다고 완료되지 않는다. 다음 조건을 모두 만족해야 한다.

1. 설치, 업데이트, 실행, 재시작의 command와 책임이 분리되어 있다.
2. 정상 실행과 자동 재시작은 dependency install, build, migration을 수행하지 않는다.
3. `ready` 성공은 실제 executor와 profile이 요구한 capability 성공을 의미한다.
4. 집·회사 설정 차이가 active profile과 진단 결과에 명시적으로 보인다.
5. transient Provider 오류는 bounded retry되고 permanent 오류는 즉시 멈춘다.
6. 출력 후 실패가 요청·tool side effect를 중복 실행하지 않는다.
7. 영구 startup 오류가 무한 재시작되지 않는다.
8. clean home VM, corporate runner, repository 이동, offline, crash/recovery 행렬이 CI 또는 release checklist에서 통과한다.
9. 사용자는 첫 화면 또는 한 번의 `lumina doctor`로 실패 단계와 해결 action을 확인할 수 있다.
10. 관련 운영 문서와 구현 계약 테스트가 같은 변경에 포함된다.

가장 먼저 구현할 것은 기능 추가가 아니다. **`ready`의 진실성, run에서 build/migration 제거, restart budget, startup phase 측정** 네 가지다. 이 기반을 먼저 만들면 이후 CA·P-GPT·Codex 문제를 고칠 때도 “이번 PC에서 우연히 됐다”가 아니라 어느 환경에서 왜 되는지 증명할 수 있다.

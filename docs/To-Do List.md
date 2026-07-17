# Lumina Agent 부하 대응 To-Do List

## 목적

Lumina Agent를 단일 서버의 소규모 파일럿 수준에서 여러 사용자가 동시에 안정적으로 사용하는 운영 구조로 발전시키기 위한 작업 목록입니다. 보안 개선은 이 문서의 범위에서 제외합니다.

현재 구현은 대화별 Run 직렬화, 사용자·서버별 동시 실행 제한, DB 기반 Run event와 SSE replay를 지원합니다. 다만 SQLite, API 프로세스 내부의 `LocalRunExecutor`, process-local claim·broker, 로컬 파일 저장소 때문에 수평 확장과 고부하 운영은 아직 보장되지 않습니다.

상용 배포 환경은 **Linux를 기준**으로 합니다. Windows는 개발 환경으로 유지하고, WSL2 + Ubuntu + Podman CLI를 Linux 운영 환경에 가까운 기본 개발 경로로 사용합니다. Docker는 OCI 호환 개발·빌드 대안으로 지원할 수 있지만 Docker Desktop GUI에 종속되지 않습니다. Kubernetes는 Linux 상용 환경의 scale-out 경로이며 Kind는 로컬 배포 검증에만 사용합니다.

현재 `infra/`는 설계상 컨테이너·배포 자산 위치로 예약되어 있지만 실제 Containerfile·Compose·Kubernetes manifest는 아직 없습니다.

관련 기준 문서:

- `docs/project-context/AGENT_LOOP.md`
- `docs/LUMINA_DETAILED_DESIGN.md`
- `docs/LUMINA_HARNESS_ENGINEERING_REVIEW_2026-07-15.md`
- `docs/project-context/COWORK_FEATURE_REQUIREMENTS.md`

## P0 — 운영 전 필수

### 1. 기준 부하 시험 구축

- [ ] `1 / 5 / 12`개 동시 Run 시나리오를 자동화합니다.
- [ ] `50 / 200`개 SSE 연결 시나리오를 자동화합니다.
- [ ] 동시 Run 중 파일 업로드·다운로드·Artifact 생성이 겹치는 시나리오를 추가합니다.
- [ ] Queue에 `10 / 100 / 1,000`개 Run이 대기하는 시나리오를 추가합니다.
- [ ] Mock Provider와 실제 운영 Provider를 분리해 측정합니다.
- [ ] 아래 지표를 동일한 형식으로 기록합니다.
  - API 응답 시간 p50·p95·p99
  - Run queue wait와 전체 완료 시간
  - 첫 응답 시간과 SSE event 전달 지연
  - DB transaction 시간, lock·timeout 횟수, 초당 event write 수
  - CPU, 메모리, 파일 I/O, 활성 task·connection 수
  - Run 성공률, 중복 실행률, recovery 성공률

완료 조건:

- [ ] 재현 가능한 명령 하나로 기준 부하 시험을 실행할 수 있습니다.
- [ ] 서버 사양, DB 종류, Provider, 동시 사용자 수가 결과에 함께 기록됩니다.
- [ ] 변경 전후 결과를 비교하여 회귀 여부를 판단할 수 있습니다.

### 2. PostgreSQL 운영 전환

- [ ] 운영 환경에서 SQLite를 사용하지 않도록 deployment 설정을 분리합니다.
- [ ] PostgreSQL connection pool의 `pool_size`, `max_overflow`, timeout 기본값을 정합니다.
- [ ] Run event write와 SSE replay 쿼리를 실제 PostgreSQL에서 부하 검증합니다.
- [ ] Alembic migration과 PostgreSQL dialect 검증을 배포 절차에 포함합니다.
- [ ] SQLite는 로컬 개발·소규모 단일 프로세스 실행 용도로만 명시합니다.

완료 조건:

- [ ] 12개 동시 Run에서 DB lock 때문에 Run이 실패하지 않습니다.
- [ ] pool 고갈과 transaction 지연이 계측되고 경고 기준이 있습니다.

### 3. API와 Agent Worker 분리

- [ ] FastAPI process가 직접 `LocalRunExecutor`를 소유하지 않도록 Worker 경계를 만듭니다.
- [ ] API는 Run을 DB Queue에 기록하고 즉시 응답하도록 유지합니다.
- [ ] Worker는 DB Queue에서 실행 가능한 Run만 가져옵니다.
- [ ] API 재시작이 실행 중인 Run을 직접 중단하지 않도록 합니다.
- [ ] API replica와 Worker replica 수를 독립적으로 조절할 수 있게 합니다.

완료 조건:

- [ ] API process 재시작 중에도 Worker가 실행 중인 Run을 계속 처리합니다.
- [ ] Worker 수를 늘려도 동일 Run이 중복 실행되지 않습니다.

### 4. 원자적 Run claim과 Worker lease

- [ ] PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED` 또는 동등한 원자적 claim을 구현합니다.
- [ ] `run_execution_leases`에 `run_id`, `worker_id`, `execution_epoch`, `claimed_at`, `heartbeat_at`, `expires_at`, `status`를 저장합니다.
- [ ] claim 시 `execution_epoch`를 증가시킵니다.
- [ ] Run event와 Tool checkpoint에 실행 epoch를 고정합니다.
- [ ] heartbeat가 만료된 lease만 recovery 대상으로 전환합니다.
- [ ] 이전 Worker의 event·shutdown update는 epoch 불일치 시 무시합니다.
- [ ] 사용자·대화·서버 concurrency limit을 동일한 DB transaction 안에서 적용합니다.

완료 조건:

- [ ] 두 Worker가 동시에 시작돼도 하나의 Run은 한 번만 실행됩니다.
- [ ] Worker 강제 종료 후 정해진 시간 안에 한 번만 recovery됩니다.
- [ ] 복귀한 오래된 Worker가 새 epoch의 Run을 변경하지 못합니다.

### 5. Linux 컨테이너 실행 기준 확정

- [ ] Linux 운영용 OCI image를 재현 가능하게 빌드하는 `Containerfile` 또는 `Dockerfile`을 추가합니다.
- [ ] API와 Agent Worker를 독립 image 또는 독립 entrypoint로 실행할 수 있게 합니다.
- [ ] Python·Node.js·OS package 버전을 고정하고 lock file 기반으로 설치합니다.
- [ ] Frontend production build는 runtime image에 필요한 결과만 포함하도록 multi-stage build를 적용합니다.
- [ ] LibreOffice, Poppler, 한글 font 등 Artifact 생성·검증에 필요한 Linux package를 image에 명시합니다.
- [ ] DB migration과 application startup을 분리하여 Pod가 시작될 때마다 migration하지 않게 합니다.
- [ ] Linux signal을 받아 새 Run claim을 중단하고 진행 중인 Run을 drain한 뒤 종료하도록 합니다.
- [ ] PID 1, zombie child process, MCP·renderer subprocess 정리가 정상 동작하는지 검증합니다.
- [ ] container filesystem을 일회성으로 간주하고 DB·파일·Artifact·로그 원본을 image 내부에 저장하지 않습니다.
- [ ] `GET /api/health/live`, `/api/health/ready`, `/api/health/startup`을 container probe에서 사용할 수 있게 유지합니다.

개발 환경 이슈:

- [ ] Windows 개발 기본 경로를 WSL2 + Ubuntu + Podman CLI로 문서화합니다.
- [ ] Docker Engine·Docker Desktop에서도 동일 OCI image가 실행되는지 선택적 호환성을 검증합니다.
- [ ] Windows NTFS bind mount의 작은 파일 I/O와 file watcher 성능을 Linux filesystem 또는 named volume과 비교합니다.
- [ ] SQLite·PostgreSQL data volume을 Windows bind mount에 둘 때 fsync·lock 동작 차이를 검증합니다.
- [ ] Windows와 Linux의 path separator, 대소문자 구분, 실행 권한, CRLF·LF 차이를 CI에서 검사합니다.
- [ ] container 내부의 `127.0.0.1`과 host의 `127.0.0.1`이 다르므로 Backend·Provider·DB 주소를 환경별로 분리합니다.
- [ ] `host.docker.internal`에 종속되지 않고 Podman·Linux에서도 같은 host 연결 계약을 사용합니다.
- [ ] 회사망 DNS·proxy·CA bundle이 host에서는 되지만 container에서는 실패하는 상황을 진단 항목에 추가합니다.
- [ ] WSL2·container VM의 CPU·메모리·디스크 상한과 메모리 회수 정책을 부하 시험 결과에 기록합니다.

완료 조건:

- [ ] 깨끗한 Linux VM에서 image build, migration, startup, Run, Artifact 생성까지 재현됩니다.
- [ ] Windows WSL2 개발 image와 Linux 운영 image가 동일한 application 계약과 test suite를 통과합니다.
- [ ] container 재시작 후 DB Queue와 Run recovery가 손실 없이 동작합니다.

## P1 — 주요 병목 제거

### 6. Queue polling을 bounded dispatcher로 교체

- [ ] 대기 Run마다 0.2초 간격 task를 만드는 구조를 제거합니다.
- [ ] Worker별 고정 개수 dispatcher가 빈 실행 슬롯만큼 Run을 claim하도록 합니다.
- [ ] 새 Run·Run 종료 시 dispatcher를 깨우는 신호 경로를 만듭니다.
- [ ] 신호를 놓쳐도 낮은 빈도의 DB fallback poll로 복구되게 합니다.
- [ ] Queue 길이와 가장 오래 기다린 Run의 대기 시간을 계측합니다.

완료 조건:

- [ ] Queue 1,000개에서도 polling SQL이 Queue 길이에 비례해 급증하지 않습니다.
- [ ] 실행 슬롯이 비면 다음 Run이 정해진 지연 목표 안에 시작됩니다.

### 7. Run event write 줄이기

- [ ] `assistant_text_delta` 저장 주기를 현재 최대 50ms보다 큰 batch로 조정해 비교 측정합니다.
- [ ] 시간, 문자 수, terminal event를 함께 고려하는 flush 정책을 정의합니다.
- [ ] 한 transaction에서 여러 delta를 안전하게 저장하는 방식을 검토합니다.
- [ ] Tool·상태 전환 event의 즉시성은 유지합니다.
- [ ] reconnect replay에서 텍스트 손실·중복이 없는지 검증합니다.

완료 조건:

- [ ] 사용자 체감 스트리밍을 유지하면서 초당 DB write 수가 유의미하게 감소합니다.
- [ ] disconnect와 `Last-Event-ID` replay 테스트가 계속 통과합니다.

### 8. SSE fan-out 개선

- [ ] 연결 수, 연결당 DB query 수, event delivery lag를 계측합니다.
- [ ] process-local `RunEventBroker`를 다중 API replica에서 동작하는 wake-up 계층으로 교체합니다.
- [ ] PostgreSQL LISTEN/NOTIFY 또는 Redis Pub/Sub을 wake-up 용도로 비교합니다.
- [ ] DB는 최종 event source of truth로 유지합니다.
- [ ] 동일 Run의 여러 관찰자가 DB를 과도하게 반복 조회하지 않도록 batch·cursor 전략을 검증합니다.

완료 조건:

- [ ] 200개 SSE 연결에서 API p95와 event lag가 정한 목표를 충족합니다.
- [ ] API replica가 달라도 새 event를 즉시 전달하고 replay가 손실 없이 동작합니다.

### 9. 동기식 파일·렌더링 작업 격리

- [ ] PDF·DOCX·XLSX·PPTX 추출을 API event loop 밖으로 이동합니다.
- [ ] Office/PDF render validation을 별도 process pool 또는 작업 Queue에서 실행합니다.
- [ ] 파일 hash, `fsync`, 대용량 read/write가 API·SSE 지연에 미치는 영향을 측정합니다.
- [ ] 작업별 CPU·메모리·시간·출력 크기 제한을 둡니다.
- [ ] 추출·렌더링 진행 상태를 Run event 또는 작업 상태로 노출합니다.

완료 조건:

- [ ] 큰 문서 처리 중에도 health, 일반 API와 SSE 응답성이 유지됩니다.
- [ ] renderer timeout이나 crash가 API process에 영향을 주지 않습니다.

## P2 — 확장성과 운영성

### 10. 공유 Object Storage 도입

- [ ] 현재 `ManagedLocalStorage` 계약 뒤에 S3·MinIO adapter를 추가합니다.
- [ ] 파일·Artifact metadata는 DB에, 원본 content는 object storage에 저장합니다.
- [ ] 여러 API·Worker replica가 동일 content를 읽고 쓸 수 있게 합니다.
- [ ] 대용량 다운로드는 application memory 전체 적재 없이 stream하도록 합니다.
- [ ] lifecycle, orphan cleanup, 저장 용량 quota 정책을 정합니다.

완료 조건:

- [ ] replica가 달라도 동일 파일과 Artifact를 일관되게 조회합니다.
- [ ] 단일 서버 로컬 디스크 장애가 전체 content 손실로 이어지지 않습니다.

### 11. Provider·Tool 전역 backpressure

- [ ] Provider별 동시 요청·분당 요청·token rate 제한을 설정할 수 있게 합니다.
- [ ] 현재 per-Run Tool semaphore와 별도로 서버·Provider·Tool별 전역 제한을 둡니다.
- [ ] 429·503·timeout의 retry와 Queue backoff 정책을 통일합니다.
- [ ] 특정 Provider 장애가 전체 Worker slot을 장시간 점유하지 않게 circuit breaker를 검토합니다.
- [ ] 조직·사용자별 공정한 Queue scheduling 정책을 정합니다.

완료 조건:

- [ ] 한 사용자나 한 Provider가 전체 실행 슬롯을 독점하지 않습니다.
- [ ] 외부 rate limit 발생 시 무제한 retry나 요청 폭증이 발생하지 않습니다.

### 12. 운영 관측성 구축

- [ ] HTTP request → Run → model turn → Tool → Artifact를 잇는 trace ID를 도입합니다.
- [ ] OpenTelemetry 또는 동등한 trace·metric 수집 계층을 추가합니다.
- [ ] active·queued Run, queue wait, Provider latency, SSE lag, DB pool, event write rate를 dashboard로 표시합니다.
- [ ] p95·오류율·Queue 길이에 대한 경고 기준을 정합니다.
- [ ] 배포 전후 성능 회귀를 자동 비교합니다.

완료 조건:

- [ ] 느린 Run이 Provider, DB, Queue, Tool, 파일 처리 중 어디에서 지연됐는지 추적할 수 있습니다.
- [ ] 용량 증설 시점을 사용자 불만보다 먼저 지표로 확인할 수 있습니다.

### 13. Linux Kubernetes 운영 기반 구축

선행 조건:

- [ ] PostgreSQL 운영 전환, 원자적 Run claim·lease, API·Worker 분리를 먼저 완료합니다.
- [ ] API와 Worker의 상태 원본을 PostgreSQL·Redis·Object Storage 등 외부 서비스로 이동합니다.
- [ ] SQLite, process-local broker, local filesystem을 replica 간 공유 상태로 사용하지 않습니다.

배포 자산:

- [ ] `infra/`에 API·Worker·Frontend·Scheduler 배포용 manifest와 환경별 overlay를 추가합니다.
- [ ] Helm 또는 Kustomize 중 하나를 표준으로 정하고 중복 템플릿을 만들지 않습니다.
- [ ] API, Worker, Scheduler의 Deployment·Service·설정 계약을 분리합니다.
- [ ] PostgreSQL, Redis, Object Storage는 운영 방식에 따라 managed service 또는 별도 stateful 운영 책임을 명시합니다.
- [ ] migration은 replica startup이 아니라 버전별 단일 Kubernetes Job으로 실행합니다.
- [ ] schema가 application보다 뒤처지거나 앞선 경우 readiness가 안전하게 실패하도록 합니다.

Pod lifecycle과 무중단 운영:

- [ ] liveness, readiness, startup probe의 목적과 timeout을 각각 설정합니다.
- [ ] Worker readiness는 새 Run을 claim할 수 있는 상태를 의미하도록 합니다.
- [ ] 종료 시 Worker가 먼저 claim을 멈추고 진행 중 Run을 완료·checkpoint·lease 반환하도록 합니다.
- [ ] `terminationGracePeriodSeconds`, `preStop`, rolling update 전략을 Run timeout과 맞춥니다.
- [ ] Pod kill, node drain, rolling update, 네트워크 단절에서 Run이 중복되거나 유실되지 않는지 검증합니다.
- [ ] PodDisruptionBudget과 topology spread를 설정하여 한 노드 장애가 전체 API·Worker를 중단하지 않게 합니다.

Scheduler와 Queue:

- [ ] 현재 API process마다 시작되는 local scheduler를 별도 Scheduler deployment로 분리합니다.
- [ ] Scheduler replica가 둘 이상이면 leader election 또는 DB lease로 하나만 schedule을 생성하게 합니다.
- [ ] Queue 길이·가장 오래된 대기 시간·Provider별 여유량을 Worker autoscaling 지표로 사용합니다.
- [ ] CPU만으로 HPA를 구성하지 않고 장시간 I/O 대기 Run과 Queue 적체를 반영합니다.
- [ ] scale-down 시 처리 중인 Worker를 먼저 drain하고 lease가 끝나기 전에 강제 종료하지 않습니다.

SSE와 네트워크:

- [ ] Ingress의 response buffering을 끄고 SSE idle timeout을 keep-alive 주기보다 길게 설정합니다.
- [ ] API replica가 달라도 DB event replay와 분산 wake-up이 동작하도록 합니다.
- [ ] rolling update 중 SSE 재연결이 `Last-Event-ID`부터 손실 없이 복구되는지 검증합니다.
- [ ] Provider·MCP·회사 proxy·DNS·CA 연결을 Linux Pod 내부에서 실제 요청 경로로 진단합니다.

리소스와 검증:

- [ ] API, Worker, Scheduler, renderer 작업별 CPU·메모리 request와 limit을 부하 시험으로 정합니다.
- [ ] ephemeral storage 사용량과 Artifact 임시 렌더링 공간에 limit·경고를 둡니다.
- [ ] OOMKill, CPU throttling, disk pressure가 Run recovery에 미치는 영향을 시험합니다.
- [ ] Kind는 manifest·probe·rolling update smoke test에만 사용하고 운영 용량 판단에는 사용하지 않습니다.
- [ ] 상용 Linux Kubernetes와 유사한 staging cluster에서 `1 / 5 / 12` Run 및 `50 / 200` SSE 시험을 반복합니다.

완료 조건:

- [ ] API와 Worker replica를 독립적으로 늘려도 동일 Run이 한 번만 실행됩니다.
- [ ] rolling update와 Worker 강제 종료 중 Run·event·Artifact 손실과 중복이 없습니다.
- [ ] Scheduler replica 수와 관계없이 예약 실행이 한 번만 생성됩니다.
- [ ] Pod와 노드가 교체되어도 사용자 재접속 시 snapshot과 event replay가 복원됩니다.

## 권장 진행 순서

1. 기준 부하 시험과 최소 지표 수집
2. Linux OCI image와 container smoke test 구축
3. PostgreSQL 전환
4. 원자적 claim·lease 구현
5. API·Worker·Scheduler 분리
6. bounded dispatcher 적용
7. Run event batch와 SSE fan-out 최적화
8. 파일 처리 격리와 Object Storage 전환
9. Provider backpressure와 운영 dashboard 완성
10. Kind 검증 후 Linux staging·상용 Kubernetes로 승격

각 단계는 바로 앞 단계의 부하 시험을 다시 실행하고 결과가 개선되었는지 확인한 뒤 완료 처리합니다. 기본 동시 실행 수 `12`는 성능 보장치가 아니므로, 측정 결과 없이 운영 용량으로 간주하지 않습니다.

> 생성일: 2026-07-12

# Manus에서 Lumina Agent가 추가로 배울 설계 교훈

조사일: 2026-07-11

## 조사 목적

Manus의 기능을 그대로 복제하는 것이 아니라, Lumina의 기존 설계 문서에 이미 있는 Cowork·Hermes·MyHarness 계열 요구사항과 비교해 **아직 명시되지 않았거나 계약이 약한 교훈만** 추립니다.

이 문서는 다음 기존 설계를 기준선으로 삼았습니다.

- `AGENT_LOOP.md`: Run, Plan, Step, Subtask, Queue, 승인, 중단·재개와 event replay
- `COWORK_FEATURE_REQUIREMENTS.md`: Project, 파일 Workspace, 전문 산출물, Connector, 브라우저·컴퓨터 사용, 예약 작업과 Live Artifact
- `HERMES_USER_FEATURES.md`: Background Run, 세션 복원, Artifact Library, Memory·Skill 통제와 상태 진단
- `PURPOSE_DRIVEN_AGENT_UI_RESEARCH.md`: 공통 Backend 계약과 교체 가능한 Agent Frontend
- `myharness_feature_requiorements.md`: Artifact 편집·버전·공유·sandbox preview

따라서 다단계 Plan, 일반적인 Tool 병렬 실행, Project 파일·지침, Artifact 생성, Browser/Computer Use, 예약 실행, Connector와 단순한 세션 공유는 새 교훈으로 다시 제안하지 않습니다.

## 결론

Manus에서 Lumina에 새로 반영할 가치가 큰 항목은 다음 7개입니다.

1. **실행 환경을 임시 Sandbox, 지속 Cloud Workspace, 사용자 로컬 실행기로 구분하고 Run마다 선택 근거를 저장**
2. **Context 압축을 요약이 아니라 원문으로 돌아갈 수 있는 복원 가능한 참조 변환으로 설계**
3. **대량 동형 작업을 fresh context로 격리하는 Batch Fan-out 실행 유형 추가**
4. **완료된 Run에서 Project 지식·지침·Skill 변경안을 추출하되 승인 전에는 반영하지 않는 학습 제안 흐름 추가**
5. **읽기 전용 공유와 공동 실행을 서로 다른 권한·비밀 경계로 분리**
6. **승인을 일회성 확인창이 아니라 task·path·capability 범위의 만료 가능한 권한 lease로 모델링**
7. **예약 작업에 시간뿐 아니라 실행 위치, 이어갈 Context와 갱신할 Artifact identity를 고정**

이 중 1~5는 제품·Backend 데이터 모델에 영향을 주므로 설계 단계에서 먼저 반영하는 편이 좋습니다. 6~7은 해당 기능 구현 전에 계약을 구체화해도 됩니다.

## 기존 설계와의 중복 판정

| Manus에서 관찰한 항목 | Lumina 기존 상태 | 판정 |
|---|---|---|
| 다단계 Agent Loop와 Tool 실행 | Run·Turn·Tool Loop가 이미 상세함 | 제외 |
| Background Run과 재접속 | snapshot + sequence replay가 이미 상세함 | 제외 |
| Project의 파일·지침·기억 | `Organization → Project → Session → Run`과 Project 격리가 이미 있음 | 제외 |
| 문서·슬라이드·표·웹 산출물 | 전문 Artifact와 형식별 검증이 이미 있음 | 제외 |
| Browser/Computer Use | Connector → MCP → Browser → Computer 우선순위가 이미 있음 | 제외 |
| 일반 Subtask 병렬 실행 | dependency 기반 병렬 Subtask가 이미 있음 | 부분 중복 |
| Sandbox와 로컬 컴퓨터 | 수단은 있으나 실행 환경의 생명주기·선택 계약은 없음 | 채택 |
| 파일 시스템을 Context로 사용 | 큰 출력을 Artifact로 전환하지만 복원 가능성 계약은 약함 | 채택 |
| Project가 매 작업에서 학습 | Memory 통제는 있으나 승인형 Project 갱신 제안 흐름은 없음 | 채택 |
| Task 공유와 실시간 공동 실행 | private/shared 모드는 있으나 두 행위의 보안 의미가 분리되지 않음 | 채택 |
| 예약 작업 | 기본 요구사항은 있으나 동일 Task/별도 Task와 동일 Artifact 갱신 의미가 약함 | 보강 |

## 1. Run과 실행 환경을 분리해 모델링

### Manus에서 확인한 점

Manus는 작업 실행 환경을 적어도 세 종류로 구분합니다.

- Task별 임시 Sandbox: 격리된 VM이며 task가 끝난 뒤 휴면·재활용될 수 있음
- Cloud Computer: 파일, 설치 도구와 프로세스가 세션 사이에도 유지되는 항상 켜진 환경
- My Computer·Browser Operator: 사용자가 허용한 로컬 폴더, CLI 도구 또는 로그인된 브라우저를 이용하는 사용자 소유 환경

중요한 점은 Tool 종류만 다른 것이 아니라 **수명, 신뢰 경계, 데이터 위치, 비용과 복구 방식이 다른 실행 환경**이라는 점입니다.

### Lumina의 빈틈

Lumina는 Backend와 Worker를 분리하고 Browser·Computer Use 우선순위를 정의했지만, Run이 어느 실행 환경에 배치되었는지와 그 환경이 언제 폐기·복구되는지는 독립 계약으로 정의하지 않았습니다. 장기 프로세스, 설치한 패키지, 임시 작업 파일과 사용자 로컬 파일을 모두 같은 Workspace 개념으로 취급하면 복구와 보안 정책이 모호해집니다.

### 권장 계약

```text
ExecutionEnvironment
├─ ephemeral_sandbox
│  ├─ isolated per Run or Task
│  ├─ sleep/recycle policy
│  └─ only declared durable files survive
├─ persistent_workspace
│  ├─ Project-scoped or user-scoped
│  ├─ persistent filesystem and processes
│  └─ explicit quota, billing and shutdown policy
└─ user_managed
   ├─ local computer or local browser
   ├─ user-presence and connection state
   └─ path/session-scoped authorization
```

Run snapshot에는 최소한 다음을 저장합니다.

```text
environment_id
environment_type
selection_reason
durability_policy
network_policy
authorized_paths_or_browser_session
created_at / expires_at
recovery_manifest_id
```

환경 선택은 다음과 같이 설명 가능해야 합니다.

- 문서 분석처럼 종료 후 중간 파일이 필요 없는 작업 → `ephemeral_sandbox`
- 장기 crawler나 Project 개발 서버처럼 프로세스 지속성이 필요한 작업 → `persistent_workspace`
- 사내 로그인 세션이나 로컬 전용 파일이 필요한 작업 → `user_managed`

자동 선택이 가능하더라도 UI에는 선택된 환경, 데이터가 존재하는 위치, 유지 기간과 로컬 연결 필요 여부를 보여줍니다. 사용자 로컬 환경으로의 자동 승격은 금지하고 명시적 허용을 받습니다.

## 2. Context 압축은 반드시 복원 가능하게 만들기

### Manus에서 확인한 점

Manus는 파일 시스템을 단순 결과 저장소가 아니라 외부 Context로 사용합니다. 웹 페이지 본문을 Context에서 제거하더라도 URL을 남기고, 문서 본문을 빼더라도 sandbox 경로를 남겨 필요할 때 다시 읽을 수 있게 합니다. 핵심은 압축 후 정보가 영구적으로 사라지지 않는다는 점입니다.

또한 긴 작업에서 todo 파일을 반복 갱신해 목표와 현재 계획을 Context 끝부분에 다시 노출합니다. 이는 계획을 저장하는 것과 별개로, 모델의 최근 주의 영역에 핵심 목표를 재주입하는 실행 전략입니다.

### Lumina의 빈틈

현재 `AGENT_LOOP.md`는 오래된 Tool 출력 정리, Artifact 전환과 대화 요약을 허용하지만 다음이 명시되지 않았습니다.

- 무엇을 버렸고 어디서 원문을 다시 가져올 수 있는지
- 참조 대상이 바뀌거나 사라졌는지 검증하는 방법
- Plan 객체를 매 Turn의 최근 Context에 어떤 축약 형식으로 재주입하는지

### 권장 계약

모든 Context 축소 결과에 `recovery_ref`를 둡니다.

```text
CompactedContextEntry
├─ summary
├─ source_type: artifact | file | url | tool_result | message_range
├─ source_id
├─ source_version_or_hash
├─ retrieval_policy
├─ access_scope
└─ compacted_at
```

- 원문이 보존되지 않는 비가역 요약은 사용자 대화처럼 원본 DB가 별도로 존재하는 경우에만 허용합니다.
- URL 재조회는 내용이 달라질 수 있으므로 fetch 시점의 hash 또는 저장 snapshot을 함께 둡니다.
- Artifact·파일 참조는 Project와 사용자 권한을 재검증합니다.
- 매 model Turn 직전에는 전체 Plan이 아니라 `goal + active step + unresolved constraints + next check`만 bounded digest로 재주입합니다.
- Context 압축 전후에 목표, 승인 상태, 부작용 Tool 결과와 idempotency key가 유지되는지 불변 조건으로 테스트합니다.

## 3. 일반 병렬 Subtask와 Batch Fan-out을 구분

### Manus에서 확인한 점

Wide Research는 단순히 여러 Tool을 동시에 실행하는 기능이 아닙니다. 비슷한 항목 수십·수백 개를 처리할 때 각 항목을 **독립된 fresh context**를 가진 Agent에 배정하고, 동일한 출력 schema와 평가 기준으로 결과를 모은 뒤 상위 Agent가 합성합니다. 한 항목의 긴 관찰 기록이 다른 항목의 품질을 떨어뜨리지 않게 하는 구조입니다.

### Lumina의 빈틈

Lumina의 Plan은 독립 Subtask 병렬화를 지원하지만, 모든 Subtask가 같은 상위 대화 Context를 얼마나 상속하는지와 대규모 동형 작업의 품질·비용 제어가 정의되지 않았습니다.

### 권장 계약

Plan Step에 일반 `parallel`과 별도로 `batch_fanout` 유형을 둡니다.

```text
BatchFanoutStep
├─ input_dataset_artifact_id
├─ item_selector
├─ shared_instruction_snapshot
├─ per_item_context_policy: fresh
├─ output_schema
├─ evaluation_rules
├─ concurrency_limit
├─ item_budget
├─ synthesis_strategy
└─ partial_failure_policy
```

핵심 규칙은 다음과 같습니다.

- 각 item worker는 공통 지침과 자신의 항목만 받고 다른 항목의 관찰 기록을 상속하지 않습니다.
- 결과는 자유 텍스트 목록이 아니라 동일 schema로 저장합니다.
- 항목별 상태·비용·출처·검증 결과를 저장하고 실패 항목만 재시도할 수 있게 합니다.
- 합성 Agent는 원시 Tool log 대신 구조화된 item 결과와 대표 근거를 받습니다.
- 자동 fan-out 전 예상 worker 수, 비용 상한과 외부 요청량을 계산합니다.
- 항목 수가 적거나 항목 사이에 순차 의존성이 있으면 일반 Plan으로 fallback합니다.

## 4. Project 학습은 자동 반영이 아니라 승인 가능한 변경 제안으로

### Manus에서 확인한 점

Manus Project는 완료된 대화에서 재사용할 결정, 용어, 형식, 예시와 workflow를 찾아 Project 지침·파일·Skill 변경안을 제안할 수 있습니다. 실제 Project Context는 사용자가 승인한 뒤에만 바뀝니다.

### Lumina의 빈틈

Lumina는 Project별 파일·지침·기억·Skill 격리와 사용자 Memory 통제를 설계했지만, Run에서 나온 지식을 Project 기본 Context로 승격하는 명시적 lifecycle은 없습니다. `HERMES_USER_FEATURES.md`가 자동 Skill 자기개선을 초기 제외 대상으로 둔 판단은 유지할 수 있습니다. 여기서 채택할 것은 자동 자기개선 자체가 아니라 **검토 가능한 제안 객체**입니다.

### 권장 계약

```text
ProjectLearningProposal
├─ project_id
├─ source_run_ids[]
├─ target_type: instruction | file | glossary | example | skill
├─ target_id and base_version
├─ proposed_patch
├─ rationale and evidence_refs[]
├─ scope and expected_future_effect
├─ status: proposed | approved | rejected | stale | applied | rolled_back
├─ proposed_by / reviewed_by
└─ created_at / reviewed_at
```

- 기본은 자동 실행이 아니라 사용자의 명시 호출 또는 완료 후 opt-in 제안입니다.
- 현재 버전과 `base_version`이 다르면 자동 적용하지 않고 stale 처리합니다.
- 적용 전에 diff, 근거 Run, 영향을 받는 향후 Task 범위를 보여줍니다.
- 공유 Project에서는 승인 역할을 제한하고 모든 변경을 감사 기록에 남깁니다.
- 지침·파일·Skill 변경은 새 version으로 저장하고 rollback할 수 있게 합니다.
- 비밀값, 개인 계정 정보, 일회성 승인과 임시 실패 우회책은 학습 후보에서 제외합니다.

## 5. 공유와 공동 작업의 보안 의미를 분리

### Manus에서 확인한 점

Manus는 task `sharing`과 `collaboration`을 구분합니다.

- Sharing: 수신자는 대화와 결과 Artifact를 보지만 Sandbox에는 접근하지 않음
- Collaboration: 참여자가 Agent에 지시하고 Sandbox의 파일을 간접적으로 읽거나 바꿀 수 있음

공동 작업이 시작되면 Connector를 비활성화하고 sandbox 로그인 cookie를 지우는 정책은, 협업 전환이 단순 UI 권한 변경이 아니라 credential trust boundary 변경이라는 점을 보여줍니다.

### Lumina의 빈틈

현재 private/shared 모드는 데이터 공개 범위를 설명하지만, 결과 열람과 Agent 실행권·Workspace 조작권을 하나의 공유 개념으로 오해할 여지가 있습니다. 특히 개인 Run에서 사용한 Connector 세션이나 임시 credential이 공유 Project로 전환될 때 어떻게 되는지 더 명확해야 합니다.

### 권장 계약

다음 세 가지를 별도 객체와 권한으로 구분합니다.

```text
view_share       → immutable message/artifact snapshot 열람
project_member   → Project의 허용된 파일·세션·Artifact에 협업
run_collaborator → 특정 Session/Run에 지시·승인·취소 action 수행
```

공유 범위가 넓어지는 전환에는 `credential boundary reset`을 실행합니다.

- 개인 Connector token과 browser session은 공동 Run에 자동 상속하지 않습니다.
- 개인 환경에서 생성한 Run을 협업 모드로 전환할 때 활성 credential lease를 폐기합니다.
- 공유 후 접근 가능한 메시지, Artifact, Project file과 실행 action을 전환 전에 preview합니다.
- 단순 공유 링크는 live Workspace, Tool log의 비밀 필드와 실행 권한을 포함하지 않습니다.
- 협업 참가자의 steer·승인·취소는 actor ID와 함께 감사 기록에 남깁니다.
- 공동 작업 중 사용할 Connector는 Project용 service connection 또는 참여자별 delegated connection으로 다시 선택합니다.

## 6. 승인을 범위와 만료가 있는 Permission Lease로

### Manus에서 확인한 점

Manus의 로컬 컴퓨터 접근은 사용자가 허용한 폴더에서 동작하고, 위험 작업 승인 시 현재 task 또는 현재 path로 범위를 제한할 수 있습니다. 매 명령을 묻지 않으면서도 승인이 무제한 권한으로 변하지 않게 하는 방식입니다.

### Lumina의 빈틈

Lumina는 `awaiting_approval`과 Tool 권한 검사를 정의하지만, 한 번의 승인이 뒤의 유사 Tool Call에 얼마나 재사용되는지는 명확하지 않습니다.

### 권장 계약

```text
PermissionLease
├─ actor_id
├─ run_id or session_id
├─ capability
├─ resource_scope: path | domain | connector_action | command_class
├─ effect_scope: read | write | send | publish | delete
├─ constraints
├─ issued_from_approval_id
├─ expires_at or max_uses
└─ revoked_at
```

- 기본 승인은 현재 Tool Call 한 번에만 유효합니다.
- 반복 허용은 `현재 Run`, `이 경로의 읽기`, `이 domain 조회`처럼 구체적인 scope를 사용합니다.
- 외부 전송, 공개 게시, 결제, 삭제와 credential 변경은 broad lease 대상에서 제외합니다.
- steer, Project 공유 전환, 권한 정책 변경과 Run 종료 시 관련 lease를 재평가하거나 폐기합니다.

## 7. 예약 작업은 시간보다 Context 배치가 중요

### Manus에서 확인한 점

Scheduled Tasks 2.0은 같은 일정이라도 다음을 선택하게 합니다.

- 기존 Task의 대화·파일·결과를 이어서 실행할지
- 매번 독립 Task로 시작할지
- Project의 Skill·Connector·출력 표준을 사용할지
- 같은 dashboard·report Artifact를 계속 갱신할지
- 신뢰된 workflow에서 반복 승인을 생략할지

### Lumina의 빈틈

Lumina의 예약 작업 요구사항은 실행 snapshot과 이력을 포함하지만, 반복 실행이 어느 Session Context에 붙고 어떤 Artifact identity를 유지하는지 더 명시할 필요가 있습니다.

### 권장 계약

```text
ScheduleDefinition
├─ context_mode: continue_session | new_session_per_run
├─ project_id
├─ source_session_id optional
├─ execution_environment_policy
├─ extension_snapshot_policy: pinned | latest_allowed
├─ target_artifact_id optional
├─ artifact_update_mode: new_version | new_artifact
├─ approval_policy_id
└─ connector_binding_ids[]
```

- `continue_session`은 이전 결과에 의존하는 추적·후속 보고에 사용합니다.
- `new_session_per_run`은 각 실행을 독립적으로 감사·삭제해야 하는 batch에 사용합니다.
- 같은 보고서를 갱신할 때는 파일명 추측이 아니라 안정적인 `artifact_id`에 새 version을 추가합니다.
- `latest_allowed` extension은 실행 직전 권한과 호환성을 다시 확인하고 실제 사용 version을 Run snapshot에 남깁니다.
- 반복 승인 생략은 Schedule 자체가 아니라 별도 Permission Lease·조직 정책으로 관리합니다.

## 낮은 우선순위지만 유용한 실행 교훈

### KV cache hit rate를 Agent 운영 지표로

Manus는 Agent가 긴 입력과 짧은 action 출력을 반복하므로 KV cache hit rate가 비용과 latency에 큰 영향을 준다고 설명합니다. Lumina도 Run 중 system prefix, Tool schema 순서와 serialization을 안정적으로 유지하고 다음을 측정할 가치가 있습니다.

- provider별 prompt cache hit 또는 cached input token
- Turn별 prefix 변경 원인
- 동적 Tool 목록 변경으로 잃은 cache 이득
- compaction 전후 latency와 비용

이는 `HERMES_USER_FEATURES.md`의 “긴 대화의 Context를 불필요하게 흔들지 않기”를 운영 지표로 구체화하는 보강 사항입니다.

### 정상 성공률과 별도로 복구 능력을 평가

Manus는 오류 복구를 Agent 행동의 핵심으로 봅니다. Lumina eval에는 정상 경로 외에 다음 fault injection을 포함하는 편이 좋습니다.

- Tool timeout 후 대체 경로 선택
- Browser selector 변경 후 재탐색
- Worker 재시작 후 checkpoint 재개
- 일부 Batch item 실패 후 실패 항목만 재시도
- Artifact 원본 참조 누락 후 사용자에게 명확한 복구 선택지 제시
- credential lease 만료 후 안전한 재승인

## 반영 우선순위

### P0 — 기존 핵심 설계에 지금 추가

1. `ExecutionEnvironment` 유형과 Run snapshot 계약
2. `CompactedContextEntry.recovery_ref`와 복원 가능 Context 원칙
3. sharing, project membership, run collaboration의 권한 분리

### P1 — Plan·Project 구현 전에 추가

4. `BatchFanoutStep`과 per-item fresh context
5. `ProjectLearningProposal`의 diff·승인·version·rollback
6. scoped `PermissionLease`

### P2 — 예약·운영 기능 구현 전에 추가

7. Schedule의 `context_mode`와 `target_artifact_id`
8. KV cache·복구 능력 운영 지표와 eval

## 제안하는 문서 반영 위치

| 반영 대상 | 추가할 내용 |
|---|---|
| `AGENT_LOOP.md` | 복원 가능한 Context 압축, bounded plan recitation, Batch Fan-out, Permission Lease |
| `COWORK_FEATURE_REQUIREMENTS.md` | Execution Environment, Project Learning Proposal, 예약 Context mode |
| `HERMES_USER_FEATURES.md` | 공유와 공동 실행의 차이, credential boundary reset |
| 별도 보안 결정 문서 | 환경별 trust boundary, Connector·browser session 승계 금지 |
| eval 요구사항 | recovery fault injection과 batch item 품질 일관성 |

## 공식 자료

아래는 2026-07-11에 확인한 Manus 공식 문서와 공식 블로그입니다. 제품 동작은 바뀔 수 있으므로 실제 구현 직전에 다시 확인합니다.

- Manus Documentation Index: https://manus.im/docs/llms.txt
- Wide Research: https://manus.im/docs/features/wide-research
- Context Engineering for AI Agents: https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
- Understanding Manus Sandbox: https://manus.im/blog/manus-sandbox
- What is the Cloud Computer?: https://help.manus.im/en/articles/15392111-what-is-the-cloud-computer
- What is the “My Computer” feature capable of?: https://help.manus.im/en/articles/14178443-what-is-the-my-computer-feature-capable-of
- Browser Operator: https://manus.im/en/blog/manus-browser-operator
- New: Projects That Learn From Every Task: https://manus.im/blog/manus-projects-self-updating
- Introducing Scheduled Tasks 2.0: https://manus.im/blog/manus-schedules
- Manus Collab Help: https://help.manus.im/en/articles/12135428-how-can-i-use-manus-collab

## 최종 판단

Manus에서 가장 배울 점은 기능의 개수가 아니라 **Agent가 행동하는 컴퓨터, Context, 권한과 협업 경계를 제품 객체로 분리했다는 것**입니다.

Lumina는 이미 Run·Queue·복구·Project·Artifact의 큰 골격이 잘 잡혀 있습니다. 여기에 다음 세 문장을 핵심 불변 조건으로 추가하면 Manus의 고유한 교훈을 중복 없이 흡수할 수 있습니다.

> 모든 Run은 어디에서 실행되고 무엇이 얼마나 오래 남는지 설명할 수 있어야 합니다.

> Context에서 제거한 정보는 권한을 지키면서 원문으로 돌아갈 수 있어야 합니다.

> 결과를 보여주는 공유와 Agent·Workspace를 함께 조작하는 협업은 같은 권한이 아닙니다.

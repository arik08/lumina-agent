# 심층분석 Mission Workflow 최종 설계

> 문서 상태: 최종 Target 구현 계약
> 작성일: 2026-07-17
> 최종 수정: 2026-07-18
> 적용 범위: Lumina Agent의 장기·대형 분석 Workflow, 단위별 LLM 출력 보존, 수치 계산, 비용 추적과 결과 보고
> 구현 상태: 이 문서는 구현 기준으로 사용할 최종 목표 계약이며 현재 source·migration·test의 구현 완료를 뜻하지 않습니다.

## 0. 구현 현황

2026-07-18 기준으로 첫 end-to-end 실행 Slice가 구현되어 있습니다. 아래 Target 전체가 완료된 것은 아니지만, Mission 생성부터 exact 자료 고정, 실제 Core Run 5단계 실행, Python 계산, Node별 산출물·비용 기록과 최종 보고서까지 제품 경로가 연결되어 있습니다.

구현된 범위는 다음과 같습니다.

- Lumina 공통 Shell의 독립 `심층분석` 메뉴와 lazy-loaded Workspace Frontend module
- Project에 귀속되는 `Mission`, `WorkflowRevision`, `WorkflowNode`, `WorkflowEdge` 분리 entity와 실행 lineage migration `0034`, `0036`
- Mission 목록·생성·상세 조회·revision CAS 수정 API, 기존 Project read/write 권한 재검증과 audit event
- Mission 생성 시 서버에 고정되는 zero-based Workflow revision 1, 기본 5개 Node와 4개 Edge
- Mission 생성 form, Mission 목록, `Workflow` Canvas, Node 선택·Inspector, 누적 비용과 opt-in Node별 비용 표시
- Project write 권한과 revision을 확인하고 동일 버튼 2단계 확인으로 수행하는 Mission·Workflow cascade 삭제. Mission 산출물 ProjectFile도 soft delete하여 orphan folder를 남기지 않음
- 각 Node를 기존 Lumina Core `Run`으로 실행하는 orchestration adapter, 숨김 `deep_analysis` Conversation과 Run·Node foreign reference
- 완료된 LLM 응답 bytes를 추가 LLM 호출 없이 `심층분석/{Mission명}_{ID}/{Node ID}_{작업명}.md` Project 파일로 저장하는 평면 산출물 계약
- Run 완료 시 다음 Node를 DB transaction으로 생성·연결하고 Worker Queue에 넣는 순차 실행, 실패·취소·Backend 재시작 뒤 terminal 동기화
- Mission 시작 시 활성 ProjectFile의 `file ID·version ID·version·digest·path·MIME·size`를 고정하고 모든 후속 Node와 Workspace Tool이 해당 버전을 읽는 exact source manifest
- 이전 Mission의 `심층분석/` 산출물은 새 Mission의 원본 입력에 자동 포함하지 않고, 현재 Mission이 생성한 선행 Node 산출물만 후속 Run manifest에 추가하는 Context 경계
- CSV 입력만 허용하고 import·file·network·dynamic code·private attribute를 차단하는 `run_python_calculation` Tool. 격리 Python process, 12초 timeout, 입력·행·열·script·정적 반복 크기 한계를 적용하고 실행 `.py`와 결과 `.csv`를 평면 Mission 경로에 저장
- 실패·중단 Node를 새 Core Run으로 재실행하고 이전 Run ID·상태·오류·시간·비용을 `runHistory`에 보존하며 선택 Node 이후 결과만 초기화하는 retry 계약
- Provider usage의 `cost_usd`를 Node·Mission `microusd` projection으로 누적하고 Mission 예산을 다음 Run의 hard limit과 Node 전환 Gate에 반영
- Node 특성별 기본 실행 Profile: 범위 확정은 `standard·brief`, 자료 확인은 `standard·standard`, 분석·합성은 `deep·standard`, 최종 보고서는 `deep·detailed`
- 실행 중 현재 Node·실제 Run 상태와 최대 6,000자의 live output을 polling으로 표시하고, 완료 문서 요약·전체 Markdown·저장 경로·계산 파일·과거 시도·비용을 Inspector에 표시
- revision CAS와 Project write 권한을 적용한 `중단` 동작과 기존 Mission·첫 활성 Node의 상태 정리
- 배율과 무관한 transform 기반 Workflow 좌클릭 drag pan, 포인터 기준 wheel zoom(40~180%), 화면 내 확대·배율·축소·위치 초기화 control
- 우상단 누적 비용 icon·hover 요약·Node별 opt-in 상세와 닫을 때 전체 Graph를 현재 viewport에 자동 맞춤하는 Node Inspector
- Canvas 내부의 숨은 native scroll 상태를 금지하여 Inspector를 닫거나 viewport가 넓어져도 Node가 잘리지 않는 배치
- Backend DB를 원본으로 한 새로고침 복원과 Project별 마지막 선택 Mission 복원

아직 구현되지 않은 핵심 Target은 질문·Decision Node, Node 위치 편집·connect와 Draft revision, 심층분석 canonical event projection, Workflow Pattern, Claim·Evidence·Quality Gate, Mission export입니다. 현재 기본 5개 Node는 순차 실행이고, typed source manifest는 구현됐지만 Claim·Evidence 단위의 선택형 Context 조립은 후속 Slice입니다.

현재 Slice는 전용 Backend test 10개에서 Mock 5단계 완주, 취소·재시도·시도 이력, source version 고정, Mission 산출물 입력 제외·삭제 연동, Python 계산의 frozen CSV 사용과 위험 script 차단을 검증했습니다. Ruff, Frontend 심층분석 test 8개, typecheck·production build와 migration `0001 → 0036`도 통과했습니다.

격리 port `15252`·`15253`의 실제 GPT-5.5 검증에서는 `inputs/cost-variance.csv` 1개를 고정 입력으로 사용해 N001부터 N040까지 5개 Node를 완주했습니다. 5개 Markdown, N010·N020·N030의 Python·CSV 6개를 합쳐 총 11개 파일을 생성했고, 전기 1,850·당기 2,240·증감 +390과 기여율을 재현 계산했습니다. Node 비용은 N001 `US$0.0672`, N010 `US$0.2140`, N020 `US$0.3171`, N030 `US$0.4530`, N040 `US$0.0498`, Mission 합계 `US$1.1010`으로 기록됐습니다. 브라우저에서 live output, 중단, 삭제 2단계 확인, 40% 좌클릭 pan, wheel zoom, 빈 Canvas click Inspector 닫기, 닫은 뒤 전체 Node fit, 비용 popover, 파일 tree와 console error 0건을 확인했습니다.

## 1. 목적

`심층분석`은 하나의 채팅 Session이나 한 번의 긴 Run으로 다루기 어려운 업무를 위한 독립 기능입니다. 사용자가 큰 목적을 전달하면 Lumina는 이를 실행 가능한 Workflow로 전개하고, 질문·자료 확인·계산·분석·검증·합성을 단계별로 수행합니다. 조사 결과에 따라 Workflow를 확장한 뒤 여러 결과를 다시 수렴하여 결론과 보고서를 만듭니다.

대표적인 대상은 다음과 같습니다.

- 전사 원가·매출·수익성 변동 원인 분석
- 생산성·품질·공급망·인력·투자 우선순위 분석
- 여러 부서 자료와 외부 근거를 함께 사용하는 장기 조사
- 수치 계산, 사용자 의사결정과 감사 가능한 근거가 모두 필요한 업무

심층분석의 핵심 결과는 최종 보고서 하나만이 아닙니다. 각 작업 단위의 LLM 출력, 계산 코드와 결과, 사용자 결정, 검증 결과, 실행 이력과 비용을 보존하여 결론이 만들어진 전체 과정을 다시 확인할 수 있어야 합니다.

## 2. 핵심 원칙

1. `심층분석`은 `파일`의 하위 기능이 아니라 Lumina의 독립적인 최상위 업무 기능입니다.
2. 큰 작업 하나를 `Mission`으로 부르고, Mission 안의 실행 단위를 `Workflow Node`로 관리합니다.
3. 화면의 기본 용어는 기술적인 `Graph`가 아니라 사용자가 이해하기 쉬운 `Workflow`를 사용합니다.
4. Workflow는 처음부터 고정하지 않습니다. AI가 초기 Workflow를 제안하고, 실행 중 새 근거와 이상치에 따라 Node 확장을 제안할 수 있습니다.
5. 각 Node에서 사용자에게 제시한 LLM 출력 결과를 별도 재작성 없이 그대로 Markdown 파일로 저장합니다.
6. 중요한 수치 계산은 LLM이 직접 수행하지 않고 Python 등 결정적인 실행 코드로 계산하며 결과를 CSV와 검증 기록으로 남깁니다.
7. 파일은 Mission 폴더까지만 기본 물리 계층으로 만들고, Node별 불필요한 하위 폴더를 자동 생성하지 않습니다.
8. 기본 화면에는 Mission 누적 비용과 예산 대비 사용률만 표시합니다. Node별 비용은 사용자가 상세 화면을 열거나 명시적으로 켰을 때만 표시합니다.
9. DB와 관리 Storage가 상태의 원본입니다. Markdown, CSV와 Python 파일은 사용자가 읽고 다운로드할 수 있는 불변 결과물이며 Frontend cache가 원본이 되지 않습니다.
10. Context 한계는 원문 삭제가 아니라 필요한 Node 출력만 선택하는 Context 조립과 단계적 압축으로 관리합니다.
11. 모든 Workflow를 Pattern으로 만들거나 Pattern에서 시작하도록 강제하지 않습니다. 새롭거나 일회성인 업무는 AI가 제로베이스로 설계하고, 반복 가치가 있는 업무에만 `Workflow Pattern`을 선택적으로 재사용합니다.
12. Mission은 보고서 생성 여부가 아니라 시작 시 합의한 Charter와 Completion Contract의 충족 여부로 완료를 판정합니다.
13. 핵심 결론은 Claim으로 관리하고 supporting·contradicting Evidence, 계산 결과, 미해결 항목과 원본 locator를 역추적할 수 있어야 합니다.
14. 최종 확정 전에 수치·근거·상충·stale·완료 조건을 검사하는 Quality Gate를 통과하거나 명시적인 사용자 waiver를 기록합니다.
15. 비용 최적화는 결과 재사용, 호출 제거, Context 선택, prefix cache와 Model routing 순으로 적용하며 품질 회귀·재실행·질문 부담까지 함께 계측합니다.

## 3. 제품 계층과 용어

Lumina의 기존 업무 계층을 유지하면서 Project 아래에 Mission 집계 객체를 추가합니다.

```text
Organization
└─ Project
   ├─ Workflow Pattern Library
   ├─ Mission
   │  ├─ Mission Charter and Completion Contract
   │  ├─ Workflow Revision
   │  ├─ Workflow Node
   │  ├─ Node Execution
   │  ├─ Decision
   │  ├─ Claim and Open Issue
   │  ├─ Evidence Reference
   │  ├─ Quality Gate Result
   │  ├─ Usage and Cost
   │  └─ Generated Files
   └─ Session
      └─ Run
```

- `Mission`: 장기 업무의 목표, 완료 기준, Workflow, 비용과 결과를 묶는 사용자 단위입니다.
- `Mission Charter`: 목적, 핵심 질문, 범위, 산출물, 품질, 예산, 기한과 자율성에 대한 시작 계약입니다.
- `Completion Contract`: Charter 중 Backend가 검사할 수 있는 완료 조건과 허용 예외입니다.
- `Workflow Revision`: 실행 시점에 고정한 Node와 Edge 구성입니다.
- `Workflow Node`: 질문, 자료, 계산, 분석, 검증, 합성 또는 보고서 작성 같은 의미 있는 작업 단위입니다.
- `Node Execution`: 특정 Workflow revision과 입력 snapshot으로 Node를 실행한 한 번의 시도입니다.
- `Decision`: 사용자에게 제시한 선택지, AI 권고, 사용자 답변, 적용 범위와 변경 이력입니다.
- `Evidence Reference`: Project 파일, 생성 파일, 외부 출처 또는 Tool 결과의 정확한 version 참조입니다.
- `Claim`: 분석에서 도출한 관찰·핵심 원인·권고이며 supporting·contradicting Evidence와 검증 상태를 가집니다.
- `Quality Gate`: 최종 결과가 수치·근거·상충·stale·Completion Contract 기준을 만족하는지 판정한 불변 결과입니다.
- `Workflow Pattern`: 반복 업무에서 재사용하는 versioned 설계 자산입니다. 단계의 목적, 선후관계, 입력·출력 계약, 질문 지점, 선택 분기와 안전 한계는 담지만 특정 Mission의 답변·파일·수치·결론은 담지 않습니다.

Mission은 여러 Session과 Run을 연결할 수 있습니다. Session은 대화 화면이고 Mission은 전체 Workflow와 결과의 원본입니다. 하나의 거대한 대화 Context에 Mission 전체 상태를 넣지 않습니다. Mission의 `base_pattern_version_id`와 조합한 Sub-workflow Pattern reference는 nullable이며 Pattern을 사용하지 않은 Mission도 완전한 1급 객체입니다.

### 3.1 Module형 UI와 Backend 경계

심층분석은 기존 일반 채팅 화면에 조건문을 추가하는 방식이 아니라, Lumina 공통 Shell에 장착하는 두 번째 builtin Workspace Frontend로 구현합니다. 동시에 Mission·Workflow·Node 같은 전용 업무 로직은 별도 Backend domain module에 두고, 신뢰·복구·운영 경계는 기존 Core Backend를 재사용합니다.

```text
Lumina 공통 Shell
└─ DeepAnalysisFrontend builtin module
   └─ Deep Analysis Backend domain module
      ├─ Mission
      ├─ Workflow Revision
      ├─ Node and Edge
      ├─ Node Execution
      ├─ Decision and stale propagation
      ├─ Claim·Evidence·Open Issue와 Quality Gate
      ├─ Mission Context assembly
      └─ 단위별 MD·CSV·PY 관리
             ↓
         Lumina Core
         ├─ 인증·권한과 Project 격리
         ├─ Session·Run·Queue와 Provider
         ├─ Tool 승인과 sandbox
         ├─ canonical event와 replay
         ├─ File·Artifact Storage와 version
         ├─ usage 원시 계측과 가격 계산
         ├─ 감사·알림
         └─ 중단·재접속·Worker restart 복구
```

이 구조는 Frontend만 분리하고 Backend를 Core에 섞는 방식도, 심층분석이 독자적인 Run·Storage·권한 체계를 다시 만드는 방식도 아닙니다. Frontend와 전용 Backend 업무 로직은 하나의 제거 가능한 vertical module 경계를 이루고, 공통 신뢰 기능은 Core가 소유합니다.

### 3.2 Frontend module

`deep-analysis`는 Lumina와 함께 검토·build하는 builtin module입니다. 사용자 설치, runtime 자동 탐색, 원격 JavaScript loader와 범용 Plugin Framework를 만들지 않습니다.

```text
apps/web/src/agent-frontends/deep-analysis/
├─ DeepAnalysisFrontend.tsx
├─ MissionList.tsx
├─ PatternLibrary.tsx
├─ WorkflowCanvas.tsx
├─ NodeInspector.tsx
├─ ExecutionDrawer.tsx
├─ DecisionPanel.tsx
├─ ClaimEvidencePanel.tsx
├─ QualityGatePanel.tsx
├─ CostPanel.tsx
└─ module styles and tests
```

이 경로와 파일명은 구현 시 현재 Frontend 구조에 맞게 조정할 수 있지만 책임 경계는 유지합니다.

- 공통 Shell은 로그인, Project 선택, 전역 내비게이션, 알림과 설정을 소유합니다.
- `DeepAnalysisFrontend`는 Mission 목록, Workflow Pattern Library, Workflow Canvas, Node Inspector, 실행 Drawer, 자료·결정·Claim·Evidence·Quality Gate·비용·보고서 화면을 소유합니다.
- 일반 채팅의 component와 내부 state를 직접 import하지 않고 공통 Frontend SDK와 typed contract만 사용합니다.
- `App.tsx`, 전역 CSS와 공용 type 여러 곳에 `deep-analysis` 조건문을 흩뿌리지 않습니다.
- 알 수 없거나 호환되지 않는 contract는 안전한 fallback을 제공하되 Mission·Run·파일 원본을 삭제하거나 다른 객체로 바꾸지 않습니다.

현재 Agent Frontend 선택은 Conversation 중심이므로 심층분석을 계기로 공통 Shell에 최소한의 builtin `Workspace Frontend Slot`을 추가합니다.

```text
Lumina Web Shell
├─ Conversation Frontend Slot
│  └─ general-chat
└─ Workspace Frontend Slot
   └─ deep-analysis
```

두 번째 실제 module에서 확인된 요구만 contract로 추출합니다. `moduleKind`, 원격 package, module DB registry와 추상 base class를 예상만으로 먼저 일반화하지 않습니다.

### 3.3 Backend domain module

심층분석 전용 Backend는 사용자 기능 단위의 vertical module로 둡니다.

```text
apps/server/src/lumina/deep_analysis/
├─ models.py
├─ schemas.py
├─ repository.py
├─ service.py
├─ workflow.py
├─ executor.py
├─ context.py
├─ files.py
├─ costs.py
├─ claims.py
├─ quality.py
└─ routes.py
```

파일 분리는 구현 규모에 따라 합칠 수 있으며 entity마다 기계적으로 Repository·Service를 만들지 않습니다. 이 module이 소유할 책임은 다음과 같습니다.

- Mission 생명주기와 완료 기준
- Workflow Pattern의 scope·version·입출력 계약과 Mission별 인스턴스화
- Workflow Draft·실행 revision, Node·Edge와 dependency
- AI 제안 Node, 확장 제한과 사용자 결정 반영
- Node 입력 조립, 완료 조건과 stale 전파
- Claim·Evidence·Open Issue와 Mission Quality Gate
- 단위별 LLM 출력 Markdown 승격과 평면 파일명
- Python·CSV 계산 결과와 Mission 파일 lineage
- Mission 누적 비용 집계와 breakdown projection
- Workflow·Node 중심의 typed API와 module event projection

다음 기능은 심층분석 module이 다시 구현하지 않습니다.

- 사용자 인증과 Project 권한
- Provider·Model 호출과 Tool Loop
- Run Queue, pause·resume·cancel과 worker recovery
- Tool 승인, sandbox와 외부 side effect 보호
- File·Artifact blob 저장과 immutable version
- Provider usage 원시 계측과 가격표 계산
- canonical audit, notification과 event replay

Node Executor는 Core Run Executor 위의 orchestration adapter입니다. 심층분석 전용 LLM transport, 독립 Queue 또는 별도 복구 loop를 만들지 않습니다.

### 3.4 파일 Root 연동

`파일 → 심층분석`을 표시하기 위해 공용 파일 화면이 Mission과 Node 내부 구조를 직접 알게 만들지 않습니다. 공용 탐색기는 최소 File Root provider contract를 사용하고, 심층분석 module이 자신의 root와 항목을 제공합니다.

```text
File Explorer
├─ ProjectFileRootProvider
└─ DeepAnalysisFileRootProvider
```

provider는 root ID·label, 자식 목록, 파일 상세, preview와 download에 필요한 stable ID만 제공합니다. rename·delete·새 version처럼 허용되는 action은 root capability로 명시합니다. 심층분석 파일을 보여주기 위해 `ProjectFilesView` 곳곳에 Mission·Node 조건문을 추가하지 않습니다.

### 3.5 Core와 module 배치 기준

| 질문 | 배치 위치 |
|---|---|
| 모든 화면이 동일하게 신뢰해야 하는 인증·권한·Run·복구인가 | Core Backend |
| File blob, immutable version, usage 원시값처럼 UI와 무관한 공통 capability인가 | Core Backend |
| Mission·Workflow·Node·계산 orchestration처럼 심층분석 전용 업무인가 | Deep Analysis Backend module |
| Canvas, Inspector, Drawer, 자료·결정·비용 배치와 상호작용인가 | Deep Analysis Frontend module |
| `파일` 화면에 root를 조합하는 공통 기능인가 | Core File Explorer contract |
| `심층분석` root의 항목·capability와 Node 이동 규칙인가 | Deep Analysis file provider |

Module을 registry에서 제거하고 Frontend·Backend module 폴더를 삭제했을 때 Core 인증·채팅·Run·파일·Artifact가 계속 동작해야 합니다. 전용 영속 데이터의 코드 제거와 보존·export·정리 migration은 별도 단계로 처리합니다.

### 3.6 최소 영속 데이터 계약

다음은 구현 시 필요한 논리 entity입니다. 실제 ORM 파일 분리는 현재 Repository 관례에 맞추되 Mission·Workflow·Node를 하나의 JSON blob으로 저장하지 않습니다. 관계, 상태 전이, 권한, stale 전파와 부분 재실행을 Backend가 query할 수 있어야 합니다.

| Entity | 필수 책임과 주요 필드 |
|---|---|
| `Mission` | `id`, `organization_id`, `project_id`, `created_by`, title, objective, status, autonomy mode, budget·deadline, Completion Contract, active draft·execution revision, nullable base Pattern version, optimistic revision, timestamps |
| `WorkflowPattern` | scope, owner, name, lifecycle status와 latest published version pointer |
| `WorkflowPatternVersion` | immutable node·edge blueprint, semantic input roles, conditional branch, adaptive slot, policy, digest와 parent version |
| `WorkflowRevision` | Mission ID, revision number, draft·active·superseded 상태, optional Pattern references, 생성 이유, created by, canonical graph digest |
| `WorkflowNode` | revision ID, stable Node ID, type, title, purpose, typed input·output, completion gate, context·cost budget, Tool·Node Profile, UI position |
| `WorkflowEdge` | revision ID, source·target Node, dependency type, condition, merge rule와 display order |
| `NodeExecution` | Node와 Workflow revision, attempt, Core Run ID, status, input·Context manifest, model·tool snapshot, output file references, usage, validation과 error |
| `Decision` | 질문·선택지·AI 권고·사용자 답변, requester·decider, 적용 revision, 영향 Node, status와 immutable history |
| `Claim` | source Node, statement, level, status, confidence, materiality, report inclusion과 latest validation |
| `EvidenceReference` | source type·stable ID·exact version·digest·locator, supporting·contradicting·context stance, 연결 Claim |
| `ContextManifest` | Node Execution에 전달한 exact·extractive·reference·compressed Item, 순서, token estimate, lineage와 prefix hash |
| `MissionFileLink` | 생성·참조 파일 stable ID, exact version, producing Node Execution, purpose, validation과 stale 상태 |

Provider usage, File blob·version, Artifact, Core Run·event와 audit 원본은 기존 Core entity를 재사용합니다. Deep Analysis module은 이 값을 복제하지 않고 stable foreign reference와 Mission projection만 소유합니다. JSON field는 Node의 bounded typed config나 snapshot처럼 한 번에 읽는 불변 payload에 사용할 수 있지만 권한·상태·lineage query가 필요한 관계를 JSON 안에 숨기지 않습니다.

모든 write API는 Backend 권한 검사, optimistic revision 또는 ETag와 idempotency key를 사용합니다. Workflow revision, Pattern version, Decision history, Claim validation과 Node Execution은 확정 뒤 덮어쓰지 않고 새 version·attempt·event를 추가합니다.

### 3.7 최소 API 계약

구체적인 path naming은 기존 route convention에 맞추되 Frontend가 필요로 하는 capability는 다음과 같습니다.

```text
Mission
POST   /projects/{project_id}/deep-analysis/missions
GET    /projects/{project_id}/deep-analysis/missions
GET    /deep-analysis/missions/{mission_id}
PATCH  /deep-analysis/missions/{mission_id}
POST   /deep-analysis/missions/{mission_id}/plan
POST   /deep-analysis/missions/{mission_id}/start
POST   /deep-analysis/missions/{mission_id}/pause
POST   /deep-analysis/missions/{mission_id}/resume
POST   /deep-analysis/missions/{mission_id}/cancel

Workflow
GET    /deep-analysis/missions/{mission_id}/revisions
POST   /deep-analysis/missions/{mission_id}/revisions
PATCH  /deep-analysis/missions/{mission_id}/draft
POST   /deep-analysis/missions/{mission_id}/draft/activate
POST   /deep-analysis/missions/{mission_id}/nodes/{node_id}/retry
POST   /deep-analysis/missions/{mission_id}/proposals/{proposal_id}/decide

Decision·Claim·Evidence
GET    /deep-analysis/missions/{mission_id}/decisions
POST   /deep-analysis/missions/{mission_id}/decisions/{decision_id}/answer
GET    /deep-analysis/missions/{mission_id}/claims
GET    /deep-analysis/missions/{mission_id}/evidence
POST   /deep-analysis/missions/{mission_id}/quality-gate

File·Cost·Export
GET    /deep-analysis/missions/{mission_id}/files
GET    /deep-analysis/missions/{mission_id}/usage
GET    /deep-analysis/missions/{mission_id}/costs
POST   /deep-analysis/missions/{mission_id}/exports

Pattern
GET    /projects/{project_id}/deep-analysis/patterns
POST   /projects/{project_id}/deep-analysis/patterns
POST   /deep-analysis/patterns/{pattern_id}/versions
POST   /deep-analysis/patterns/{pattern_id}/versions/{version_id}/publish
```

`start`, `pause`, `resume`, `cancel`, `retry`, Decision 답변, proposal 결정과 export는 중복 요청에 안전해야 합니다. Frontend가 Node 상태를 계산하지 않고 Mission snapshot과 canonical event를 합쳐 표시합니다. 목록은 cursor pagination, 상세 write는 ETag·expected revision, 긴 실행과 export는 비동기 operation ID를 사용합니다.

### 3.8 Canonical event 계약

Deep Analysis 전용 event는 Core event envelope와 sequence·replay를 사용합니다. 초기 필수 event는 다음과 같습니다.

```text
mission_created
mission_charter_updated
mission_status_changed
workflow_draft_created
workflow_revision_activated
workflow_expansion_proposed
workflow_expansion_decided
node_queued
node_started
node_output_delta
node_completed
node_validation_failed
node_failed
node_stale
decision_requested
decision_resolved
claim_recorded
claim_status_changed
evidence_linked
mission_file_created
mission_cost_updated
mission_budget_warning
quality_gate_completed
mission_completed
```

event에는 사용자 입력·원본 파일·LLM 출력·Secret을 중복 저장하지 않고 stable ID, status, revision, sequence와 화면 복원에 필요한 최소 projection만 넣습니다. 대용량 output은 File·Artifact Storage, 실행 원본은 Node Execution·Run, 사용자에게 보이는 최신 상태는 Mission snapshot이 담당합니다.

## 4. 사용자 흐름

```text
큰 업무 목적 입력
→ Mission 목표·범위·완료 기준 제안
→ 시작 방식 결정
   ├─ 제로베이스: AI가 목적에 맞춰 새 Workflow Draft 설계
   ├─ Pattern 보조: 관련 부분만 추천·조합하여 Draft 설계
   └─ Pattern 지정: 사용자가 고른 Pattern을 Mission에 맞게 변형
→ 선택한 방식과 목표·자료에 맞는 최소 질문
→ Mission 전용 초기 Workflow Draft 확정
→ 사용자 검토·수정·승인
→ 실행 가능한 Node 순차·병렬 실행
→ 필요한 질문과 결정 요청
→ 새로운 분석 Node 제안 또는 자동 확장
→ 계산·분석·검증 결과 축적
→ Claim·supporting·contradicting Evidence와 Open Issue 축적
→ Synthesis Node에서 결과 수렴
→ Quality Gate에서 Completion Contract 검사
→ 최종 결론과 보고서 생성 또는 미충족 결과 확정
→ 전체 과정·파일·비용·근거 검토 및 다운로드
→ 반복 가치가 확인된 개선을 Pattern의 새 후보 version으로 제안
```

AI는 되돌릴 수 있고 결과에 미치는 영향이 작은 사항을 매번 묻지 않습니다. 결과를 크게 바꾸는 범위, 기준, 고비용 확장, 외부 쓰기와 권한 상승만 명시적인 질문이나 승인을 요구합니다.

### 4.1 Mission Charter와 Completion Contract

Mission 생성 직후 AI는 긴 Workflow보다 먼저 짧은 `Mission Charter`를 제안합니다. 사용자가 직접 수정할 수 있으며 실행 시작 시 revision으로 고정합니다.

```text
목적
반드시 답해야 하는 핵심 질문
필수 산출물과 독자
포함 범위와 제외 범위
비교 기준·기간·단위·통화
사용 가능한 자료와 추가로 필요한 자료
수치 정합성·근거 coverage·신뢰도 기준
허용 가능한 미설명 잔차와 미해결 항목 한도
예산·기한·자율성 mode
최종 사용자 검토 또는 승인 필요 여부
```

`Completion Contract`는 Charter 중 기계적으로 검사 가능한 완료 조건입니다. 예를 들어 `전체 변동액의 95% 이상 설명`, `핵심 Claim의 100%가 검증된 Evidence 또는 계산 결과와 연결`, `stale·validation_failed 결과 0건`, `경영진 보고서와 계산 CSV 생성`처럼 정의합니다.

AI가 보고서를 생성했다는 사실만으로 Mission을 완료하지 않습니다. Quality Gate가 Completion Contract를 평가하고 충족하지 못한 항목, 예외 승인과 남은 위험을 함께 기록합니다. 사용자가 조건 미충족 상태에서 종료하면 `Decision`으로 waiver를 남기고 최종 결과에 예외를 표시합니다.

### 4.2 시작 방식

Mission은 다음 세 방식 중 하나로 계획할 수 있습니다.

| 방식 | 사용 시점 | 동작 |
|---|---|---|
| `zero_based` | 새롭거나 일회성인 업무 | AI와 사용자가 목적에 맞는 새 Workflow Draft를 설계 |
| `pattern_assisted` | 일부 반복 구간이 있는 업무 | 관련 Sub-workflow·Node Recipe만 선택적으로 조합 |
| `pattern_based` | 충분히 정형화된 반복 업무 | 지정 Pattern을 현재 Mission에 맞게 인스턴스화·변형 |

기본값은 `zero_based`이며 Pattern 추천은 선택 사항입니다. 시작 방식은 기록을 위한 provenance이지 실행 능력의 차이가 아닙니다.

### 4.3 자율성 Mode

Pattern 사용 여부와 별도로 Mission별 자율성 범위를 지정합니다.

| Mode | 자동 수행 범위 |
|---|---|
| `strict` | 승인된 Workflow 밖의 Node 추가·외부 요청·고비용 재실행을 모두 확인 |
| `balanced` | 기본값. 저비용·읽기 전용·되돌릴 수 있는 확장은 정책 한도 안에서 자동 수행 |
| `exploratory` | 명시 예산·depth·branch 한도 안에서 가설 탐색을 넓게 허용하되 외부 write·권한 상승은 계속 승인 |

Mode는 조직 상한을 넘을 수 없고 실행 시작 시 snapshot으로 고정합니다. 사용자가 실행 중 Mode를 바꾸면 새 Mission policy revision과 영향 범위를 기록하며 이미 수행한 작업을 소급 변경하지 않습니다.

### 4.4 Mission 상태와 완료 결과

```text
draft
→ planning
→ ready
→ running
↔ awaiting_input | paused
→ completing
→ completed | failed | cancelled | limit_reached
```

`completed`는 목표 충족을 무조건 뜻하지 않습니다. Quality Gate 결과를 별도 `completion_outcome`으로 기록합니다.

```text
satisfied
satisfied_with_exceptions
not_satisfied
```

자료 부족으로 결론을 낼 수 없다는 검증된 보고도 작업 완료 결과일 수 있으므로 `completed + not_satisfied`를 허용합니다. UI와 export는 이를 성공한 분석처럼 표시하지 않고 미충족 사유와 필요한 후속 자료를 보여줍니다.

## 5. 정보 구조와 화면

### 5.1 최상위 내비게이션

`심층분석`은 `에이전트`와 같은 수준의 독립 메뉴입니다.

```text
에이전트
심층분석
마켓스토어
라이브러리
파일
예약 작업
Memory
```

심층분석 첫 화면에는 Mission 목록을 표시합니다. 상단의 `새 Mission` 옆에 보조 동작 `Workflow 패턴`을 두되 Pattern Library를 별도 최상위 메뉴로 만들지는 않습니다.

```text
전사 영업원가 변동 원인 분석
진행 중 · 62% · 결정 대기 1건 · 누적 비용 184,300원

해외사업 수익성 개선 분석
일시 정지 · 38%

설비투자 우선순위 분석
완료 · 최종 보고서 생성
```

### 5.2 Mission Workspace

Mission을 열면 다음 탭을 같은 순서로 제공합니다.

```text
Workflow | 실행 과정 | 자료 | 의사결정 | 결론·근거 | 비용 | 보고서
```

- `Workflow`: Node를 배치·연결하고 실행 상태를 보는 주 화면
- `실행 과정`: 시간순 Node 실행, 질문, 승인, 실패, 재시도와 복구
- `자료`: 현재 Mission이 참조하거나 생성한 MD·CSV·PY와 원본 참조
- `의사결정`: 선택지, 권고, 답변, 영향 Node와 변경 이력
- `결론·근거`: Claim, supporting·contradicting Evidence, 미해결 항목과 Quality Gate
- `비용`: 단계·Node·Model·날짜·재실행별 사용량과 비용
- `보고서`: 중간 보고와 최종 결과, 검증 상태와 download

### 5.3 Workflow Canvas

Workflow 화면은 n8n과 유사한 드래그·연결 Canvas 상호작용을 사용하되 Lumina의 절제된 Light UI를 유지합니다.

- Canvas를 화면의 주 영역으로 사용합니다.
- `+ Node`를 누르면 Node 검색·추가 popover를 임시로 엽니다. Node 목록을 상시 고정해 Canvas를 좁히지 않습니다.
- Node를 Canvas로 끌어 놓고 연결점을 드래그해 Edge를 만듭니다.
- Node 클릭 시 오른쪽 Inspector를 열고 Canvas 빈 영역을 클릭하면 닫습니다.
- 실행 중에는 접을 수 있는 하단 Drawer에서 대화, 실행 트리, 입력, 출력, 로그와 비용을 확인합니다.
- 확대·축소, fit, 자동 정렬, 미니맵과 Sub-workflow 접기를 제공합니다.
- Keyboard로 Node 이동·연결·삭제·상세 열기와 focus 이동이 가능해야 합니다.

```text
┌─────────────────────────────────────────────────────────────┐
│ Mission 상태 · 누적 비용                        + Node      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [목표 확정] ─┬─ [원재료 분석] ─ [Python 계산] ─ [검증]    │
│               ├─ [제품믹스 분석]                            │
│               └─ [생산·수율 분석]                           │
│                              └─ [핵심 원인 합성] ─ [보고서] │
│                                                             │
│                     [Workflow 실행]                          │
├─────────────────────────────────────────────────────────────┤
│ 대화 | 실행 트리 | 입력 | 출력 | 로그 | 비용                │
└─────────────────────────────────────────────────────────────┘
```

일반 Node는 흰 표면과 얇은 선을 사용합니다. 선택과 실행 경로에만 cobalt를 사용하고, 완료는 icon과 `완료`, 결정 대기는 icon과 `결정 필요`, 실패는 icon과 오류 문구를 함께 표시합니다. 색상만으로 상태를 전달하지 않습니다.

### 5.4 설계와 실행 상태

Workflow 안에 `설계`와 `실행 상태` 모드를 둡니다.

- `설계`: Node 추가·삭제·이동·연결과 완료 조건 편집
- `실행 상태`: 현재 진행 경로, 결과, 실패, 재시도와 비용 확인

실행 시작 시 Workflow revision을 고정합니다. 실행 중 편집은 진행 중 revision을 바꾸지 않고 새 Draft revision을 만듭니다.

```text
실행 중: revision 7
편집 중: Draft revision 8
```

### 5.5 Workflow Pattern Library

Pattern Library는 자주 반복되는 업무 흐름을 찾고 관리하는 심층분석 내부 화면입니다. Pattern 카드는 이름, 적용 범위, 설명, 최근 version, 사용 횟수와 대표 완료율을 보여주며 `이 패턴으로 Mission 시작`, `미리보기`, `새 version 만들기`를 제공합니다.

새 Mission에서 사용자는 큰 목적만 먼저 입력할 수 있습니다. 기본 동작은 목적에 맞는 Workflow를 제로베이스로 설계하는 것이며, 높은 관련성이 있거나 사용자가 요청한 경우에만 Pattern을 보조 선택지로 추천합니다. 사용자는 `AI가 새로 설계`, `추천 패턴 활용`, `패턴에서 시작` 중 하나를 선택할 수 있고 추천을 무시할 수도 있습니다. Pattern이 없는 일회성 Mission도 기능·기록·복구·감사 측면에서 아무 제약이 없습니다. 완료 후에도 반복 가치가 확인될 때만 Pattern 후보로 제안합니다.

Pattern 미리보기에서는 다음을 구분해 표시합니다.

- 항상 수행하는 필수 단계
- 답변이나 데이터 상태에 따라 켜지는 조건부 단계
- Mission마다 AI가 새로 계획하는 적응 구간
- 비용·depth·외부 쓰기·승인 한계
- 필요한 입력과 최종 산출물 계약

## 6. Workflow Node

### 6.1 Node 종류

초기 제품은 다음 Node 종류를 제공합니다.

| 종류 | 역할 |
|---|---|
| 질문 | 분석에 필요한 범위·기준·자료를 사용자에게 질문 |
| 사용자 결정 | 선택지, AI 권고, 예상 영향과 비용을 제시하고 결정 대기 |
| 자료 | Project 파일, Mission 생성 파일, DB 조회나 외부 근거를 입력으로 고정 |
| Python 계산 | 정제, 집계, 통계와 수치 계산을 재현 가능한 코드로 실행 |
| AI 분석 | 계산 결과와 문서를 해석하고 가설·의미·추가 조사를 도출 |
| 검증 | 데이터 품질, 합계 정합성, 반대 근거와 완료 조건 검사 |
| 합성 | 여러 하위 결과를 비교하고 모순을 해소해 상위 결론 생성 |
| 보고서 | 검증된 합성 결과를 최종 산출물로 작성 |

Node 종류는 UI Profile일 뿐 권한 경계를 우회하지 않습니다. Python, 파일, Connector와 외부 Tool 실행은 기존 승인·sandbox·Project 권한 계약을 그대로 적용합니다.

### 6.2 Node 계약

각 Node는 최소한 다음 정보를 가집니다.

- 안정적인 Node ID와 표시 이름
- Node 종류와 상태
- 목적과 완료 조건
- 선행 Node와 의존 관계
- 입력 파일·이전 Node 출력·사용자 결정의 exact reference
- 실행 Provider, Model, Tool, Skill, MCP와 환경 snapshot
- 출력 파일과 후속 Node
- 현재·과거 실행, 오류와 재시도
- 검증 상태와 신뢰도
- Token, 시간과 비용

### 6.3 상태

```text
draft
→ proposed
→ queued
→ running
→ awaiting_input | awaiting_approval
→ completed | validation_failed | failed | cancelled | limit_reached
```

선행 입력이나 결정이 변경되면 완료 Node를 즉시 삭제하지 않고 `stale` 또는 `review_required`로 표시합니다. 영향받은 후속 Node도 관계를 따라 재검토 대상으로 표시하며 사용자가 선택적으로 재실행할 수 있어야 합니다.

### 6.4 AI 제안과 Workflow 확장

AI가 실행 중 추가 분석 필요성을 발견하면 Node를 바로 확정하지 않고 `AI 제안` 상태로 추가할 수 있습니다.

```text
물류비 원인 분석
예상 비용 12,000~18,000원
예상 시간 3~6분
기대 효과: 미설명 변동 8.4% 확인

[추가] [수정] [제외]
```

조직 정책이 허용한 저비용·읽기 전용 Node는 자동 확장할 수 있습니다. 예상 비용, 외부 요청량, 권한, depth 또는 branch 수가 기준을 넘으면 반드시 사용자 확인을 받습니다.

Workflow 폭발을 막기 위해 다음 제한을 둡니다.

- Mission과 Node별 시간·Token·비용 예산
- 최대 depth와 동시 branch 수
- 유사 가설과 중복 Node 병합
- 중요도·금액 영향도 threshold
- 반복해도 신뢰도가 개선되지 않는 분석 중단
- 미사용 branch 보관과 수동 재개

### 6.5 재사용 가능한 Workflow Pattern

`Workflow Pattern`은 과거 Mission의 Workflow를 그대로 복사하는 Template이 아니라, 유사한 다음 Mission을 계획할 때 선택적으로 사용하는 versioned 설계 자산입니다. Pattern은 직접 실행하지 않으며 사용하기로 한 경우에만 Mission 전용 Workflow Draft로 인스턴스화합니다. Pattern을 사용하지 않는 Mission은 AI 설계 또는 사용자 직접 편집으로 동일한 Workflow Draft를 만듭니다.

Pattern이 보존하는 항목은 다음과 같습니다.

- 업무 유형, 의도, 적용 조건과 기대 산출물
- 필수 stage와 Node 역할, dependency와 합류 조건
- Node별 typed input·output contract와 검증 규칙
- 시작 시 확인할 핵심 질문과 답변에 따른 조건부 branch
- AI가 자유롭게 분해·확장할 수 있는 adaptive slot
- 시간·비용·depth·동시 branch·외부 쓰기와 승인 policy
- 추천 Tool·계산 방식·보고서 구조와 품질 기준

Pattern에는 특정 Mission의 사용자 답변, Project 파일 ID, 원본 수치, 비밀값, LLM 출력, 계산 결과, 결론과 고정 Model ID를 넣지 않습니다. 필요한 자료는 `전표 원장`, `계획 대비 실적`, `제품·고객 기준정보` 같은 semantic input role로 선언하고 Mission 생성 시 권한이 확인된 exact file·query version에 binding합니다.

#### 6.5.1 Mission별 적응

같은 Pattern을 사용해도 Workflow는 다음 입력에 따라 달라져야 합니다.

- 사용자가 표현한 목적과 완료 기준
- 비교 기간, 조직·제품 범위와 중요도 기준
- 실제로 확보된 자료, schema, 품질과 누락
- 허용된 Tool·Provider·권한과 외부 반출 정책
- 예산, 마감, 원하는 검증 수준과 보고 대상
- 실행 중 발견된 이상치, 반대 근거와 미설명 잔차

Lumina는 Pattern의 필수 뼈대를 지키면서 조건부 Node를 선택하고, adaptive slot을 새 Node나 Sub-workflow로 구체화하며, 불필요한 단계를 제거합니다. 서로 다른 Pattern의 일부를 조합할 수도 있지만 동일한 input·output contract와 합류 조건을 만족해야 합니다. Pattern과 달라진 이유는 Workflow revision diff에 `질문 답변`, `자료 상태`, `조직 정책`, `AI 제안`, `사용자 편집` 중 하나로 기록합니다.

질문은 Template의 빈칸을 모두 채우기 위해 묻지 않습니다. 현재 후보 Workflow를 실제로 바꾸는 정보 가치가 큰 질문만 먼저 묻고, 답을 몰라도 안전한 기본 경로로 진행할 수 있으면 가정과 영향을 기록한 뒤 진행합니다.

#### 6.5.2 재사용 단위와 scope

초기 재사용 단위는 다음 세 가지로 제한합니다.

| 단위 | 예시 | 용도 |
|---|---|---|
| 전체 Pattern | 손익 변동 원인 분석 | 새 Mission의 전체 뼈대 |
| Sub-workflow Pattern | 데이터 품질 검사, 반대 근거 검증 | 여러 Pattern에서 공유하는 검증·분석 구간 |
| Node Recipe | Python 분해 계산, 경영진 요약 | 입출력 계약이 명확한 단일 작업 방식 |

scope는 `builtin`, `organization`, `project`, `personal`을 지원할 수 있으나 초기 구현은 검토된 builtin과 Project scope부터 시작합니다. 공유 범위 승격은 원본 Mission의 민감 자료를 제거한 구조만 대상으로 하며 권한 있는 사용자의 명시적 검토와 publish가 필요합니다. Pattern은 immutable version을 가지며 기존 Mission은 시작 시 사용한 Pattern version과 생성된 Workflow revision을 계속 참조합니다.

#### 6.5.3 실행에서 패턴으로의 학습

완료된 Mission 하나를 자동으로 표준 Pattern으로 덮어쓰지 않습니다. Lumina는 다음 신호를 근거로 `Pattern 개선 후보`만 제안합니다.

- 여러 Mission에서 반복해 추가·삭제·재배치된 Node
- 자주 발생한 사용자 질문과 실제 분기 결과
- 검증 실패, 재실행, stale 전파와 수동 수정
- 비용·소요시간·완료율·근거 충족도
- 사용자가 최종적으로 채택하거나 제외한 분석 경로

후보에는 기존 version과의 diff, 기대 효과, 회귀 위험, 영향을 받을 Mission 유형을 표시합니다. 승인된 후보만 새 Pattern version으로 publish하며 이전 version과 그 version으로 생성된 Mission의 기록은 유지합니다. LLM 출력 내용 자체를 암묵적으로 학습하거나 다른 Project로 전파하지 않습니다.

## 7. 질문·의사결정·Claim·품질 Gate

### 7.1 질문과 의사결정 기록

질문과 답변은 채팅 문자열로만 남기지 않고 Decision 객체와 event로 저장합니다.

```text
질문: 비교 기준을 무엇으로 할 것인가
선택지: 전년 동기 / 사업계획 / 전월 / 복수 기준
AI 권고: 전년 동기와 사업계획 병행
사용자 결정: 전년 동기와 사업계획 병행
적용 Workflow: revision 7
영향 Node: N003, N004, N005, N020
결정 시각과 결정자
```

결정이 바뀌면 기존 기록을 덮어쓰지 않습니다. 새 revision을 만들고 영향받은 Node와 결과 파일을 `review_required`로 표시합니다. 질문은 가능한 한 시작 시 묶어 제시하고, 실행 중에는 결과를 크게 바꾸는 경계에서만 요청합니다.

### 7.2 Claim Ledger와 Evidence

최종 보고서의 핵심 결론을 Markdown 문장 안에만 숨기지 않고 구조화된 `Claim`으로 관리합니다.

```text
Claim: 원재료 가격 상승이 영업원가 증가의 41%를 설명
Level: key_finding
Source Node: N003
Materiality: high
Status: verified
Support:
- N003_원재료비_분석_결과.csv 18~24행
- 원재료 구매실적 exact version 3, 2026-01~06
Contradiction:
- 장기계약 단가 고정 품목 2건
Validation:
- 가격·물량·환율 분해 합계 일치
Report inclusion: executive_summary
```

Claim level은 `observation`, `supporting_finding`, `key_finding`, `recommendation`을 사용하고 status는 다음과 같이 관리합니다.

```text
proposed
→ supported
→ verified | disputed | unresolved | rejected
```

Evidence는 Claim을 `support`, `contradict`, `context` 중 하나의 stance로 연결합니다. 동일 Evidence가 여러 Claim을 지원할 수 있고 하나의 Claim이 계산 결과·원본 파일·외부 출처를 함께 참조할 수 있습니다. Confidence는 Model의 자기확신만으로 결정하지 않고 자료 coverage, 계산 검증, 출처 신뢰도, 반대 근거와 reviewer 결과로 산정합니다.

보고서 문장에는 관련 Claim ID를 내부적으로 연결하고 사용자가 문장이나 표의 근거를 열면 Node 출력, 계산 파일과 원본 locator까지 역추적할 수 있어야 합니다.

### 7.3 미해결·상충 항목

분석이 설명하지 못한 사항도 결과물입니다. 다음 항목을 `Open Issue Register`로 보존합니다.

- 미설명 수치·잔차와 전체 금액 대비 비율
- 자료 부족으로 검증하지 못한 가설
- 서로 충돌하는 계산·Evidence·부서 설명
- 낮은 신뢰도의 잠정 결론
- 범위에서 의도적으로 제외한 항목과 이유
- 추가로 필요한 파일·질문·담당자 확인

AI는 Open Issue를 억지로 하나의 결론에 합치지 않습니다. 최종 보고서에서 `확정`, `잠정`, `미해결`, `제외`를 구분하고 Completion Contract의 허용 한도를 넘으면 Mission을 `satisfied`로 완료하지 않습니다.

### 7.4 최종 Quality Gate

최종 합성·보고서 확정 전에 독립 Quality Gate를 수행합니다. 가능한 검사는 Python·SQL·schema rule로 결정적으로 실행하고 의미 검토가 필요한 항목만 검증 Node나 사용자 reviewer를 사용합니다.

| Gate | 검사 내용 |
|---|---|
| `data_quality` | 입력 version, schema, 결측·중복, 기간·단위·통화 |
| `numeric_reconciliation` | 합계·부분합, 분해 잔차, 중복 영향, 허용 오차 |
| `evidence_coverage` | 핵심 Claim의 support, exact locator와 source version |
| `contradiction_review` | 주요 반대 근거의 검토·해소 또는 unresolved 표시 |
| `stale_check` | stale·review_required·validation_failed 결과 포함 여부 |
| `completion_contract` | 필수 질문·산출물·coverage·잔차·예산·승인 조건 |
| `report_integrity` | 보고서 수치와 확정 Claim·CSV의 일치, 잠정·예외 표시 |

Gate 실패 시 최종 보고서를 확정하지 않고 영향 Node만 재실행하거나 Open Issue로 전환하거나 사용자에게 명시적 waiver를 요청합니다. 검증 Node와 보고서 Node가 같은 LLM 응답을 공유해 자기 결과를 형식적으로 승인하지 않도록 실행·Prompt 역할을 분리합니다. 모든 Gate 결과와 waiver는 immutable record와 event로 남깁니다.

## 8. 단위별 LLM 출력의 Markdown 저장

### 8.1 저장 의미

각 Workflow Node에서 사용자에게 제시한 LLM의 완료 출력을 그대로 Markdown 파일로 저장합니다. 다음 Node를 위한 별도 인계 문서를 다시 생성하거나 같은 내용을 요약하기 위해 추가 모델 호출을 하지 않습니다.

```text
LLM 출력 생성
→ 사용자 화면에 표시
→ 동일한 완료 출력 bytes를 Backend가 Markdown으로 저장
→ Node Execution과 파일 version 연결
```

이미 생성된 출력 문자열을 저장하므로 저장 자체에는 추가 출력 Token이 들지 않습니다. 제목, Node ID, 생성 시각, Run ID, Model, 비용과 입력 reference 같은 metadata는 Backend가 기록하며 LLM이 본문으로 다시 작성하지 않습니다.

### 8.2 파일 배치와 이름

물리 폴더는 기본적으로 Mission 단위까지만 자동 생성합니다. Node마다 `output.md` 폴더를 만들지 않고 Mission 폴더 아래에 고유한 이름으로 평평하게 저장합니다.

```text
심층분석/
└─ 전사 영업원가 변동 원인 분석/
   ├─ N001_목표범위_확정.md
   ├─ N002_데이터품질_검사.md
   ├─ N003_원재료비_분석.md
   ├─ N003_원재료비_분석_계산.py
   ├─ N003_원재료비_분석_결과.csv
   ├─ N003_원재료비_분석_정합성검증.csv
   ├─ N004_제품믹스_분석.md
   ├─ N004_제품믹스_분석_계산.py
   ├─ N004_제품믹스_분석_결과.csv
   ├─ N005_생산수율_분석.md
   ├─ N020_교차검증.md
   ├─ N030_핵심원인_합성.md
   └─ N040_최종보고서.md
```

기본 파일명 규칙은 다음과 같습니다.

```text
{Node ID}_{작업명}.md
{Node ID}_{작업명}_{용도}.{확장자}
```

- Node ID는 Workflow 안에서 안정적이고 정렬 가능한 ID를 사용합니다.
- 작업명과 용도는 사용자가 이해할 수 있는 짧은 이름으로 정규화합니다.
- 파일명은 Windows와 Linux 모두에서 안전해야 하며 예약문자, trailing dot·space와 과도한 길이를 제거합니다.
- 동일 논리 파일의 재실행 결과를 새 `v2`, `v3` 파일로 목록에 늘어놓지 않고 immutable version history로 관리합니다.
- 전체 version download를 명시적으로 선택한 경우에만 export 파일명에 version suffix를 붙입니다.

파일이 많아지면 실제 폴더를 늘리는 대신 UI에서 `Node별 묶기`, 확장자 filter, 상태 filter와 검색을 제공합니다. 이 묶기는 가상 group이며 물리 경로를 바꾸지 않습니다.

### 8.3 부분 출력과 재실행

정상 완료된 LLM 출력만 현재 Node의 주 Markdown version으로 승격합니다. 중단된 partial output도 복구와 감사 목적으로 저장하되 UI에서 `생성 중 중단됨`을 명확히 표시하고 확정 결과처럼 사용하지 않습니다.

재실행은 이전 결과를 덮어쓰지 않고 새 immutable version과 Node Execution을 만듭니다. UI의 기본 파일 목록에는 latest valid version만 보이고 파일 상세에서 과거 실행과 partial version을 확인합니다.

## 9. 수치 계산과 파일

### 9.1 역할 분리

```text
LLM: 분석 목적·계산 방법·검증 기준 설계
→ Python: 정제·집계·통계·수치 계산 수행
→ CSV: 입력·중간·최종 수치 결과 저장
→ 검증: 합계·오차·단위·결측·중복 검사
→ LLM: 검증된 결과 해석
→ Markdown: LLM의 최종 해석 출력 저장
```

LLM은 중요한 합계, 증감률, 가격·물량·믹스 분해와 통계값을 문맥만으로 직접 계산하지 않습니다. 계산은 sandbox 안의 Python, SQL 또는 검증된 계산 Tool로 수행합니다.

### 9.2 계산 검증

계산 Node는 최소한 다음을 검사합니다.

- 필수 column과 schema
- 숫자·날짜 변환 실패
- 결측치, 중복과 제외 행
- 원·천원·백만원, kg·톤 등 단위
- 통화와 환율 기준
- 세전·세후, 연결·별도 같은 회계 범위
- 원본 합계와 기준 수치 대조
- 분해 결과 합계와 전체 변동액의 차이
- 0 나누기, overflow와 극단값
- 허용 오차와 완료 조건

```text
전체 변동액        5,420억 원
분해 결과 합계     5,417억 원
미설명 차이            3억 원
차이율              0.055%
허용 기준             0.1%
검증 결과             통과
```

검증에 실패한 수치는 최종 확정 결론으로 승격하지 않습니다. LLM 출력에는 실패 원인, 잠정 결과와 필요한 후속 작업을 구분해 표시합니다.

### 9.3 입력·코드·결과 lineage

각 계산 결과는 다음 관계를 설명할 수 있어야 합니다.

```text
입력 파일 exact version
+ 계산 코드 exact version
+ 실행 parameter와 환경 snapshot
+ 사용자 결정 revision
= 결과 CSV version과 검증 결과
```

## 10. 파일 화면과 자료 연결

### 10.1 같은 수준의 저장 영역

`파일` 화면의 탐색기에는 `프로젝트 파일`과 `심층분석`을 같은 수준의 root로 표시합니다.

```text
파일 저장소
├─ 프로젝트 파일
└─ 심층분석
   └─ 전사 영업원가 변동 원인 분석
      ├─ N001_목표범위_확정.md
      ├─ N003_원재료비_분석.md
      ├─ N003_원재료비_분석_계산.py
      └─ N003_원재료비_분석_결과.csv
```

- `프로젝트 파일`: 사용자가 직접 업로드·생성·이동·삭제하는 일반 Project 자료
- `심층분석`: Mission 실행이 생성한 LLM 출력, 계산 코드, 결과 데이터와 보고서

`심층분석`은 제품 내비게이션에서는 독립 기능이고, `파일 → 심층분석`은 결과 파일을 탐색하는 또 다른 진입점입니다. 두 화면은 같은 Mission, Node, File과 version ID를 사용합니다.

### 10.2 원본 참조와 생성 파일

Project 파일을 Mission에서 사용할 때 원본을 복사하지 않습니다. Mission 자료 화면에는 stable reference와 원본 위치를 표시하고 클릭 시 `프로젝트 파일`의 exact version으로 이동합니다.

Mission이 생성한 MD·CSV·PY는 심층분석의 관리 Storage에 실제 파일로 저장합니다. 사용자가 파일 상세에서 `관련 Node 보기`를 누르면 Workflow의 Node로, Node의 출력 파일을 누르면 파일 상세로 이동합니다.

Project 파일의 사용자 관리 경계와 Mission 생성 파일의 시스템 관리 경계를 Backend에서 분리합니다. Mission 생성 파일을 일반 upload 파일처럼 임의 덮어쓰기하거나 다른 Mission으로 이동해 lineage를 끊지 않습니다. 수정은 새 version 또는 명시적인 사본 만들기로 처리합니다.

## 11. Context 관리와 Token 최적화

Mission 전체 대화와 모든 파일을 매 model Turn에 넣지 않습니다. Workflow 연결, 현재 Node 목적, 사용자의 결정과 Evidence relevance를 이용해 Context를 조립합니다.

```text
Mission 목표와 완료 기준
+ 현재 Node 계약
+ 직접 연결된 선행 Node의 MD 출력
+ 관련 사용자 결정
+ 필요한 CSV 통계·일부 행
+ 검증 결과와 반대 근거
+ 현재 Node의 Context·비용 예산
```

원본 Message, Tool Result와 파일은 저장소에 유지합니다. 모델은 우선 Node 출력의 필요한 section과 짧은 preview를 받고, 필요할 때 권한이 제한된 부분 읽기로 원문을 추가 조회합니다.

Token 낭비를 줄이기 위해 다음 원칙을 적용합니다.

- LLM 출력을 MD로 저장하기 위한 별도 재작성 호출을 하지 않습니다.
- 동일 본문, 파일과 Tool 결과는 ID·digest로 재참조하고 중복 주입하지 않습니다.
- Tool의 대용량 원문은 저장소에 보존하고 Context에는 preview와 reference만 넣습니다.
- 상위 합성 Node는 필요한 하위 MD부터 읽고 모든 원본을 선제적으로 넣지 않습니다.
- 완료된 branch는 필요할 때 기존 Context compaction 계약으로 압축하되 목표, 결정, 검증 결과, citation과 미완료 Node를 보존합니다.
- 안정적인 system prompt, Tool schema와 Mission prefix를 유지해 Provider prompt cache를 활용합니다.

### 11.1 Prefix Cache를 고려한 Prompt 배치

심층분석은 같은 Mission에서 여러 Node와 model Turn이 공통 지침·목표·Tool 계약을 반복하므로 Provider의 prefix cache 할인 효과가 큽니다. Prompt를 단순히 짧게 만드는 것뿐 아니라 동일한 앞부분이 byte 수준에서 오래 유지되도록 다음 순서로 조립합니다.

```text
stable core prefix
├─ system security와 제품 지침
├─ Organization·Agent·Project 지침의 canonical serialization
└─ Provider·Model별 안정적인 Tool profile

stable mission prefix
├─ Mission 목표·완료 기준 revision
├─ 적용한 Pattern version 또는 제로베이스 설계 계약
├─ 공통 용어·단위·데이터 사전
└─ Mission 예산·권한·검증 policy

stable node-profile prefix
├─ 분석 / 조사 / 계산해석 / 검증 / 합성 중 하나의 역할 계약
└─ typed output schema와 공통 품질 기준

volatile tail
├─ 현재 Node 목적과 직접 dependency
├─ 관련 Decision·Evidence·CSV 일부
├─ 최신 Tool Result와 사용자 입력
└─ 현재 시각·진행률·남은 예산 같은 변동 상태
```

같은 Mission의 Node마다 system prompt, Tool schema, JSON key 순서, whitespace와 공통 지침 표현을 다시 만들지 않습니다. timestamp, Run·request ID, Node 상태, 누적 비용, 동적 memory recall과 검색 결과는 stable prefix에 넣지 않고 뒤쪽 tail에 둡니다. Mission 목표나 정책이 바뀌면 기존 prefix를 조용히 변형하지 않고 새 `mission_context_revision`과 prefix hash를 만듭니다.

Tool을 줄이면 uncached Token은 감소하지만 호출마다 Tool schema 구성이 달라져 cache hit가 깨질 수 있습니다. 따라서 모든 Tool을 항상 넣지도, Node마다 임의 조합하지도 않고 실제 사용이 반복되는 소수의 안정적인 `Tool Profile`을 둡니다.

```text
research profile     검색·문서 읽기·근거 저장
analysis profile     파일 읽기·Python·SQL·결과 저장
synthesis profile    확정 결과 읽기·인용·보고서 저장
```

Profile 내부 Tool 순서와 schema version은 고정합니다. 드물게 쓰는 고비용·고위험 Tool은 prefix 밖에서 추가 승인 후 별도 profile이나 새 Context lineage로 전환하고 cache 무효화 비용을 기록합니다.

### 11.2 할인까지 반영한 Cache 경제성 판단

Prefix cache는 Token 수를 줄이지 않아도 cached input 단가 할인으로 비용을 낮출 수 있지만, Provider에 따라 cache write·read 단가, 최소 cacheable 길이, TTL과 long-context 가격 구간이 다릅니다. 설계에 고정 할인율을 넣지 않고 실행 시점의 Provider·Model capability와 가격표 version으로 계산합니다.

동일 prefix를 앞으로 `n`회 사용할 것으로 예상할 때 다음 두 비용을 비교합니다.

```text
cache 미사용 비용 = n × 일반 input 비용
cache 사용 비용   = 최초 cache write 비용 + (n - 1) × cache read 비용
```

실제로는 cache 생성이 별도 과금되지 않는 Provider, 명시적 cache write가 필요한 Provider와 자동 cache만 제공하는 Provider를 adapter가 구분합니다. 더 큰 안정 prefix가 long-context 할증, latency 또는 불필요한 자료 노출을 일으킨다면 cache 할인만을 위해 유지하지 않습니다. `짧은 uncached prompt`와 `조금 크지만 반복 할인되는 cached prefix`의 예상 총비용을 비교해 더 저렴한 쪽을 선택합니다.

- 한두 번만 호출할 Node를 위해 별도 cache warming 호출을 만들지 않습니다.
- 첫 번째 실제 계획·분석 호출이 prefix를 자연스럽게 생성하고, 동일 prefix를 쓰는 병렬 fan-out은 Provider의 cache 가시성 특성을 고려해 시작합니다.
- Pattern을 쓰지 않는 제로베이스 Mission도 Mission 목표·지침·Tool Profile이 안정되면 같은 방식으로 cache를 활용합니다.
- Pattern version, Mission context revision, Tool Profile과 Node Profile이 같아도 사용자·Organization·Project 권한 scope가 다르면 cache 재사용 대상으로 취급하지 않습니다.
- Context compaction 뒤에는 새 prefix lineage를 한 번 만들고 매 Turn마다 다른 요약으로 재작성하지 않습니다.

Prompt prefix cache는 `같은 입력에 대한 완료 결과 재사용`과 다릅니다. 전자는 Provider가 입력 처리 비용을 할인하더라도 model 호출과 새 출력 비용은 발생합니다. 후자는 권한·입력·계약 fingerprint가 완전히 같을 때 Node Execution 자체를 생략합니다. 비용 최적화 우선순위는 `결과 재사용 → 불필요한 호출 제거 → Context 축소 → prefix cache 할인 → Model routing`으로 둡니다.

### 11.3 Cache 계측과 비용 예측

각 model Turn은 Core usage 계약의 다음 값을 Mission과 Node Execution에 연결합니다.

- uncached input, cached input, cache write와 output Token
- Provider raw usage와 가격표 version
- stable prefix hash, Mission context revision과 Tool·Node Profile version
- cache hit ratio와 `system_prompt`, `instructions`, `tool_schema`, `mission_revision`, `compaction`, `provider` 무효화 사유
- cache가 없었을 때의 추정 input 비용, 실제 input 비용과 추정 할인액

예상 완료 비용은 모든 미래 입력을 일반 단가로 계산하지 않습니다. 동일 prefix를 사용할 남은 Node 수, 최근 cache hit ratio, TTL 안의 예상 실행 시간과 Provider별 read·write 단가를 반영해 `cache 예상 적용`과 `cache 미적용 상한`을 함께 계산합니다. cache hit은 보장하지 않으므로 예산 hard limit 판정에는 보수적인 상한을 사용합니다.

### 11.4 연구 근거를 반영한 Context·Model·Workflow 최적화 Gate

긴 Context, prompt 압축, Model routing과 Workflow 자동 최적화는 항상 비용을 줄이거나 품질을 높이지 않습니다. 각 기법을 다음 Gate를 통과한 경우에만 적용합니다.

#### Context Pack과 압축

Node 입력은 원본을 하나의 긴 prompt로 합치지 않고 의미와 보존 수준을 가진 `Context Pack Item`으로 조립합니다.

```text
exact        사용자 결정, 공식 수치, 계산식, schema, 직접 인용과 핵심 Claim
extractive   원문에서 선택한 관련 section·행·문단과 stable locator
reference    필요할 때 Tool로 읽는 원본 version reference
compressed   반복·장문의 저위험 설명을 줄인 파생 Context
```

`exact`와 원본 Evidence는 압축으로 대체하지 않습니다. `compressed` Item은 원본 reference, 압축기·Model version, 압축률, 생성 비용과 검증 결과를 가지며 Node의 권위 있는 산출물이나 감사 원본이 되지 않습니다. 우선순위는 `관련 자료 선택 → extractive 축소 → deterministic 구조화 → 필요한 경우에만 model 기반 압축`입니다.

압축은 다음 조건을 모두 만족할 때만 수행합니다.

- 압축 호출·전처리 비용보다 이후 반복 입력에서 예상되는 절감액이 큼
- 같은 Context를 여러 후속 Node가 사용할 가능성이 높음
- 숫자·결정·인용·부정 표현과 locator 보존 검사를 통과함
- 압축 결과가 prefix cache lineage를 매 Turn 깨지 않도록 immutable version으로 고정됨
- 품질 회귀가 생기면 원본·extractive Context로 fallback 가능함

#### Model routing과 cascade

초기에는 학습된 범용 Router를 바로 도입하지 않고 Node Profile·위험도·자료 민감도·필요 capability에 따른 정책 기반 routing을 사용합니다. 저비용 Model 결과가 schema, confidence, 계산·근거 coverage Gate를 통과하지 못할 때만 상위 Model로 escalation합니다.

학습형 Router는 충분한 실제 Mission 평가 자료와 강·약 Model의 쌍별 품질 label이 쌓인 뒤 offline evaluation을 통과한 scope에만 사용합니다. 학습 분포와 다른 업무, 고위험 결론, 최종 합성·보고서와 Router confidence가 낮은 요청은 강한 Model 또는 사용자 정책으로 fallback합니다. Router 자체의 Token·latency·비용과 오분류로 발생한 재실행 비용도 절감액에서 차감합니다.

#### Workflow compile과 trajectory 축소

각 Tool 호출 전에 LLM이 전체 과거를 다시 읽는 ReAct식 순차 loop를 기본 실행 형태로 삼지 않습니다. 승인된 Workflow revision을 dependency graph로 compile하고, 독립적인 읽기·계산 Tool은 한 번의 계획에서 batch 또는 병렬 dispatch합니다. 다만 병렬화는 지연시간을 줄일 뿐 호출 수와 Token을 자동으로 줄이지 않으므로 동일 자료·동일 Tool의 중복 호출을 먼저 병합합니다.

Node의 typed output과 Generated File을 application-level semantic variable처럼 취급하여 후속 Node가 문자열 전체를 다시 parsing하지 않고 stable ID·schema·lineage로 연결합니다. Scheduler는 개별 model call latency가 아니라 Mission의 최종 완료 비용·기한·품질 Gate를 최적화합니다.

실행 trajectory에서 중복, 만료, 후속 Node와 무관한 Tool 원문은 Context에서 제거할 수 있지만 저장 원본과 event는 유지합니다. 목표, 최신 Decision, 미완료 dependency, Claim·Evidence·계산 lineage, 오류와 side effect Tool pair는 제거하지 않습니다. 축소 전후 Context manifest와 품질 결과를 저장해 fallback과 회귀 평가가 가능해야 합니다.

#### Workflow 자동 탐색

AFlow처럼 Workflow 구조를 반복 탐색하는 방식은 유용할 수 있지만 탐색 자체가 많은 LLM 호출을 요구합니다. 따라서 실제 Mission 실행 중 MCTS나 대량 후보 Workflow를 기본 생성하지 않습니다. 완료 Mission에서 수집한 품질·비용·재실행 자료를 사용해 background/offline으로 소수의 Pattern 개선 후보를 평가하고, 정해진 탐색 예산과 회귀 suite를 통과한 후보만 사용자에게 제안합니다.

## 12. 비용과 예산 UI

### 12.1 기본 표시

Workflow Canvas와 Node 카드에는 Node별 비용을 기본 표시하지 않습니다. Mission Header에는 누적 비용과 예산 대비 사용률을 항상 조용하게 표시하여 장기 작업의 비용을 인지할 수 있게 합니다.

```text
누적 비용 184,300원 · 예산 300,000원 중 61%
```

예산을 설정하지 않았으면 누적 비용만 표시하고 알 수 없는 비용을 0원으로 표시하지 않습니다. Codex OAuth 등 실제 청구액을 알 수 없는 Provider는 기존 정책에 따라 `예상 비용`임을 명확히 표시합니다.

### 12.2 상세 보기

사용자가 누적 비용을 누르면 비용 화면이나 Drawer에서 다음 breakdown을 확인합니다.

- 단계·Node·Model·Provider·날짜별 비용
- input, cache write, cached input, uncached input과 output Token
- cache 미적용 추정 비용, 실제 비용, 할인 추정액과 cache hit ratio
- Python·Tool·Connector의 별도 계측 비용
- 재실행과 실패로 추가된 비용
- 최종 결론에 사용된 Node와 보관된 branch의 비용
- 현재 추세를 반영한 예상 완료 비용

Node별 비용은 다음 경우에만 노출합니다.

- 사용자가 `Node별 비용 표시`를 켠 경우
- Node Inspector 또는 비용 상세를 연 경우
- 예상 비용이 정책 threshold를 넘는 경우
- 재실행이나 신규 AI 제안으로 추가 비용이 발생하는 경우

예산 50%, 80%, 100% 같은 threshold는 조직 정책으로 설정합니다. 80% 도달이나 초과 예상 시 경고와 예상 완료 비용을 표시하고, hard limit을 넘는 고비용 Node는 실행 전에 확인을 요구합니다.

## 13. 실행, 복구와 동시성

- 실행 가능한 Node만 dependency와 사용자·서버 한도 안에서 병렬 실행합니다.
- 실행 전 Workflow revision을 dependency graph로 compile하고 동일 입력·동일 Tool의 중복 작업을 병합한 뒤 독립 작업만 batch·병렬 dispatch합니다.
- 하나의 Node Execution은 입력, Workflow revision, Provider, Model, Tool, 파일과 결정 reference를 snapshot으로 고정합니다.
- 브라우저를 닫거나 다른 화면으로 이동해도 Backend Worker가 계속 실행합니다.
- 재접속 시 Mission snapshot과 sequence event replay로 Canvas 상태, 실행 Drawer, partial output, 질문, 비용과 파일을 복원합니다.
- 완료 여부를 알 수 없는 외부 부작용 Tool은 자동 재실행하지 않습니다.
- Python 계산처럼 입력과 코드가 고정되고 side effect가 없는 작업은 검증된 checkpoint에서 안전하게 재시도할 수 있습니다.
- Node 재실행은 완료된 다른 Node 결과를 삭제하지 않으며 새 version을 만듭니다.
- 다른 Mission과 서로 다른 Session의 실행은 사용자·서버 한도 안에서 병렬 실행할 수 있습니다.

## 14. 권한, 보안과 감사

- Backend는 Mission, Project, Organization과 사용자 권한을 모든 파일·Node·Run 요청에서 다시 검증합니다.
- Project 파일 reference는 선택 시점의 exact version과 digest를 고정합니다.
- Python과 Tool 실행은 Mission 전용 sandbox 또는 승인된 Worker 경계에서 수행하며 Project root 밖 경로를 사용할 수 없습니다.
- Secret, 인증서 원문, credential, 개인정보와 허용되지 않은 원본 행을 Markdown, 코드, CSV, 로그와 event에 남기지 않습니다.
- 외부 검색·Connector·다운로드·공유는 기존 egress, TLS, 승인과 감사 정책을 따릅니다.
- 누가 Workflow를 수정하고 Node를 실행·재실행·취소했는지, 어떤 질문에 답하고 결정을 바꿨는지 기록합니다.
- 보고서 문장과 핵심 결론에서 관련 Node, LLM 출력, 계산 결과와 Evidence로 이동할 수 있어야 합니다.

## 15. 다운로드와 내보내기

사용자는 다음 범위를 선택해 다운로드할 수 있습니다.

- 선택 파일
- 최신 Mission 생성 파일 전체
- 최종 보고서와 근거 파일
- 과거 version을 포함한 전체 감사용 내보내기

기본 Mission download는 Mission 폴더의 최신 유효 MD·CSV·PY를 원래의 평면 파일명으로 묶습니다. Project 원본 파일은 기본 포함하지 않고 stable reference 목록만 제공하며, 사용자가 권한과 반출 범위를 확인하고 `원본 자료 포함`을 선택한 경우에만 추가합니다.

민감 자료, 외부 반출 금지 자료와 다른 사용자 소유 자료는 download 전에 다시 권한을 검사합니다. download 실행과 포함·제외 범위를 감사 기록에 남깁니다.

## 16. 예시 Workflow

```text
Mission: 전사 영업원가 변동 원인 분석

N001 목표·범위 확정
├─ N002 데이터 품질 검사
├─ N003 원재료비 분석
│  ├─ Python 가격·물량·환율 효과 계산
│  └─ 합계 정합성 검증
├─ N004 제품·고객 믹스 분석
├─ N005 생산·수율 분석
└─ N006 물류·재고평가 분석
       ↓
N020 교차 검증과 반대 근거 확인
       ↓
N030 핵심 원인 합성
       ↓
N040 경영진 보고서
```

각 분석 Node는 자신의 LLM 출력 Markdown을 만들고, 계산이 있는 Node는 같은 접두어의 Python과 CSV를 함께 생성합니다. `N030`은 선행 Node의 확정 MD와 검증 결과를 선택해 읽고, `N040`은 검증된 합성 결과로 최종 보고서를 작성합니다.

## 17. 유사 오픈소스에서 선택적으로 배울 점

2026-07-18 기준 공개 GitHub 프로젝트를 비교하면 Lumina의 전체 제품 개념과 동일한 단일 솔루션은 확인하지 못했습니다. 각 프로젝트는 Canvas, durable execution, 장기 조사, 파일 기반 기억, lineage 또는 비용 추적 중 일부에 강점이 있습니다. 따라서 외부 프로젝트의 제품 모델을 복제하지 않고 검증된 부분 설계만 Lumina의 Mission 계약 안으로 가져옵니다.

| 프로젝트 | 가져올 점 | 그대로 가져오지 않을 점 | Lumina 적용 위치 |
|---|---|---|---|
| [Dify](https://github.com/langgenius/dify) | 시각 Workflow, Node 실행 event, 부분 실행·재개, Human Input | 개발자 변수 중심 설정과 고정 app-flow 편향 | Canvas 실행 상태, 질문·승인 Node, revision 실행 |
| [Flowise Agentflow](https://github.com/FlowiseAI/Flowise) | 쉬운 drag·connect, branch·loop·parallel, Agent·Tool·LLM 역할 분리, 실행 log | business 사용자가 기술 port와 state를 직접 다루는 UX | Node palette, 연결 제약, 실행 Drawer |
| [Langflow](https://github.com/langflow-ai/langflow) | Python custom component, 단계별 test, typed input·output | 개발자용 component builder를 제품 중심에 두는 방식 | Python Node, Node 단위 시험, Pattern 계약 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | checkpoint, durable execution, interrupt·resume, subgraph, memory | 별도 orchestration runtime을 Core와 중복 도입 | Lumina Run·Queue·replay 위의 실행 의미와 idempotency 기준 |
| [Open Deep Research](https://github.com/langchain-ai/open_deep_research) | 범위 설정→병렬 조사→압축→최종 보고, 단계별 model 역할, 비용 평가 | web 조사에 고정된 pipeline과 반복 요약 | adaptive research 구간, 단계별 Context 전략 |
| [DeerFlow](https://github.com/bytedance/deer-flow) | filesystem을 외부 기억으로 사용, sandbox, subagent, 장기 실행 inspect | 불투명한 자율 실행과 제한 없는 subagent 확장 | MD·CSV·PY 기록, 안전한 계산, branch 예산 |
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | planner·executor·publisher 분리, breadth·depth 제어, 병렬 조사 | 최종 보고서만 남기는 흐름과 branch 폭발 | 질문 분해, 탐색 예산, 합성·보고 Node 분리 |
| [Nexus Agents](https://github.com/trilogy-group/nexus-agents) | living document, 지속 workflow 생명주기, source provenance, MD·CSV 산출물 | README 수준 주장만으로 visual editor나 운영 성숙도를 전제 | Mission 기록, 파일 provenance, Pattern 개선 후보 |
| [Dagster](https://github.com/dagster-io/dagster) | asset materialization, metadata, lineage, stale·freshness, 선택 재계산 | 데이터 엔지니어링 용어와 정적 DAG를 사용자에게 노출 | 생성 파일 lineage, stale 전파, 선택 재실행 |
| [Langfuse](https://github.com/langfuse/langfuse) | trace·span, token·cost·model·prompt version, evaluation | 개발자 observability 화면과 trace를 업무 상태의 원본으로 사용 | Node Execution 계측, 비용 breakdown, 품질 평가 |

### 17.1 Lumina식 조합

```text
Workflow UX              Dify + Flowise + Langflow에서 검증된 상호작용
Durable execution        LangGraph 의미론, Lumina Core Run·Queue·Replay로 구현
Dynamic investigation    Open Deep Research + DeerFlow + GPT Researcher의 탐색 구조
Reusable planning        Pattern + 조건부 branch + adaptive slot + version 승격
Files and lineage        Dagster + Nexus Agents의 asset·provenance 관점
Cost and trace           Langfuse식 계층 계측, Lumina의 Mission 업무 화면으로 투영
```

Lumina의 차별점은 Workflow Builder 자체가 아닙니다. 사용자가 큰 업무 목적을 말하면 새로 설계하거나 필요할 때만 재사용 Pattern을 활용해 상황별 Workflow를 계획하고, 장기간 실행하면서 질문·결정·근거·계산·파일·비용을 모두 보존한 뒤 감사 가능한 결론으로 수렴시키는 `Mission System`입니다.

### 17.2 도입 원칙

1. 외부 실행 engine을 추가하기 전에 Lumina Core의 Run·Queue·event replay로 필요한 durable semantics를 구현할 수 있는지 먼저 확인합니다.
2. Canvas의 기술 표현보다 업무 목적, 근거, 산출물, 결정과 검증 상태를 우선합니다.
3. Pattern은 고정 pipeline이 아니라 Mission별 계획을 돕는 prior이며 AI가 이유를 남기고 변경할 수 있어야 합니다.
4. 자동 확장과 subagent는 breadth·depth·비용·시간 한계 안에서만 수행하고 중요한 확장은 승인받습니다.
5. trace, Markdown과 파일은 서로 대체하지 않습니다. DB event는 실행 원본, trace는 관측, 파일은 사람이 읽고 반출하는 결과물입니다.
6. 중요한 수치는 재현 가능한 code와 검증 결과로 materialize하고 영향받은 후속 결과에 stale를 전파합니다.
7. Pattern 추천·개선은 실제 Mission 기록으로 평가하되 민감한 내용과 Project 경계를 넘어 암묵적으로 학습하지 않습니다.

### 17.3 비용·Context·Workflow 최적화 관련 논문 검토

2026-07-18 기준 다음 논문의 원문·학회 페이지를 검토했습니다. 논문 수치는 각 연구의 Model, hardware, dataset과 비교 기준에서 나온 결과이므로 Lumina의 예상 절감률로 사용하지 않습니다. 특히 자체 추론 server의 latency·throughput 개선과 상용 API의 청구 할인은 구분합니다.

| 논문 | 검토한 핵심 결과 | Lumina 반영 | 그대로 적용하지 않는 이유 |
|---|---|---|---|
| [Prompt Cache: Modular Attention Reuse for Low-Latency Inference](https://proceedings.mlsys.org/paper_files/paper/2024/hash/a66caa1703fe34705a4368c3014c1966-Abstract-Conference.html), MLSys 2024 | 반복 prompt segment의 attention state를 module로 재사용해 긴 prompt의 TTFT를 크게 낮춤 | Core·Mission·Node Profile의 stable prefix와 canonical serialization | 자체 prototype의 latency 결과이며 외부 Provider API의 할인율·TTL을 보장하지 않음 |
| [SGLang: Efficient Execution of Structured Language Model Programs](https://arxiv.org/abs/2312.07104) | RadixAttention으로 tree·multi-turn·few-shot workload의 KV prefix 재사용, structured decoding 최적화 | prefix lineage, branch 공통 prefix, typed output 제약 | Lumina가 제3자 API를 사용할 때 inference runtime과 KV placement를 직접 제어할 수 없음 |
| [Preble: Efficient Distributed Prompt Scheduling for LLM Serving](https://arxiv.org/abs/2407.00023) | 분산 환경에서 prompt 공유와 GPU load balancing을 함께 최적화 | 향후 self-hosted Provider에서 prefix locality를 scheduler hint로 사용 | 초기 Lumina Backend scheduler에 GPU KV cache 책임을 섞지 않음 |
| [CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion](https://arxiv.org/abs/2405.16444) | prefix가 아닌 여러 document chunk의 KV를 선택 재계산으로 결합 | Project file chunk의 stable digest·순서·context manifest 보존 | Provider가 기능을 제공하지 않으면 Application layer에서 흉내 낼 수 없고 잘못된 KV 결합은 품질 위험이 있음 |
| [Parrot: Efficient Serving of LLM-based Applications with Semantic Variable](https://arxiv.org/abs/2405.19888) | request 단위가 아니라 application dataflow와 end-to-end 목표를 노출해 최적화 | Node typed output·File·Evidence를 semantic variable로 연결하고 Mission 완료 비용·기한을 최적화 | Parrot runtime을 별도 도입하지 않고 Lumina Workflow·Run 계약에 개념만 반영 |
| [LLMLingua](https://aclanthology.org/2023.emnlp-main.825/), EMNLP 2023 | budget controller와 token 선택으로 prompt 압축 가능성을 보임 | 반복 장문의 저위험 Context에만 검증된 `compressed` 파생 Item 허용 | 논문 최대 압축률을 일반화할 수 없고 계산·결정·인용 손실은 감사 가능성을 훼손함 |
| [LongLLMLingua](https://aclanthology.org/2024.acl-long.91/), ACL 2024 | query-aware long-context 압축이 일부 QA에서 비용·latency와 성능을 함께 개선 | Node 목적을 기준으로 Evidence를 선택하고 중요한 정보를 명시적으로 재배치 | benchmark별 결과이며 압축 호출 overhead와 다른 업무의 citation fidelity를 별도 검증해야 함 |
| [Lost in the Middle](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00638/119630/Lost-in-the-Middle-How-Language-Models-Use-Long), TACL 2024 | 긴 Context에서 관련 정보 위치에 따라 성능이 저하되고 단순히 더 많은 문서를 넣어도 이득이 포화됨 | Mission 전체 주입 금지, 관련 Evidence 선택, Node 질문과 핵심 입력을 명확한 경계에 배치 | 긴 Context window 지원을 실제 활용 능력으로 간주하지 않음 |
| [FrugalGPT](https://arxiv.org/abs/2305.05176) | prompt adaptation, approximation과 LLM cascade로 비용·품질 trade-off를 탐색 | 저비용 Model 우선 후 품질 Gate 기반 escalation | 논문 최대 절감 수치를 Lumina에 적용하지 않고 업무별 평가·현재 가격표로 재산정 |
| [RouteLLM](https://arxiv.org/abs/2406.18665) | preference data 기반으로 강·약 Model을 routing할 수 있으나 일부 OOD benchmark에서는 random 수준으로 저하 | 초기 policy routing, 이후 scope별 학습 Router와 OOD·low-confidence 강한 Model fallback | 범용 Router를 즉시 신뢰하거나 self-reported confidence만으로 핵심 결론을 약한 Model에 배정하지 않음 |
| [An LLM Compiler for Parallel Function Calling](https://arxiv.org/abs/2312.04511) | dependency를 한 번 계획하고 독립 Tool을 병렬 dispatch하여 ReAct 대비 반복 호출·latency·cost 감소 | Workflow compile, duplicate Tool 병합, dependency-aware batch·parallel 실행 | 무관한 분석 branch를 늘리는 근거로 사용하지 않고 side effect·동적 결과는 안전 경계를 유지 |
| [AFlow: Automating Agentic Workflow Generation](https://openreview.net/forum?id=z5uVAKwmjf), ICLR 2025 | workflow를 search space로 보고 실행 feedback으로 개선하며 작은 Model workflow의 가능성을 보임 | 완료 Mission 자료에 기반한 offline Pattern 개선 후보와 회귀 평가 | Mission마다 online MCTS를 수행하면 탐색 비용·재현성·감사 복잡도가 커짐 |
| [Reducing Cost of LLM Agents with Trajectory Reduction](https://arxiv.org/abs/2509.23586), arXiv preprint | coding-agent 실험에서 중복·만료 trajectory 제거가 입력 Token과 총비용을 낮춤 | Context manifest에서 redundant·expired·irrelevant 항목 제거와 원본 보존 | coding benchmark 결과를 업무 분석에 일반화하지 않고 Claim·Decision·Evidence 보존 회귀 test가 필요 |
| [Value of Information: A Framework for Human-Agent Communication](https://arxiv.org/abs/2601.06407), arXiv preprint | 질문으로 얻는 기대 utility와 사용자 부담을 함께 고려하는 질문 정책 | Workflow를 실제로 바꿀 정보 가치가 큰 질문만 요청하고 질문 비용도 Mission 최적화에 포함 | 고위험 업무의 의무 승인·법적 질문을 utility 계산으로 생략하지 않음 |

#### 17.3.1 논문 검토로 확정한 설계 결정

1. Prefix cache는 `비용 할인 가능성`, KV cache 연구는 `서빙 latency·throughput 가능성`의 근거이며 둘을 같은 절감률로 보고하지 않습니다.
2. Cache hit을 위해 Context를 늘리기 전에 호출 제거, Node 결과 재사용, 관련 Evidence 선택과 deterministic 계산을 먼저 적용합니다.
3. Prompt 압축은 원본을 대체하지 않는 파생 Context이며 숫자·결정·계산식·직접 인용·Evidence locator에는 기본 적용하지 않습니다.
4. Model routing은 policy 기반으로 시작하고 실제 Mission 평가 자료가 쌓인 뒤 scope별로 학습하며 OOD·고위험·낮은 confidence는 강한 Model로 fallback합니다.
5. Workflow는 한 번 compile해 dependency와 semantic output을 활용하고 Tool 호출마다 전체 trajectory를 다시 reasoning하지 않습니다.
6. 자동 Workflow 탐색은 online 기본 동작이 아니라 예산이 제한된 offline Pattern 개선 과정입니다.
7. 비용 최적화는 Token·달러뿐 아니라 품질 회귀, 재실행, 질문 부담, TTFT와 Mission 완료시간을 함께 평가합니다.

## 18. 단계별 구현

### 1단계: 기록 가능한 Mission 실행

1. builtin `deep-analysis` Workspace Frontend registry와 공통 Shell slot
2. Deep Analysis Backend domain module과 Core Run·Storage adapter
3. Mission CRUD, Charter·Completion Contract, 상태·자율성 Mode
4. Pattern 없이 만드는 제로베이스 Workflow와 선택적 builtin Workflow Pattern, 사용 시 Mission별 인스턴스화·version 고정
5. 고정된 Workflow revision과 기본 Node 종류
6. 순차 실행, 상태, 질문·결정과 재실행
7. 단위별 LLM 출력 Markdown 자동 저장
8. Mission 누적 비용과 사용량
9. File Root provider와 `파일 → 심층분석` 평면 파일 목록
10. Core prompt-cache usage·가격 계약 연결과 stable Mission prefix
11. 최소 entity·typed API, idempotent command와 canonical event replay

### 2단계: 수치 계산과 시각 Workflow 편집

1. Python 계산 Node와 sandbox
2. CSV 입력·출력과 정합성 검증
3. drag·connect Workflow Canvas
4. Node Inspector와 하단 실행 Drawer
5. Workflow Draft revision과 실행 revision 분리
6. 비용 breakdown과 예산 threshold
7. Project scope Pattern Library와 Pattern 미리보기
8. 조건부 branch, adaptive slot과 Pattern input·output contract
9. Workflow dependency compile, 중복 Tool 병합과 semantic output 연결
10. Claim·Evidence·Open Issue와 deterministic Quality Gate

### 3단계: 동적 확장과 장기 복구

1. AI 제안 Node와 사용자 승인
2. branch·depth·비용 기반 자동 확장 제한
3. Sub-workflow, 가상 group과 대규모 Canvas 탐색
4. 관련 MD·Evidence 선택형 Context 조립
5. Mission 단위 중단·재접속·Worker restart 복구
6. 결론·보고서에서 Evidence와 계산 lineage 역추적
7. 완료 Mission 비교에 기반한 Pattern 개선 후보와 승인형 version publish
8. exact·extractive·reference·compressed Context Pack과 압축 품질 Gate
9. 평가 기반 Model cascade·routing과 OOD fallback
10. 제한된 offline Workflow 개선 탐색과 비용·품질 회귀 suite

## 19. 수용 기준

1. 사용자는 `심층분석` 독립 메뉴에서 Mission을 생성하고 현재 상태를 확인할 수 있습니다.
2. 사용자는 `Workflow` Canvas에서 Node를 추가·이동·연결하고 Node 상세를 열 수 있습니다.
3. 실행 중 Workflow는 revision으로 고정되고 편집은 새 Draft revision에만 반영됩니다.
4. 각 완료 Node의 실제 LLM 출력이 추가 모델 호출 없이 고유한 Markdown 파일로 저장됩니다.
5. Mission 폴더 아래에 Node별 불필요한 물리 폴더가 자동 생성되지 않습니다.
6. 파일명은 `{Node ID}_{작업명}_{용도}` 규칙으로 고유하며 Windows와 Linux에서 안전합니다.
7. 수치 계산은 재현 가능한 Python·SQL·계산 Tool로 수행되고 입력·코드·결과와 검증 version을 추적할 수 있습니다.
8. 검증에 실패한 수치가 확정 결론이나 최종 보고서로 자동 승격되지 않습니다.
9. 기본 Canvas에는 누적 비용과 예산 비율만 표시되고 Node별 비용은 상세 또는 opt-in에서 확인됩니다.
10. 사용자는 누적 비용을 눌러 단계·Node·Model·날짜·재실행별 breakdown과 예상 완료 비용을 확인할 수 있습니다.
11. `파일` 화면에는 `프로젝트 파일`과 `심층분석` root가 같은 수준으로 표시됩니다.
12. Project 원본 파일은 Mission에 복제하지 않고 exact reference로 연결됩니다.
13. 후속 Node는 Workflow에 연결된 관련 MD와 근거만 Context로 받고 모든 과거 대화와 파일을 무조건 포함하지 않습니다.
14. 질문, 사용자 결정, Workflow 변경, Node 실행·재실행, 비용과 생성 파일이 감사 가능한 event로 남습니다.
15. 브라우저 연결이 끊겨도 실행이 계속되며 재접속 시 Workflow, partial output, 비용과 파일 상태를 복원합니다.
16. 최종 보고서에서 관련 Node 출력, 계산 파일과 Evidence를 역추적할 수 있습니다.
17. `deep-analysis`는 명시적인 builtin Workspace Frontend와 Backend domain module로 등록되고 일반 채팅·공통 Shell·Project 파일 내부에 전용 조건문을 흩뿌리지 않습니다.
18. `deep-analysis` registry와 module 코드를 제거해도 Core 인증·채팅·Run·Project 파일·Artifact의 test, typecheck와 build가 계속 통과하며 전용 데이터 보존·export 정책은 코드 제거와 별도로 적용됩니다.
19. 사용자는 Pattern 없이 AI가 새로 설계한 Workflow, 추천 Pattern을 일부 활용한 Workflow 또는 지정한 Pattern 기반 Workflow 중 하나로 Mission을 시작할 수 있습니다.
20. Pattern을 사용한 경우에만 시스템이 Pattern version과 생성된 Workflow revision을 함께 고정하며, Pattern reference가 없는 Mission도 동일하게 실행·복구·감사할 수 있습니다.
21. 같은 Pattern으로 시작한 Mission도 목표·답변·자료·정책과 중간 결과가 다르면 서로 다른 Workflow를 만들며 변경 이유를 revision diff에서 확인할 수 있습니다.
22. Pattern에는 특정 Mission의 파일 ID·수치·답변·출력·비밀값이 포함되지 않고 semantic input role만 저장됩니다.
23. 완료 Mission의 변경은 기존 Pattern을 자동 덮어쓰지 않으며 검토·승인된 개선 후보만 새 immutable version으로 publish됩니다.
24. 같은 Mission과 Tool·Node Profile의 반복 호출은 stable prefix를 canonical하게 재사용하고 변동 정보는 tail에 배치합니다.
25. 비용 집계와 예상 완료 비용은 Provider별 cache write·read·일반 input 단가와 가격표 version을 구분하며 cache 미적용 상한도 제공합니다.
26. Prompt cache 할인 때문에 불필요한 Tool·자료를 넣거나 별도 warming 호출을 만들지 않고 사용자·Organization·Project 권한 scope를 넘어서 cache를 재사용하지 않습니다.
27. 자체 서빙 KV cache의 latency·throughput 개선과 외부 Provider의 API cache 할인은 서로 다른 지표로 기록하고 논문 benchmark를 Lumina 예상 절감률로 표시하지 않습니다.
28. 압축 Context는 원본 reference와 검증 결과를 가지며 사용자 결정·공식 수치·계산식·직접 인용·핵심 Evidence를 대체하지 않습니다.
29. 저비용 Model routing은 scope별 품질 평가를 통과해야 하고 OOD·고위험·낮은 confidence 요청은 강한 Model 또는 명시 정책으로 fallback합니다.
30. 실행 전 dependency compile과 중복 Tool 병합을 수행하되 병렬화가 호출 수·Token을 줄였다고 별도 계측 없이 간주하지 않습니다.
31. Workflow 자동 탐색은 실행 Mission의 예산을 암묵적으로 사용하지 않고 별도 offline 예산·평가·승인 과정에서 Pattern 개선 후보로만 수행합니다.
32. Mission 실행 전에 목적·필수 질문·산출물·범위·품질·잔차·예산·승인을 포함한 Charter와 Completion Contract를 revision으로 고정합니다.
33. `strict`, `balanced`, `exploratory` 자율성 Mode는 조직 정책 상한 안에서 동작하고 실행 중 변경은 새 policy revision으로 기록됩니다.
34. 핵심 결론은 Claim으로 저장되고 supporting·contradicting Evidence, 계산 결과와 원본 exact locator를 역추적할 수 있습니다.
35. 미설명 잔차·자료 부족·상충 근거·제외 범위는 Open Issue로 보존되고 최종 보고서에서 확정 결론과 구분됩니다.
36. 최종 보고서 확정 전에 수치 정합성·Evidence coverage·반대 근거·stale·Completion Contract를 검사하는 Quality Gate를 통과하거나 명시적 waiver를 기록합니다.
37. `completed`와 목표 충족 여부를 분리해 `satisfied`, `satisfied_with_exceptions`, `not_satisfied`를 표시하고 자료 부족 결과를 성공한 분석처럼 표현하지 않습니다.
38. Mission·Workflow·Node 관계는 query 가능한 entity로 저장하고 write command는 권한 검사·ETag 또는 expected revision·idempotency를 적용합니다.
39. 재접속 시 Mission snapshot과 canonical event replay로 Node·Decision·Claim·File·비용·Quality Gate 상태를 중복 없이 복원합니다.

## 20. 구현 시작 기준

### 20.1 첫 Vertical Slice

첫 구현은 Canvas 기능을 넓게 만드는 것보다 다음 하나의 사용자 흐름을 end-to-end로 완성합니다.

```text
Mission 생성
→ Charter·Completion Contract 확인
→ zero-based 고정 Workflow Draft 생성
→ 사용자 질문 1건과 Decision 저장
→ LLM 분석 Node 실행·Markdown 자동 저장
→ Python 계산 Node 실행·CSV와 검증 결과 저장
→ Claim·Evidence 연결
→ Quality Gate
→ 최종 보고서 Markdown 생성
→ 누적 비용·cache usage 표시
→ 브라우저 재접속 후 동일 상태 복원
→ Mission export
```

이 Slice에서 Project 격리, exact file version, 실행 revision 고정, idempotent command, partial failure, stale 전파와 event replay까지 검증합니다. 단순 화면 demo만 동작하고 복구·권한·비용 원본이 없는 상태는 1단계 완료가 아닙니다.

### 20.2 초기 구현에서 의도적으로 미루는 것

- 사용자 설치형 Workflow plugin과 remote module loader
- 별도 범용 Workflow engine 또는 LangGraph runtime 교체
- Organization·Personal Pattern 공유와 Marketplace
- 학습형 Model Router와 online Workflow MCTS
- CacheBlend·Preble 같은 self-hosted inference scheduler 기능
- 무제한 Sub-agent, 자동 외부 write와 사용자 승인 없는 고비용 확장
- 모든 Node 종류와 고급 Canvas group·minimap·대규모 layout 최적화

이 항목은 Core 계약과 실제 사용량이 확인된 뒤 별도 설계·검증합니다. 초기 schema와 UI에 동작하지 않는 placeholder를 노출하지 않습니다.

### 20.3 필수 검증 Matrix

| 영역 | 최소 검증 |
|---|---|
| 권한 | 다른 Project·사용자의 Mission, Pattern, 파일, Claim과 export 접근 거부 |
| Revision | 실행 revision 불변, Draft 편집 분리, stale writer·no-op write 차단 |
| 실행 | 순차·병렬 dependency, pause·resume·cancel·retry, Worker restart 복구 |
| 파일 | LLM 출력 MD 동일성, 평면 고유 파일명, exact version·digest·lineage |
| 계산 | sandbox, deterministic rerun, schema·합계·허용 오차와 validation failure |
| Claim | support·contradict locator, Open Issue, stale 전파와 report 역추적 |
| 비용 | cached·uncached·cache write·output, retry, 가격표 version과 hard limit |
| Context | manifest 재현, 권한 범위, 압축 fallback, prefix hash·무효화 사유 |
| 복원 | snapshot과 Last-Event-ID replay, 중복·누락 event, partial output |
| UI | Mission 목록, Canvas, Inspector, Decision, 결론·근거, 비용, 보고서와 반응형 배치 |
| 접근성 | Keyboard Canvas 조작, focus 복원, 상태 text·icon, 색상 비의존 |
| 제거성 | `deep-analysis` module 제거 뒤 Core 인증·채팅·Run·Project 파일 test·build 통과 |

실제 UI 구현 후에는 사용자 runtime을 재사용하지 않는 격리 port와 browser context에서 화면, 재접속, 오류 상태, console과 반응형 배치를 확인합니다.

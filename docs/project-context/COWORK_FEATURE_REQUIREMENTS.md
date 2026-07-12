> 생성일: 2026-07-12

# Claude/Cowork 계열 기능의 Lumina 반영 요구사항

## 목적

이 문서는 사용자가 제공한 Claude Cowork 중심 기능 지도를 Lumina Agent의 제품 요구사항으로 통합한 결과입니다. 일부 기능은 Hermes Agent 분석과 기존 Agent Loop·Purpose UI 설계에 이미 포함되어 있으므로 중복된 개념은 하나의 공통 요구사항으로 합칩니다.

이 문서의 기능은 다음 우선순위 표에서 “후순위” 또는 “보류”로 명시하지 않은 한 Lumina의 제품 방향에 반영합니다.

## 기존 설계와의 통합 관계

| Cowork 계열 기능 | Lumina의 기존 설계 | 통합 결과 |
|---|---|---|
| 자율 다단계 작업 | `AGENT_LOOP.md`의 Turn·Tool·Queue·중단/재개 | Plan·Subtask·Steering·단계 재실행을 추가 |
| 로컬 파일 작업 공간 | `@파일명`, Artifact, Storage | 명시 연결 Workspace와 Local Bridge를 추가 |
| 전문 업무 산출물 | Artifact Library | 형식별 생성·Preview·검증·부분 수정 추가 |
| Project 지속성 | 사용자·조직·세션 구조 | `Organization → Project → Session → Run`으로 확장 |
| Connector·MCP·Skill·Plugin | `extensions/`, `$` 호출 | 동적 Tool 로딩과 조직 승인 수명주기 추가 |
| 브라우저·컴퓨터 사용 | Tool·승인 UI | Connector 우선 원칙과 고위험 확인 강화 |
| 예약 작업 | Hermes 기능 분석의 Scheduler | Task Definition과 Run 분리, 원격 실행을 요구 |
| Live Artifact·Interactive UI | `PURPOSE_DRIVEN_AGENT_UI_RESEARCH.md` | UI Profile·Component Registry 설계를 구현 기준으로 사용 |

## 1. 자율적인 다단계 작업

### 제품 목표

사용자는 하나의 업무 목표를 전달하고, Lumina는 이를 계획과 하위 작업으로 나누어 순차 또는 병렬로 실행합니다. 사용자는 실행 중 진행 상태를 확인하고 추가 지시·일시 정지·재개·취소·단계 재실행을 수행할 수 있어야 합니다.

### 사용자 체감 기능

- 시작 전에 간단한 작업 계획과 예상 산출물을 표시합니다.
- 각 하위 작업에 `queued`, `running`, `blocked`, `approval`, `completed`, `failed`, `cancelled` 상태를 표시합니다.
- 하위 작업별 입력, 사용한 Tool, 중간 결과, artifacts와 오류를 확인할 수 있게 합니다.
- 서로 독립적인 조사·파일 분석은 병렬 실행합니다.
- 사용자가 실행 중 추가 지시를 보내면 현재 실행을 무조건 폐기하지 않고 다음 안전한 경계에서 반영합니다.
- 전체 Run을 일시 정지·재개·취소할 수 있습니다.
- 실패한 단계만 입력 snapshot을 기준으로 재실행할 수 있습니다.
- 최종 답변과 상세 실행 로그를 분리해 기본 화면은 읽기 쉽게 유지합니다.

### Frontend 요구사항

```text
Run Header
├─ 목표와 현재 상태
├─ 일시 정지·재개·취소
└─ 전체 진행률

Plan Timeline
├─ Step/Subtask 상태
├─ 입력·출력·Artifact
├─ 오류와 재실행
└─ 병렬 실행 그룹
```

- Timeline은 사용자에게 의미 있는 업무 단계 중심으로 표시하며 내부 model turn을 그대로 나열하지 않습니다.
- 실행 중 사용자 메시지는 `steer`, `queue_next`, `cancel_and_restart` 중 어떤 방식으로 적용되는지 명확히 보여줍니다.
- 중간 지시가 아직 적용되지 않았다면 대기 상태로 표시합니다.
- Run 실행 중에도 Composer 입력과 전송을 허용합니다. 기본 `Enter`와 전송 버튼은 `현재 작업에 반영(steer)`, `Ctrl+Enter`는 `다음 요청으로 대기(queue_next)`, `Shift+Enter`는 줄바꿈으로 동작하며 보조 메뉴에서도 두 전송 동작을 선택할 수 있게 합니다.
- 전송된 추가 메시지에는 `steer 대기`, `현재 Run에 반영됨`, `Queue 1번`, `취소됨`처럼 처리 상태를 표시합니다.
- 대기 중 steer와 queued message는 실행 전에 취소할 수 있고, queued message는 현재 Run의 assistant 답변과 시각적으로 구분합니다.

### Backend 요구사항

- `Run → Step → Subtask` 계층과 의존 관계를 저장합니다.
- 병렬 가능한 Subtask만 동시 실행하고 선행 단계가 필요한 작업은 dependency를 기다립니다.
- 각 Step의 입력·옵션·Context·Provider·Model·Tool 버전을 snapshot으로 저장합니다.
- 재실행 시 완료된 다른 Step의 결과를 훼손하지 않습니다.
- pause는 새 Tool 실행을 막고 현재 안전한 작업이 끝난 뒤 상태를 저장합니다.
- 취소, pause, steer와 retry는 idempotent API로 제공합니다.
- 누가 계획을 수정하고 지시·승인·재실행했는지 감사 기록을 남깁니다.
- steer는 현재 Run 안에서 다음 안전한 model Turn·Step 경계에 적용하고, `queue_next`는 현재 Run의 terminal state 이후 별도 Run으로 승격합니다.
- text streaming 중 steer는 Provider의 안전한 취소 capability가 있으면 협력적으로 중단해 빠르게 반영하고, 부작용 Tool 실행은 강제 중단하지 않습니다.
- 추가 입력과 상태 이벤트는 DB를 원본으로 저장하여 세션 전환·재연결·event replay 후에도 접수 순서와 적용 여부를 복원합니다.

### Agent Loop 통합

상세 실행은 `AGENT_LOOP.md`를 따릅니다. Plan은 모델이 마음대로 표시하는 문장만으로 끝내지 않고 Backend가 추적할 수 있는 구조화된 Step 상태로 관리합니다.

## 2. 명시적으로 연결하는 파일 Workspace

### 제품 목표

파일은 단순 첨부가 아니라 지속되는 업무 입력과 산출물입니다. 사용자가 허용한 Project Workspace 안에서 Agent가 파일을 읽고 결과를 지정 위치에 저장할 수 있어야 합니다.

### 서버형 Lumina에서의 해석

브라우저로 접속하는 서버 프로그램은 사용자 PC의 임의 폴더를 직접 읽을 수 없습니다. 따라서 다음 연결 방식을 구분합니다.

```text
Server Workspace   → 서버 또는 Object Storage의 Project 파일
Uploaded Files     → 사용자가 업로드한 Project 파일
Local Workspace    → 사용자 PC의 Local Bridge가 허용 폴더만 연결
Remote Connector   → SharePoint, Drive, Box 등 외부 저장소
```

`Server Workspace`가 Lumina의 기본 저장 위치입니다. 채팅의 `저장`과 Agent의 Artifact 생성·편집 결과는 사용자의 브라우저 PC가 아니라 Lumina Backend가 구동되는 서버 또는 PC의 관리 저장소에 기록합니다. 사용자의 개인 PC에는 사용자가 명시적으로 브라우저 다운로드를 실행할 때만 사본을 전달합니다. 초기에는 단일 구동 장비의 관리된 `data/` 영역을 사용할 수 있지만, API와 metadata는 Storage Adapter를 통해 향후 별도 S3/MinIO 또는 조직 파일 서버로 이전할 수 있게 합니다.

Local Bridge가 없는 환경에서는 “로컬 폴더 직접 접근”을 제공한다고 오해하게 만들지 않습니다. 초기 버전은 Upload와 Server Workspace부터 구현하고, Local Bridge는 이후 별도 설치 구성요소로 제공합니다.

### 사용자 체감 기능

- 사용자가 명시적으로 연결한 폴더와 Project 파일만 접근합니다.
- Project 화면에 파일 트리, 검색, Preview와 최근 변경을 표시합니다.
- `@파일명`으로 채팅에서 파일을 빠르게 연결합니다.
- Agent가 파일을 생성·수정하면 저장 위치와 변경 내용을 표시합니다.
- 기존 파일 덮어쓰기 전에 diff 또는 새 버전 생성을 기본으로 합니다.
- 삭제는 휴지통 이동과 영구 삭제를 구분하고 영구 삭제는 추가 승인을 요구합니다.
- 생성된 파일에서 원본 입력과 생성 Run으로 이동할 수 있습니다.

### Backend 요구사항

- Project별 허용 Workspace root와 Storage key 범위를 관리합니다.
- Frontend가 보낸 raw path를 신뢰하지 않고 reference ID를 다시 검증합니다.
- 경로 탈출, symbolic link, 절대 경로와 다른 사용자 Workspace 접근을 차단합니다.
- 파일 버전, checksum, 작성자, 원본 Run과 변경 이유를 기록합니다.
- 쓰기 작업은 optimistic concurrency 또는 base version을 사용해 다른 사용자의 변경을 덮어쓰지 않습니다.
- Local Bridge는 사용자 인증, 장치 등록, 폴더별 grant와 폐기 기능을 제공해야 합니다.

### 폴더별 지침

Project 또는 연결 폴더에 `AGENTS.md` 같은 지침을 둘 수 있습니다. 적용 범위와 우선순위를 사용자에게 표시하고, 사용자 지침이 시스템·조직 보안 정책을 우회하지 못하게 합니다.

## 3. 전문적인 업무 산출물

### 제품 목표

최종 결과는 채팅 Markdown에 머물지 않고 제출·공유·편집 가능한 업무 파일이어야 합니다.

### 필수 생성 형식

- DOCX
- XLSX
- PPTX
- PDF
- 독립 실행 가능한 HTML

### 보고서 기본 형식

- 사용자가 파일 유형을 언급하지 않고 보고서 작성을 요청하면 독립 실행 가능한 HTML 보고서를 생성합니다.
- 사용자가 DOCX, XLSX, PPTX, PDF, Markdown 등 특정 형식을 명시하면 명시된 형식을 우선합니다.

### 사용자 체감 기능

- 채팅 옆 Preview에서 문서·표·슬라이드·PDF·HTML을 확인합니다.
- 산출물을 다운로드하거나 Project Workspace에 저장합니다.
- 선택한 문장, 표 영역, 셀 범위 또는 슬라이드만 수정 요청할 수 있습니다.
- 수정 전후 버전을 비교하고 이전 버전으로 복원합니다.
- 회사 템플릿, 색상, 로고와 문체 규칙을 Skill로 선택합니다.
- 생성 완료 표시와 별도로 형식 검증 결과를 보여줍니다.

### 형식별 검증

```text
DOCX → 페이지 렌더, 잘림, 표·헤더·폰트 확인
XLSX → 수식, 참조 오류, 셀 형식, 차트와 sheet 구조 확인
PPTX → 슬라이드 넘침, 겹침, 폰트, 이미지와 편집 가능성 확인
PDF  → 페이지 렌더, 링크, 글자 깨짐과 접근성 확인
HTML → 브라우저 렌더, console 오류, 링크와 반응형 확인
```

생성 성공과 품질 검증 성공을 구분합니다. 검증 실패 시 사용자에게 파일을 완성으로 표시하지 않고 수정 또는 제한 사항을 안내합니다.

### 부분 수정 원칙

- 전체 파일을 매번 재생성하지 않고 가능한 경우 선택 영역만 수정합니다.
- 수정 대상과 비대상 영역을 구분하고 비대상 영역의 회귀를 검사합니다.
- 각 수정은 새 artifact version으로 저장합니다.

## 4. Project: 파일·지침·기억의 지속성

### 기본 계층

```text
Organization
└─ Project
   ├─ Members and Roles
   ├─ Instructions
   ├─ Files and Connected Folders
   ├─ Allowed Connectors / Skills / Plugins
   ├─ Project Memory
   ├─ Scheduled Tasks
   └─ Sessions
      └─ Runs
```

Project는 반복 업무의 배경, 용어, 이해관계자, 출력 형식과 데이터 접근 범위를 유지하는 기본 공간입니다.

### 사용자 체감 기능

- 새 채팅을 Project 안에서 시작하면 Project 지침과 허용 Context를 자동 적용합니다.
- Project 파일·URL·Connector·Skill을 한곳에서 관리합니다.
- Project 안의 세션과 artifacts를 통합 검색합니다.
- 과거 결과를 새 작업의 입력으로 재사용합니다.
- Project Memory를 조회·수정·삭제하고 출처 대화를 확인합니다.
- 다른 Project의 Memory와 파일이 섞이지 않습니다.
- 세션을 닫아도 Run checkpoint와 작업 이력이 유지됩니다.

### 공유 모드와 관계

공유 모드는 Project 또는 Workspace 범위로 적용합니다. 전역적으로 모든 Project를 섞는 방식보다 명시된 공유 Project 안에서 대화·옵션·artifacts를 공유하는 방식이 기본입니다.

## 5. Connectors·MCP·Skills·Plugins

### 역할

```text
Connector → 외부 서비스의 인증된 데이터와 작업 API
MCP       → 표준 Tool·Resource 연결
Skill     → 업무 절차, 템플릿, 스크립트와 품질 기준
Plugin    → Skill·MCP·Provider·UI·설정을 묶은 설치 단위
```

### 사용자 체감 기능

- 통합 디렉터리에서 설치 가능한 항목과 조직 제공 항목을 탐색합니다.
- 설치 전에 필요한 권한, 외부 전송 데이터, 실행 코드와 의존성을 보여줍니다.
- `$이름`으로 현재 요청에서 Skill 또는 MCP를 명시적으로 호출합니다.
- Project마다 허용 Connector·Skill·Plugin 목록을 관리합니다.
- 업데이트 가능 버전, 현재 고정 버전, 변경 내역과 폐기 상태를 표시합니다.
- 비활성화하거나 제거해도 과거 Run에서 사용한 버전과 출처는 기록으로 남깁니다.

### 동적 Tool 접근

모든 Tool schema를 모든 모델 요청에 넣지 않습니다.

```text
요청과 Project 정책 분석
→ 관련 Skill·Plugin·MCP 탐색
→ 필요한 Tool만 Run snapshot에 로드
→ Agent Loop 실행
```

- 사용자가 `$`로 명시 호출한 Skill·MCP는 우선 후보로 포함합니다.
- Provider capability와 조직 정책에 맞지 않는 Tool은 제외합니다.
- Tool 목록은 Run 시작 시 snapshot으로 고정하고 진행 중 임의 변경하지 않습니다.
- 사용하지 않는 Tool로 인한 Context·비용 낭비를 측정합니다.

### 조직 관리

- 설치 승인과 배포 권한
- 버전 고정과 단계적 rollout
- 취약 버전 차단과 폐기
- Plugin 코드 및 의존성 검사
- 데이터 접근 범위와 감사 로그
- 사용자별 credential과 조직 credential 분리

## 6. 브라우저 및 컴퓨터 사용

### 연결 우선순위

안정성과 정확도가 높은 연결을 먼저 선택합니다.

```text
전용 Connector/API
→ MCP Tool
→ Browser DOM 자동화
→ 화면 기반 Computer Use
```

Computer Use는 API가 없는 레거시 ERP, 사내 Dashboard와 Desktop 앱 같은 마지막 구간을 처리하기 위한 fallback입니다.

### 사용자 체감 기능

- 현재 어떤 앱·사이트에서 무엇을 수행 중인지 단계별로 표시합니다.
- 로그인, 민감 정보, 결제, 전송, 게시, 삭제 전에 승인을 요청합니다.
- 실행 결과를 screenshot·DOM 결과·다운로드 파일 등으로 검증합니다.
- 실패 시 무한 재시도하지 않고 현재 화면과 필요한 사용자 행동을 안내합니다.
- 사용자가 중간에 직접 제어권을 가져오고 다시 Agent에 넘길 수 있게 합니다.

### 보안 요구사항

- 허용 domain과 앱 범위
- credential 직접 노출 금지
- 입력·클릭 전 위험 분류
- 외부 전송과 삭제의 명시 승인
- 실행 화면과 결과 증거의 감사 기록
- 민감 화면 screenshot 보존 정책

범용 Computer Use보다 Connector와 Browser 자동화를 먼저 구현합니다.

## 7. 예약 작업과 루틴

### 데이터 모델 원칙

작업 정의와 실제 실행을 분리합니다.

```text
ScheduledTask
├─ schedule
├─ Project and instructions
├─ Provider / Model / Effort
├─ Skill / Plugin / Connector permissions
├─ input template
├─ delivery policy
└─ enabled

ScheduledRun
├─ immutable input snapshot
├─ status and attempts
├─ outputs and artifacts
├─ usage and cost
├─ error and approval state
└─ started/finished timestamps
```

### 사용자 체감 기능

- 시간별·일별·주별·평일·수동 실행을 지원합니다.
- 다음 실행, 최근 실행과 현재 상태를 표시합니다.
- 일시 정지·재개·수정·즉시 실행을 제공합니다.
- 실패한 Run 재시도와 결과 비교를 제공합니다.
- 성공·실패·승인 필요 알림을 전달합니다.
- 결과를 Project, 채팅, 이메일 또는 허용 Connector로 전달합니다.

### 실행 안정성

- 동일 예약 시각의 중복 실행을 방지합니다.
- retry와 timeout을 Task 정책으로 관리합니다.
- 실행 시점의 설정과 입력을 snapshot으로 저장합니다.
- PC가 꺼져도 동작해야 하는 Task는 서버 Worker에서 실행합니다.
- Local Bridge가 필요한 Task는 해당 장치가 offline이면 명확히 대기 또는 실패 처리합니다.

## 8. Live Artifacts와 대화 안의 Interactive UI

### 제품 목표

반복해서 확인하는 분석과 작업 상태는 매번 새 자연어 보고서를 생성하지 않고 지속형 Artifact 또는 Interactive UI로 제공합니다.

### 사용자 체감 기능

- Artifact를 별도 탭 또는 채팅 옆 panel에서 다시 엽니다.
- 연결 데이터와 Project 파일을 기준으로 새로 고칩니다.
- 변경 요청을 대화로 전달하고 갱신 결과를 즉시 확인합니다.
- 버전 이력, diff와 복원을 제공합니다.
- Dashboard, 작업 board, filter와 form을 대화 안에서 직접 조작합니다.

### 구현 기준

상세 구현은 `PURPOSE_DRIVEN_AGENT_UI_RESEARCH.md`의 다음 설계를 따릅니다.

- 공통 Run/Event Contract
- UI Profile
- 검증된 Component Registry
- 제한된 선언형 UI schema
- MCP Apps용 sandbox 확장 경로
- Backend에서 검증하는 typed UI action

Agent가 제품의 핵심 UI 코드를 매번 자유 생성하게 하지 않습니다. Live HTML Artifact와 제품 UI Profile은 구분합니다.

## 공통 사용자 경험 원칙

### 최종 결과와 실행 과정 분리

기본 화면에는 결론과 산출물을 우선 표시하고, Tool log·중간 reasoning·재시도 상세는 접힌 실행 기록에서 확인하게 합니다.

### 변경 가능성과 복구 가능성

파일, Artifact, Plan과 예약 작업은 버전 또는 이력을 남깁니다. 사용자가 생성형 변경을 되돌릴 수 있어야 합니다.

### 중간 개입

Agent 실행은 “시작 또는 취소” 두 상태만 갖지 않습니다. steer, pause, approve, resume와 retry-step을 명시적인 action으로 제공합니다.

답변 생성 중 추가 입력은 현재 Run을 수정하는 `steer`와 다음 Run으로 순차 실행하는 `queue_next`를 모두 지원합니다. 두 동작의 Composer UX, 안전 경계, Provider 취소, Queue 승격과 복구 계약은 `AGENT_LOOP.md`의 “답변 생성 중 Steer와 순차 입력”을 따릅니다.

### 상태의 원본은 Backend

Frontend stream이나 브라우저 저장소가 Run, Plan, Artifact, Task 상태의 원본이 되면 안 됩니다. 재접속 시 DB snapshot과 event history로 복구합니다.

### 최소 권한

Project, 파일, Connector, Skill, Plugin, Browser와 Computer Use 모두 현재 업무에 필요한 범위만 허용합니다.

## 단계별 반영 우선순위

### 1단계: 핵심 업무 실행

1. 구조화된 Plan과 Step 상태
2. 실행 중 steer·pause·resume·cancel
3. 실패 Step 재실행
4. Project 기본 계층과 Project별 지침
5. Upload·Server Workspace와 파일 버전
6. DOCX/XLSX/PPTX/PDF/HTML 생성·Preview·검증 기반
7. Connector·Skill·MCP 동적 로딩

### 2단계: 반복 업무와 지속성

1. Project Memory와 통합 검색
2. Scheduler와 원격 Worker 실행
3. Artifact 버전 비교와 부분 수정
4. Browser 자동화
5. 회사 Template Skill 배포
6. UI Profile 두 종류의 PoC

### 3단계: 확장 자동화

1. Local Workspace Bridge
2. 조직 Plugin Directory와 승인·버전 정책
3. Computer Use
4. 선언형 Interactive UI
5. MCP Apps sandbox host
6. 승인 가능한 자동 Memory·Skill 개선

## 수용 기준

1. 사용자는 다단계 Run의 현재 단계와 병렬 Subtask를 이해할 수 있습니다.
2. 사용자는 실행 중 지시·일시 정지·재개·취소와 실패 Step 재실행을 할 수 있습니다.
3. Agent는 연결되지 않은 폴더와 다른 Project 파일에 접근할 수 없습니다.
4. 전문 산출물은 다운로드 전에 형식별 검증 결과를 가집니다.
5. Project Memory와 검색 결과가 다른 Project로 누출되지 않습니다.
6. 사용하지 않는 Tool을 모델 Context에 무조건 포함하지 않습니다.
7. 위험한 Browser·Computer Use 작업은 승인과 결과 검증을 거칩니다.
8. 예약 작업은 중복 실행 없이 입력 snapshot과 결과 이력을 보존합니다.
9. Live Artifact는 버전 이력과 복원을 지원합니다.
10. Frontend 연결이 끊겨도 Run과 예약 작업은 Backend에서 계속됩니다.

## 참고한 공식 설명 주제

사용자가 제공한 기능 지도는 다음 Claude Cowork 공식 설명 주제를 기반으로 합니다. 구현 시점에는 최신 공식 문서와 회사 정책을 다시 확인합니다.

- Organize your tasks with projects in Claude Cowork
- Browse skills, connectors, and plugins in one directory
- Use plugins in Claude
- Use skills in Claude
- Manage Claude’s tool access
- Let Claude use your computer in Cowork
- Schedule recurring tasks in Claude Cowork
- Use live artifacts in Claude Cowork
- Use interactive connectors in Claude

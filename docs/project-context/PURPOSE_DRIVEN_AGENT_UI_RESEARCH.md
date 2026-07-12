> 생성일: 2026-07-12

# 목적별 Agent UI 생성·전환 유사 사례 조사

조사일: 2026-07-11

## 요약

Lumina Agent의 Agent Core와 실행 계약은 유지하면서, 사용 목적에 따라 UI를 빠르게 만들고 전환하는 구상은 현재 **Agentic UI**, **Generative UI**, **Agent-driven UI**라는 이름으로 활발히 구현되고 있습니다.

가장 가까운 사례는 다음 세 부류입니다.

1. **동일한 Agent에 교체 가능한 Frontend를 연결**: AG-UI, LangChain Agent Chat UI
2. **검증된 컴포넌트 카탈로그에서 Agent가 화면을 선택·조합**: CopilotKit Generative UI, Google A2UI, Vercel AI SDK UI
3. **Tool 또는 외부 서비스가 자체 UI를 함께 제공**: MCP Apps, OpenAI Apps SDK

Lumina의 우선 목표는 Agent가 화면을 동적으로 생성하는 것이 아닙니다. 먼저 **동일한 Backend와 Agent Core에 서로 다른 Frontend를 쉽게 갈아 끼울 수 있는 구조**를 만들어야 합니다. 범용 채팅 UI도 고정된 유일한 제품 화면이 아니라, 공통 Backend 계약에 연결된 첫 번째 기본 Agent Frontend로 취급합니다. 이후 필요할 때 A2UI 또는 MCP Apps 호환 계층을 추가합니다.

## 구상을 더 구체적으로 정의하면

사용 목적에 따라 바뀌는 것은 Agent Core가 아니라 **작업을 보여주고 입력받는 Frontend application**입니다.

예를 들면 같은 Agent Run을 다음처럼 표현할 수 있습니다.

| 사용 목적 | 주 UI | 같은 Core Event의 표현 |
|---|---|---|
| 일반 조사 | 채팅 + 출처 패널 | Tool Call을 검색 진행과 출처 목록으로 표시 |
| 보고서 작성 | 문서 캔버스 + 근거 패널 | Artifact 생성·수정을 문서 버전으로 표시 |
| 데이터 분석 | 필터 + 표 + 차트 | Tool Result를 데이터셋과 시각화로 표시 |
| 운영 모니터링 | 상태판 + 로그 + 승인함 | Run Event를 실시간 상태와 경고로 표시 |
| 배포 작업 | 단계형 Wizard + diff + 승인 | Tool Call을 검증 단계와 위험 승인으로 표시 |

핵심은 각 Frontend가 Agent Loop를 복제하지 않고, 공통 Backend API와 상태·Tool·Artifact·승인 이벤트 계약을 사용하게 만드는 것입니다. 전용 Frontend는 일반 채팅의 패널 조합에 제한되지 않으며, 업무에 맞는 완전히 다른 화면과 사용자 흐름을 가질 수 있습니다.

## 유사 사례

### 1. AG-UI: Agent Core와 사용자 UI 사이의 공통 이벤트 계약

AG-UI는 Agent backend와 사용자-facing application 사이에서 Agent 상태, UI intent, 사용자 상호작용을 전달하는 양방향 이벤트 프로토콜입니다. Streaming, shared state, frontend tool call, backend tool rendering, human-in-the-loop 등을 공통 building block으로 정의합니다.

Lumina와 가장 직접적으로 닮은 부분은 **Core를 바꾸지 않고 여러 Frontend를 붙일 수 있는 경계**입니다. Lumina의 기존 SSE/WebSocket 이벤트를 AG-UI와 동일하게 바꿔야 한다는 뜻은 아니지만, 내부 계약을 설계할 때 좋은 기준선입니다.

- 공식 문서: https://docs.ag-ui.com/introduction
- 적합도: 매우 높음
- 참고할 부분: event envelope, run lifecycle, state snapshot/delta, interrupt, frontend action
- 주의점: Lumina의 DB 원본 상태, 세션별 queue, provider snapshot 규칙은 내부 계약으로 계속 유지해야 함

### 2. CopilotKit: 하나의 Runtime에서 UI 생성 수준을 기능별로 선택

CopilotKit은 다음 방식을 한 Runtime에서 함께 제공합니다.

- 이미 만든 React component를 Agent가 선택
- 기존 backend tool call에 전용 UI를 연결
- streamed agent state로 화면을 갱신
- A2UI schema를 component catalog로 렌더링
- MCP server가 제공하는 UI를 sandboxed iframe으로 표시

특히 모든 화면을 자유 생성하는 대신, 기능별로 **개발자 통제형 → 선언형 → 외부 sandbox형** 중 하나를 고르는 구분이 유용합니다.

- 공식 문서: https://docs.copilotkit.ai/a2a/concepts/generative-ui-overview
- 적합도: 매우 높음
- 참고할 부분: component-as-tool, tool renderer, state renderer, catalog 기반 UI
- 주의점: CopilotKit 전체 도입과 패턴 차용은 별개의 결정임

### 3. Google A2UI: Agent가 안전한 선언형 UI를 전달

A2UI는 Agent가 update 가능한 UI 표현을 선언형 형식으로 보내고, Host가 Lit·Angular·Flutter 등의 renderer로 표시하는 오픈소스 프로젝트입니다. Host는 공통 component 또는 자신이 허용한 custom component 목록을 광고할 수 있습니다.

이 방식은 Lumina의 목적별 UI를 “Agent가 HTML/React 코드를 직접 생성”하는 대신 “허용된 컴포넌트와 layout schema를 생성”하게 할 때 적합합니다.

- 공식 소개: https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/
- 적합도: 높음, 특히 장기 방향
- 참고할 부분: declarative tree, client-advertised catalog, incremental update
- 주의점: 초기 제품에서는 dynamic schema보다 fixed schema + data binding부터 시작하는 편이 예측 가능함

### 4. MCP Apps: Tool이 대화 안에서 자체 UI를 제공

MCP Apps는 MCP Tool이 `ui://` resource를 선언하고 Host가 HTML/JavaScript UI를 sandboxed iframe으로 렌더링하는 공식 MCP extension입니다. UI와 Host는 제한된 양방향 메시지 채널로 통신합니다.

복잡한 데이터 탐색, 다수 옵션 설정, rich media preview, 실시간 monitoring, 다단계 workflow에 적합합니다. Lumina에서는 외부 Plugin/MCP가 지도, PDF viewer, 배포 configurator 같은 전문 UI를 제공하는 확장 경로가 될 수 있습니다.

- 공식 문서: https://modelcontextprotocol.io/extensions/apps/overview
- 적합도: 높음, 단 Core UI가 아니라 extension UI에 적합
- 참고할 부분: UI resource declaration, sandbox, CSP/permission, host-mediated tool call
- 주의점: iframe UI를 Lumina의 기본 목적별 shell로 사용하면 브랜드·접근성·상태 일관성이 약해질 수 있음

### 5. OpenAI Apps SDK: 대화 맥락에서 목적별 앱 UI를 호출

OpenAI Apps SDK는 MCP 위에서 앱의 chat behavior와 UI를 함께 정의합니다. ChatGPT가 맥락에 맞는 앱을 제안하거나 사용자가 이름으로 호출하며, 지도·목록·프레젠테이션 같은 familiar UI와 대화를 결합합니다.

Lumina 관점에서 중요한 사례는 “하나의 만능 화면”보다 **사용 목적에 맞는 mini-app surface가 대화 중 활성화**된다는 점입니다.

- 공식 소개: https://openai.com/index/introducing-apps-in-chatgpt/
- 적합도: 중간~높음
- 참고할 부분: contextual app discovery, conversation + interactive surface 결합
- 주의점: ChatGPT 내부 배포 모델을 Lumina 자체 제품 구조와 동일시하면 안 됨

### 6. LangChain Agent Chat UI: Agent와 UI 배포를 분리

LangChain Agent Chat UI는 local 또는 deployed Agent endpoint에 연결되는 별도 Next.js UI이며, real-time chat, tool visualization, interrupts, state forking과 generative UI를 지원합니다.

이는 “Agent 하나에 UI 하나가 소스 레벨로 결합될 필요가 없다”는 실용적 사례입니다. 다만 목적별 업무 화면보다는 범용 Agent 개발·채팅 UI에 가깝습니다.

- 공식 문서: https://docs.langchain.com/oss/python/langchain/ui
- 적합도: 중간
- 참고할 부분: endpoint-driven attachment, automatic tool/interrupt rendering

### 7. Vercel AI SDK UI: Provider와 UI framework의 결합도를 낮춤

Vercel AI SDK는 Core의 text/object/tool generation과 UI용 framework-agnostic hooks를 분리하며 React, Next.js, Vue, Svelte 등을 지원합니다. 목적별 UI 전환 자체를 제품 개념으로 제공하는 것은 아니지만, Agent stream과 UI renderer를 분리하는 구현 참고 사례입니다.

- 공식 소개: https://vercel.com/ai-sdk
- 적합도: 중간
- 참고할 부분: typed message parts, tool UI, streaming hooks

## Lumina에 권장하는 제품 개념

핵심 개념은 `UI Profile`보다 강한 **교체 가능한 Agent Frontend**입니다. 장기적으로 Agent는 다음을 묶는 versioned package가 될 수 있습니다.

```text
Agent Package
├─ Frontend application
├─ Instructions / Workflow
├─ Plugins
├─ Skills
└─ MCP bindings
```

특수목적 Agent를 지금 구현할 필요는 없습니다. 현재 범용 Agent와 일반 채팅 UI부터 같은 package 계약에 등록하여, 향후 새 Frontend가 추가될 때 Backend를 다시 설계하지 않아도 되게 합니다.

### Agent Frontend manifest

```yaml
id: general
version: 1.0.0
name: 범용 Agent
default: true

frontend:
  type: builtin
  module: general-chat
  contract: lumina-frontend-v1

extensions:
  plugins: []
  skills: []
  mcp: []
```

향후 특수목적 Agent는 동일한 계약으로 다른 Frontend module을 지정할 수 있습니다.

```yaml
id: specialized-agent
version: 1.0.0

frontend:
  type: package
  module: specialized-workspace
  contract: lumina-frontend-v1
```

### Frontend가 의존하는 공통 Backend 계약

Backend는 특정 React component, 화면 배치 또는 범용 채팅 UI의 상태 구조를 알아서는 안 됩니다. 모든 Agent Frontend는 다음 공통 기능을 API와 event stream으로 사용합니다.

```text
Common Backend API
├─ authentication and user context
├─ Agent registry and manifest
├─ conversation and messages
├─ Run start / cancel / resume / queue
├─ attachments and artifacts
├─ approval and rejection
├─ Provider and execution options
└─ Plugin / Skill / MCP availability

Canonical Event Stream
├─ run.status.changed
├─ message.delta
├─ message.completed
├─ tool.started
├─ tool.completed
├─ approval.requested
├─ artifact.created
└─ run.completed
```

Backend는 정규화된 상태와 데이터를 제공하고, 이를 채팅·표·차트·타임라인·업무용 편집기 중 무엇으로 표현할지는 Frontend가 결정합니다.

### Frontend Host

초기에는 웹 애플리케이션 전체를 매번 독립 배포하기보다, 공통 Shell 안의 Agent Frontend slot에 module을 장착하는 방식이 적합합니다.

```text
Lumina Web Shell
├─ login and user context
├─ Agent selector
├─ notifications
├─ common settings
├─ permission and fatal error handling
└─ Agent Frontend Slot
   ├─ GeneralChatFrontend       # 현재 기본 UI
   └─ InstalledAgentFrontend    # 향후 확장
```

공통 Shell은 로그인, 알림과 전역 설정만 소유합니다. Agent Frontend slot 내부는 목적에 따라 완전히 다른 route, layout, form과 interaction을 가질 수 있습니다.

장기적으로는 신뢰 수준과 배포 방식에 따라 다음 type을 지원할 수 있습니다.

```text
builtin   → Lumina와 함께 빌드된 Frontend module
package   → 설치된 Agent package의 Frontend module
remote    → 동일 Backend 계약을 사용하는 독립 웹 애플리케이션
sandbox   → 신뢰하지 않는 외부 UI를 격리한 iframe application
```

초기 구현 범위는 `builtin` 하나면 충분합니다. 다만 manifest와 Backend 계약이 나머지 방식을 가로막지 않아야 합니다.

### 공통 Frontend SDK

각 Frontend가 API, 인증, reconnect와 event parsing을 다시 구현하지 않도록 `apps/web` 안에 공통 client 계층을 둡니다.

```text
Lumina Frontend SDK
├─ API client
├─ authenticated session
├─ conversation client
├─ Run and event stream client
├─ approval client
├─ artifact client
└─ typed contracts
```

범용 채팅 Frontend도 이 SDK만 통해 Backend에 접근해야 합니다. 이 경계가 지켜져야 향후 다른 Frontend를 실제로 갈아 끼울 수 있습니다.

## 권장 아키텍처

```text
                         ┌─ General Chat Frontend
Lumina Web Shell ────────┼─ Installed Agent Frontend
                         └─ Future Remote/Sandbox Frontend
            │
            │ Lumina Frontend Contract
            ▼
FastAPI Backend
├─ Agent Registry
├─ Conversation / Message
├─ Run / Queue / Resume
├─ Approval / Artifact
├─ Provider / Extension availability
└─ canonical event stream
            │
            ▼
Agent Worker / Harness
├─ Provider adapters
├─ Plugin / Skill / MCP
└─ Tool execution
```

이 구조는 Lumina의 Frontend·Backend·Agent Worker 경계를 유지합니다. Frontend가 바뀌거나 사용자가 다른 Agent 화면으로 이동해도 Backend Run은 계속되고, 재접속 시 같은 상태를 복원해야 합니다.

## 단계별 제안

### 1단계: 범용 UI를 첫 번째 교체형 Frontend로 만들기

- 범용 Agent를 Agent Registry의 기본 Agent로 등록
- 일반 채팅 화면을 `GeneralChatFrontend` module로 격리
- Backend 접근을 공통 typed client로 이동
- conversation에 `agent_id`와 `agent_version` 저장
- Run 시작 시 Agent와 extension 구성을 snapshot으로 고정
- Frontend가 Agent 목록과 module entry를 Backend manifest에서 조회
- 알 수 없는 module은 범용 채팅으로 안전하게 fallback

이 단계에서는 특수목적 Agent나 두 번째 UI를 만들 필요가 없습니다.

### 2단계: 두 번째 내부 Frontend로 교체 가능성 검증

- 실제 업무 Agent가 아닌 작은 개발용 reference Frontend 사용
- 같은 conversation, Run, approval과 artifact를 두 Frontend에서 복원
- Frontend를 바꿔도 진행 중인 Backend Run이 중단되지 않는지 검증
- Backend에 화면별 조건문을 추가하지 않고 연결되는지 검증

### 3단계: 설치형 Agent package

- Agent manifest, Frontend bundle과 extension binding의 설치·활성·삭제 모델 추가
- required와 optional dependency 구분
- package version, 권한과 호환 contract 검증
- 사용자가 Agent를 클릭해 Frontend를 수동 선택하는 흐름을 기본으로 제공

### 4단계: 추천·자동 전환과 외부 UI

- 사용자 질문에 맞는 Agent 추천
- 사용자 확인 후 해당 Frontend에서 초기 입력값을 채워 실행
- 명시적으로 허용된 경우에만 자동 전환
- 필요할 때 A2UI, MCP Apps 또는 remote/sandbox Frontend adapter 검토

## 반드시 피할 설계

### Agent가 매번 전체 UI 코드를 자유 생성

속도, 보안, 접근성, 브랜드 일관성, 테스트와 재현성이 모두 나빠집니다. Prototype artifact에는 가능하지만 제품의 주 UI 전환 방식으로는 부적합합니다.

### Agent Frontend마다 Agent Loop를 별도 구현

목적별 UI가 Run, queue, approval, reconnect를 각자 구현하면 곧 동작이 갈라집니다. Canonical event와 action 계약은 하나여야 합니다.

### Frontend 전환이 Run 설정을 암묵적으로 변경

Frontend 전환과 Provider·Model·Tool permission 변경을 암묵적으로 묶지 않습니다. Agent를 선택해 새 Run을 시작할 때만 해당 Agent Definition을 snapshot으로 고정하며, 진행 중인 Run은 화면 전환 때문에 바뀌지 않습니다.

### 브라우저 저장소만으로 Agent와 Frontend를 기억

Lumina의 기존 원칙과 동일하게 서버 DB를 원본으로 사용해야 합니다. 공유 모드에서는 공용 Agent 선택과 개인 display preference를 구분해야 합니다.

## 핵심 데이터 모델 후보

```text
agents
  id, version, name, manifest_json, enabled, is_default

conversations
  ..., agent_id, agent_version

agent_runs
  ..., agent_snapshot_json, frontend_contract_version

agent_frontend_state
  conversation_id, agent_id, frontend_state_json
```

저장 범위는 최소 다음을 구분해야 합니다.

- 사용자 또는 공유 작업공간의 기본 Agent
- 특정 conversation에 연결된 Agent와 version
- Agent Frontend 내부의 비민감 view state
- Run 시작 시 고정된 Agent와 extension snapshot

진행 중 Run의 Provider·Model·Tool·Agent snapshot과 현재 Frontend view state는 별도 객체로 유지합니다.

## PoC 성공 기준

1. 범용 채팅 UI가 공통 Frontend SDK와 Backend contract만으로 동작합니다.
2. Backend API와 event schema에 React component 또는 화면 배치가 포함되지 않습니다.
3. 같은 conversation과 Run을 다른 reference Frontend에서도 복원할 수 있습니다.
4. Frontend를 전환해도 실행 중인 Backend Run이 중단되지 않습니다.
5. 같은 Tool Call을 Frontend별로 다르게 렌더링해도 Tool Call과 Result ID는 동일합니다.
6. 승인·취소·재개는 어느 Frontend에서도 동일한 Backend 권한 검사를 통과합니다.
7. 알 수 없는 Agent module 또는 호환되지 않는 contract는 안전한 기본 화면으로 fallback합니다.
8. 새 Frontend 연결을 위해 Backend에 해당 화면 전용 business logic을 추가하지 않아도 됩니다.

## 결론

이 아이디어는 단순한 테마, layout 또는 패널 전환이 아닙니다. Lumina를 “하나의 채팅 Frontend에 결합된 Agent”가 아니라 **동일한 Backend와 Agent Runtime에 여러 업무용 Frontend를 교체해 연결할 수 있는 플랫폼**으로 만드는 방향입니다.

가장 현실적인 출발점은 다음입니다.

> 범용 채팅 UI부터 고정된 유일한 화면이 아니라, 공통 Backend 계약에 연결된 첫 번째 교체형 Agent Frontend로 구현합니다.

이 기반이 마련되면 향후 Agent package가 전용 Frontend, Instructions, Plugins, Skills와 MCP를 함께 제공할 수 있습니다. 사용자 선택을 기본으로 하고, 질문에 따른 Agent 추천과 UI 자동 전환은 그 위에 추가합니다. 외부 전문 UI가 필요해질 때 A2UI 또는 MCP Apps를 별도 adapter와 sandbox 경로로 검토합니다.

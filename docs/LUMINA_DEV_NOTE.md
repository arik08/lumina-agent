# Lumina Agent 개발 노트

> 생성일: 2026-07-15
> 분석 기준: Git 커밋 `c23871e`까지의 144개 커밋 (`2026-07-11`~`2026-07-15`)

이 문서는 Lumina Agent의 로컬 Git 커밋 기록을 바탕으로, 무엇이 새로 추가되고 어떻게 바뀌었는지를 날짜별로 정리한 개발 노트입니다. 비개발자도 제품의 변화 흐름을 이해할 수 있도록 작은 문구·간격·테스트 수정은 관련 기능 아래에 묶고, 실제 사용 방식이나 운영 안정성을 바꾼 내용은 별도로 드러냈습니다.

현재 작업 트리에 남아 있는 미커밋 변경은 분석에서 제외했습니다. 따라서 이 문서는 위 기준 커밋 시점의 확정된 이력만 설명합니다.

## 전체 변화 요약

5일 동안 Lumina는 설계 문서와 빈 디렉터리 중심의 골격에서 출발해, 브라우저에서 여러 사용자가 대화·파일·Artifact·Skill·MCP·예약 작업을 다루는 실행 가능한 Agent 서비스로 확장되었습니다.

- Git 기준 727개 파일이 관리되고 있으며, 최초 골격 이후 749개 파일에 걸쳐 약 20만 줄이 추가되었습니다.
- React·TypeScript Frontend와 FastAPI·SQLite Backend, Agent Worker 경계를 갖춘 제품 구조가 만들어졌습니다.
- 로그인, Organization·Project·Session·Run 계층, 프로젝트 공유와 권한, 장시간 Run 복구, Queue와 event replay가 구현되었습니다.
- Codex, OpenAI, Anthropic, Gemini, OpenAI Compatible, P-GPT와 Mock Provider를 연결하는 실행 기반이 들어왔습니다.
- 파일·첨부·Artifact 생성과 검증, Memory, 지침 계층, Skill·MCP Marketplace, 예약 작업과 알림이 제품 화면으로 연결되었습니다.
- Alembic migration은 기준 커밋에서 `0026`까지 확장되었고, Backend·Frontend 회귀 테스트와 설치·진단 도구가 함께 보강되었습니다.
- 저장소에는 17개의 Skill 진입점과 13개의 MCP manifest가 포함되어 문서·검색·데이터·시각 결과물 작업을 확장할 수 있게 되었습니다.

## 2026-07-11 — 제품 골격과 개발 기준 수립

Lumina Agent 저장소의 첫 구조가 만들어진 날입니다. 아직 완성된 화면이나 실행 기능보다, 어떤 경계로 제품을 만들 것인지와 이후 코드를 어디에 둘지를 먼저 고정했습니다.

- Frontend, Backend, Provider, Extension, Infra, Test와 문서 영역을 분리한 monorepo 골격을 만들었습니다.
- `Organization → Project → Session → Run`을 중심으로 한 제품 방향과 Agent 실행, 인증, 공유, Artifact, Marketplace의 설계 문서를 추가했습니다.
- Windows·Linux 양쪽에서 개발할 수 있는 기본 경로와 저장소 규칙을 마련했습니다.
- CodeGraph가 아직 읽을 소스가 없는 초기 저장소에서도 갱신 작업이 실패하지 않도록 처리했습니다.
- 실제 파일이 들어온 디렉터리의 임시 `.gitkeep` 파일을 제거해 골격을 정리했습니다.

## 2026-07-12 — 실행 가능한 Lumina의 첫 통합 버전

설계 골격에 실제 Backend, Frontend, 데이터 모델, 확장 기능과 테스트가 한꺼번에 연결되면서 Lumina가 처음으로 실행 가능한 제품 형태를 갖췄습니다.

- React·TypeScript 기반 웹 앱과 FastAPI 기반 API 서버를 추가하고, 로그인부터 대화 실행까지의 기본 흐름을 연결했습니다.
- 사용자, 조직, 프로젝트, 대화, 메시지, Run, Tool 실행, 승인과 감사 기록을 SQLite에 저장하는 핵심 데이터 모델을 만들었습니다.
- 같은 Session의 Run은 하나만 실행하고 추가 요청은 Queue에 두며, 다른 Session은 병렬 실행할 수 있는 Agent Loop 기반을 추가했습니다.
- 브라우저 연결이 끊기거나 화면을 이동해도 Run을 Backend가 계속 소유하고, 재접속 시 snapshot과 event replay로 상태를 복원하도록 했습니다.
- Codex, OpenAI, Anthropic, Gemini, OpenAI Compatible, P-GPT와 테스트용 Mock Provider adapter를 추가했습니다.
- Provider·Model·Effort 선택과 관리자용 Provider catalog, credential 상태 확인, 모델 후보 갱신의 기본 구조를 만들었습니다.
- 프로젝트 파일과 대화 첨부를 읽고 Context에 넣을 수 있게 했으며 TXT, Markdown, HTML, CSV, PDF와 Office 문서 추출 기반을 추가했습니다.
- 답변과 결과물을 HTML, Markdown, DOCX, XLSX, PPTX, PDF Artifact로 만들고 저장·미리보기·다운로드·버전 복원할 수 있게 했습니다.
- 생성 파일의 signature, OpenXML, 외부 링크, 페이지 구조를 검사하고 LibreOffice·Poppler가 있을 때 실제 렌더까지 검증하는 안전장치를 마련했습니다.
- 개인·프로젝트 Memory와 조직·프로젝트·사용자 지침 계층, Context 압축과 학습 흐름을 추가했습니다.
- Skill WorkingDraft, immutable version, 설치·게시·권한과 MCP catalog·runtime·allowlist의 기본 Marketplace 기능을 구현했습니다.
- 반복 예약 작업, 재시도, 완료 Artifact 동기화와 앱 내부 알림을 추가했습니다.
- 대화 공유 링크, 메시지 반응, 대화 검색·분기·내보내기와 프로젝트 구성원 관리 기반을 넣었습니다.
- Web Search·Fetch와 인용 처리에 URL 제한, private IP 차단, redirect·DNS rebinding 방어를 적용했습니다.
- 회사 CA와 P-GPT, 설치 검증, health endpoint, 진단 CLI, PostgreSQL 호환성 검사 등 사내 환경용 운영 기반을 추가했습니다.
- 일반 문서 RAG와 개발 계정 로그인 도우미의 후속 설계를 별도 문서로 정리했습니다.

## 2026-07-13 — 업무 흐름 확장과 UI 체계화

전날 들어온 큰 제품 기반을 실제로 계속 사용할 수 있도록 실행 흐름, 협업, 관리자 설정과 화면 상호작용을 정리한 날입니다.

- Agent Runtime과 제품 workflow를 확장하고 Backend·Frontend 테스트와 상세 설계 문서를 현재 구현에 맞게 동기화했습니다.
- 계정 기반 프로젝트 공유와 구성원 권한 관리를 추가해 개인 작업공간을 넘어 협업 프로젝트를 운영할 수 있게 했습니다.
- 답변 시점에서 새 대화를 분기하고, 이전 질문으로 빠르게 이동하는 대화 내비게이터를 추가했습니다.
- 답변을 Markdown Artifact로 저장하고 Artifact 생성량·완료 기록을 보존하도록 했습니다.
- 좋아요·싫어요 평가 토글과 시각 피드백을 추가하고, 저장·비용·메타정보 액션을 한 줄에서 읽기 쉽게 정리했습니다.
- LLM이 문맥에 맞는 Skill을 선택하도록 실행 흐름을 조정하고, 명시적 Memory 저장의 지연과 불필요한 토큰 사용을 줄였습니다.
- 개인 Memory는 짧은 한국어 한 문장으로 정리되게 해 목록 가독성을 높였습니다.
- Worker 재시작 중 같은 Run이 다시 중단되는 문제를 막고 Codex Tool 인자 복구와 OAuth 오류 오분류를 보완했습니다.
- Provider 식별자·기본 endpoint, 모델 catalog, 공용 정책, 문서 한도와 Skill 파일 정책의 단일 원본을 정리해 설정 불일치를 줄였습니다.
- Run 안전 한도와 비상 제어를 관리자 설정으로 옮기고, 분 단위 트래픽 그래프로 운영 상태를 볼 수 있게 했습니다.
- 공용 선택 메뉴를 만든 뒤 Project, Memory 등 여러 화면에 적용해 브라우저 기본 select의 모양과 동작 차이를 없앴습니다.
- Tooltip을 `document.body`의 공용 레이어로 통합하고 화면 위쪽·스크롤 경계에서는 위치가 자동 전환되도록 했습니다.
- 메뉴 배경, scrollbar, 채팅·패널 motion, 정지 버튼과 프로젝트 권한 메뉴를 공용 디자인 기준에 맞춰 다듬었습니다.
- 개발 종료 시 검증과 로컬 체크포인트 커밋을 남기는 저장소 작업 규칙을 추가했습니다.

## 2026-07-14 — 파일·Artifact·확장 기능 완성과 실행 신뢰성 강화

사용자가 자주 만나는 파일, Artifact, Marketplace와 관리자 화면을 크게 확장하는 동시에, 장시간 Run과 설치 환경에서 생길 수 있는 실패를 집중적으로 줄였습니다.

### 파일과 업무 도구

- 프로젝트 파일의 폴더 생성·이동·탐색을 추가하고 파일 도구 모음의 순서와 새로고침 위치를 실제 작업 흐름에 맞게 바꿨습니다.
- 빈 파일도 업로드할 수 있게 하고, Composer에서 선택한 파일·폴더·Artifact가 Backend 검증을 거쳐 Context에 연결되도록 보강했습니다.
- 제품 안에서 기능 설명을 찾을 수 있는 도움말 화면과 관련 API·DB migration을 추가했습니다.
- 예약 작업과 파일 작업의 주요 버튼을 목록 가까이 옮겨 현재 대상을 보면서 바로 실행할 수 있게 했습니다.

### Artifact와 보고서

- Artifact Library에 유형·상태 필터와 정렬을 추가하고 version 선택 표시를 복구했습니다.
- 채팅과 Artifact 사이의 분할선을 직접 조절할 수 있게 하고, 최소 폭·닫기 버튼·여백·필터 표시를 다듬었습니다.
- 보고서 목표 분량, 실제 생성 Token과 경과 시간을 분리해 표시하고 슬라이더 입력과 완료 기록을 바로잡았습니다.
- HTML Preview의 각주 표시를 실제 문서 표현과 맞추고, 출처가 0건인 빈 영역은 숨겼습니다.
- 채팅과 Artifact에서 `Ctrl+A`가 앱 전체가 아니라 현재 작업 영역만 선택하도록 범위를 제한했습니다.

### Skill과 MCP

- Marketplace의 Skill·MCP 목록을 한 줄 중심으로 줄이고 아이콘 색, 범위, 초안 상태와 설명을 더 빠르게 읽을 수 있게 했습니다.
- MCP 연결 UI와 실제 Skill 삭제를 추가하고, 삭제된 Skill을 보관함에서 복원할 수 있게 했습니다.
- 중복 Skill 요약과 불필요한 목록 정보를 줄여 실제 설치·관리 action에 집중하도록 했습니다.

### Agent 실행과 Provider

- P-GPT adapter와 MCP 실행 경로를 정리하고 반복 요청의 stable prefix를 유지해 prompt cache 효율을 높였습니다.
- 초기 모델 응답이 늦을 때 Worker 소유권이 충돌하는 문제를 막고 실행 시간 표시를 정확히 했습니다.
- 채팅 Context 압축과 응답 연속성을 보강해 긴 대화에서 이전 요구가 갑자기 끊기는 문제를 줄였습니다.
- MyHarness에서 확인한 교훈을 반영해 Agent 지침 합성, 외부 Provider payload와 런처 복구를 강화했습니다.
- 조직·프로젝트·사용자 지침이 최종 prompt에 어떤 순서로 합성되는지 관리자 화면에서 확인하고 override할 수 있게 했습니다.

### 설치와 운영 안정성

- Windows 설치기에 `uv` 자동 설치 bootstrap을 추가하고 Node·Python·회사 인증서 진단을 강화했습니다.
- public CA와 회사 CA를 결합한 Trust 경로를 시작 단계에서 일관되게 사용하고, 진단 상태를 기록하도록 했습니다.
- 개발 Runtime의 준비 순서를 보정하고 Backend 시작·health 확인·복구 동작을 안정화했습니다.
- CodeGraph 상태와 DB 수정 시각을 확인해 필요할 때 재색인하는 복구 절차와 스크립트를 보강했습니다.
- 환경 이식성, Runtime 신뢰성, 설치와 Trust 진단 기준을 별도 문서로 정리했습니다.

### 화면 사용성

- 세션별 채팅 스크롤 위치를 기억해 다른 대화에 다녀와도 읽던 위치로 돌아오게 했습니다.
- Composer 입력 여백·정렬, sidebar 빈 영역 toggle, Session 관리 제목 위치와 공용 scrollbar 동작을 정리했습니다.
- Cache rate는 구간별 색으로 구분하고 반복 Tool 아이콘은 과도하게 강조되지 않도록 조정했습니다.
- Project 구성원 관리와 주요 화면을 공용 디자인 token·component 기준에 맞췄습니다.

## 2026-07-15 — 복구 자동화, 관리자 제어와 인터랙티브 응답 강화

장시간 실행과 운영 관리를 더 믿을 수 있게 만들고, 응답·Skill·예약 작업을 실제 사용 맥락에 맞게 다듬은 날입니다.

### Agent와 Memory

- 별도 후처리 호출에 의존하던 Memory 추출을 본 응답의 LLM 구조화 출력에 통합해 지연과 추가 호출을 줄였습니다.
- “기억해 줘” 같은 Memory 요청을 파일 생성 요청으로 잘못 판단하지 않도록 실행 지침과 회귀 테스트를 보완했습니다.
- 파일 모드는 강제 출력 규칙이 아니라 LLM의 출력 선호로 완화하고, 일반 대화가 파일 작업으로 오인될 때 Composer에 경고를 표시하도록 했습니다.
- 오래 남은 유령 Run을 Frontend가 Backend 상태와 대조해 자동 정리하고, 연결 상태 표시가 실제 readiness와 일치하도록 수정했습니다.

### 운영과 관리자 기능

- Lumina 실행기가 일시적 Backend 장애 뒤에도 감시를 멈추지 않고 재시작 간격을 조절하며 자동 복구하도록 했습니다.
- 개발 런처의 종료·hard reset 입력 처리와 오래된 DB schema 복구를 개선했습니다.
- 모니터링 그래프에 시간 범위 선택, 비정상 event와 발생 시각 표시를 추가했습니다.
- 관리자 설정에서 실제 Context 예산과 사용 비율 계약을 볼 수 있게 했습니다.
- 관리자가 특정 모델을 관리자 전용으로 제한할 수 있게 하고 Codex 모델의 표시 순서를 조정했습니다.
- 에이전트별 격리 QA port, 사용자 화면 보호, 브라우저 process와 점검 산출물 정리 규칙을 저장소 지침에 추가했습니다.

### 예약 작업과 확장 기능

- 예약 실행에서 Provider·Model·Effort·실행 설정을 고를 수 있게 하고 주기 선택 UI를 더 촘촘하게 배치했습니다.
- 예약 실행 직후 최근 실행 목록이 즉시 갱신되도록 했습니다.
- `extensions/` 폴더 변경을 자동 감지하고 Marketplace 새로고침 시 Skill을 다시 탐색하도록 했습니다.
- Skill Markdown의 frontmatter와 본문 Preview를 분리하고 trigger 미리보기와 확대 toggle을 추가했습니다.
- Draft·version 표기가 화면마다 다르던 문제를 정리하고, 일반 목록에서는 불필요한 version 문자열을 숨겼습니다.

### 채팅과 시각 결과물

- Agent 응답 안에 인터랙티브 chart를 렌더링하는 기능을 추가했습니다.
- Mermaid diagram을 채팅에서 바로 보고 확대할 수 있게 했습니다.
- 표준 Markdown 응답과 인터랙티브 콘텐츠가 같은 Conversation Turn 안에서 안전하게 공존하도록 renderer와 스타일을 분리했습니다.
- 경고 메시지의 색·간격·표현을 디자인 시스템 기준으로 통일했습니다.

## 현재 제품에서 할 수 있는 일

- 프로젝트별로 대화를 만들고 여러 Provider·Model·Effort를 선택해 장시간 Agent Run을 실행할 수 있습니다.
- 다른 Session으로 이동하거나 브라우저 연결이 끊겨도 실행은 계속되며, 돌아오면 진행 상태가 복원됩니다.
- Project 파일, 첨부와 Artifact를 Context에 연결하고 결과를 HTML·Markdown·Office·PDF로 저장·검증할 수 있습니다.
- 개인·Project Memory와 조직·Project·사용자 지침을 관리하고 실제 prompt 합성 구조를 확인할 수 있습니다.
- Skill과 MCP를 탐색·설치·초안 편집·version 저장하고 예약 Run에도 고정해 사용할 수 있습니다.
- 프로젝트 구성원과 권한, 읽기 전용 대화 공유, 알림, 예약 작업과 관리자 운영 설정을 한 서비스에서 관리할 수 있습니다.
- 회사 CA, P-GPT와 여러 외부 Provider를 동일한 실행 경계 안에서 사용하고 설치·연결·Runtime 상태를 진단할 수 있습니다.

## 문서 갱신 기준

이 파일을 다음에 갱신할 때는 마지막 분석 기준 커밋 이후의 이력만 추가로 검토합니다. 커밋 제목만 옮기지 않고 실제 diff와 관련 설계 문서를 함께 확인하며, 아직 커밋되지 않은 변경과 계획 단계의 기능은 완료된 기능처럼 기록하지 않습니다.

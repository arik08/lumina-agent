# Lumina Agent

Lumina Agent는 Harness를 기반으로 AI의 실행 과정을 관리하고, Plugins, Skills, MCP를 통해 기능을 확장할 수 있는 다중 사용자용 사내 AI Agent 서버 프로젝트입니다.

## 핵심 컨셉

- React와 TypeScript로 채팅 UI를 구성합니다.
- Python으로 API, Agent, Harness 및 도구 실행 환경을 구성합니다.
- 여러 사용자가 서버에 접속해 자신의 대화와 파일을 안전하게 관리할 수 있어야 합니다.
- Harness가 Agent 실행, 재시도, 추적 및 도구 호출 흐름을 관리합니다.
- Plugins, Skills, MCP를 독립적인 확장 자원으로 관리합니다.
- Codex, OpenAI, OpenAI Compatible, P-GPT, Claude 및 Gemini Provider를 선택할 수 있어야 합니다.
- 회사 인증서(`.crt`)를 적용해 사내 환경에서도 웹 검색과 외부 HTTPS 요청이 가능해야 합니다.
- 채팅 기록과 관련 파일은 세션 단위의 폴더로 묶어 보관합니다.
- 제품의 방향과 제작 기준은 별도의 프로젝트 컨텍스트 문서로 관리합니다.

## 주요 폴더

```text
lumina-agent/
├─ .agents/                  # 프로젝트용 AI Agent 설정과 지침
├─ .codex/                   # Codex 프로젝트 설정
├─ .examples/                # Coding Agent용 외부 프로그램 참고 자료
├─ .codegraph/               # 로컬 CodeGraph 인덱스, Git 제외
├─ .git/                     # Git 저장소 내부 데이터
├─ apps/
│  ├─ web/                    # React + TypeScript UI
│  └─ server/                 # Python API 및 Agent 런타임
├─ data/
│  ├─ database/               # 개발용 SQLite
│  ├─ sessions/               # 대화 내보내기와 세션 재현
│  ├─ files/                  # 첨부 파일과 생성 결과물
│  ├─ certs/                  # 로컬 회사 인증서
│  ├─ users/                  # 사용자별 런타임 작업공간
│  └─ shared/                 # 공유 모드의 공용 artifacts
├─ docs/
│  └─ project-context/        # 제품 컨셉과 제작 기준 문서
│     └─ decisions/           # 주요 설계 결정 기록
├─ extensions/
│  ├─ plugins/                # 복합 확장 기능
│  ├─ skills/                 # Agent 업무 절차와 지침
│  └─ mcp/                    # MCP 서버 및 연결 자원
├─ infra/                     # 컨테이너와 Kubernetes 배포 환경
├─ devtools/                  # 개발·검증·유지보수 자동화 도구
├─ tests/
│  ├─ backend/                # 백엔드 테스트
│  ├─ frontend/               # 프런트엔드 테스트
│  ├─ e2e/                    # 전체 사용자 흐름
│  └─ evals/                  # Agent 품질 평가
├─ installer.bat              # Windows 설치 및 초기 설정
├─ run_lumina.bat             # Windows 운영 모드 실행
├─ run_lumina_dev.bat         # Windows 개발 모드 실행
├─ AGENTS.md                  # 프로젝트 전체 Coding Agent 규칙
└─ README.md                  # 프로젝트 개요와 설계 원칙
```

### 최상단 항목별 용도

| 항목 | 용도 |
|---|---|
| `.agents/` | 이 프로젝트에서 사용하는 AI Agent의 작업 규칙, 역할, 프로젝트 전용 설정을 둡니다. 실제 사용자 채팅이나 모델 API 키를 저장하지 않습니다. |
| `.codex/` | Codex가 프로젝트에서 사용할 설정, MCP 연결 및 프로젝트 단위 동작 옵션을 두는 예약 공간입니다. 사용자별 비밀값은 저장소에 커밋하지 않습니다. |
| `.examples/` | Lumina Agent를 설계·구현할 때 Coding Agent가 참고할 외부 프로그램을 둡니다. Lumina Agent의 소스 코드나 실행 구성요소가 아닙니다. |
| `.codegraph/` | Coding Agent가 코드 관계, 호출자와 변경 영향을 빠르게 조회하기 위한 로컬 인덱스입니다. 생성 데이터이므로 Git에 커밋하지 않습니다. |
| `.git/` | Git이 커밋, 브랜치, 태그 및 변경 이력을 관리하기 위해 자동으로 사용하는 내부 폴더입니다. 사람이 직접 수정하지 않습니다. |
| `AGENTS.md` | Lumina Agent를 수정하는 Coding Agent가 따라야 할 프로젝트 전체 규칙과 아키텍처 경계를 정의합니다. |
| `apps/` | 실제로 실행되는 애플리케이션을 둡니다. `web/`은 React 프런트엔드, `server/`는 FastAPI와 Agent 백엔드입니다. 두 앱은 독립적으로 실행·배포할 수 있게 유지합니다. |
| `data/` | 프로그램 버전과 분리해야 하는 SQLite, 세션 내보내기, 파일과 로컬 인증서를 둡니다. 운영 비밀값과 실제 데이터는 Git에 커밋하지 않습니다. |
| `docs/` | 프로젝트 관련 문서를 모읍니다. `project-context/`에는 제품 목적, 요구사항과 제작 기준을, `decisions/`에는 중요한 설계 결정과 결정 이유를 기록합니다. |
| `extensions/` | 코드 수정 없이 Agent 기능을 확장할 수 있는 자원을 둡니다. Plugin은 복합 확장 패키지, Skill은 작업 절차, MCP는 외부 도구 서버 연결을 담당합니다. |
| `infra/` | Podman Compose, 컨테이너 이미지, Reverse Proxy 및 향후 Kubernetes 배포 설정을 둡니다. 애플리케이션 비즈니스 로직은 넣지 않습니다. |
| `devtools/` | CodeGraph 갱신, 환경 검증, DB 마이그레이션·백업과 릴리스 준비처럼 개발자·운영자·Coding Agent가 사용하는 자동화 도구를 둡니다. 제품 런타임 코드와 구분합니다. |
| `tests/` | 백엔드, 프런트엔드, E2E 테스트와 Agent 품질 평가를 단순한 네 영역으로 나누어 관리합니다. |
| `installer.bat` | Windows에서 필요한 도구 확인, 의존성 설치, 개발용 데이터 폴더 준비와 초기 설정을 수행할 최상단 설치 진입점입니다. |
| `run_lumina.bat` | 사용자가 하나의 Lumina Agent 서비스로 접속할 수 있도록 운영 설정으로 Frontend, Backend와 필요한 내부 작업을 시작할 최상단 실행 진입점입니다. |
| `run_lumina_dev.bat` | React 개발 서버와 FastAPI 개발 서버를 개발 설정과 자동 재시작 모드로 함께 실행할 최상단 개발 진입점입니다. |
| `README.md` | 프로젝트의 핵심 컨셉, 폴더 구조, 개발·운영 원칙과 향후 확장 방향을 설명하는 첫 진입 문서입니다. |

## 참고 프로그램

`.examples/`는 Coding Agent가 다른 프로그램의 구조와 구현 방식을 살펴보기 위한 참고 자료 전용 폴더입니다.

Coding Agent는 이 폴더를 확인하기 전에 `.examples/AGENTS.md`의 참고 전용 규칙을 따릅니다.

- Lumina Agent의 구성요소가 아닙니다.
- 앱의 import 및 런타임 의존성으로 사용하지 않습니다.
- 빌드, 실행, 테스트, 패키징 및 배포 대상에 포함하지 않습니다.
- `.examples/` 안의 프로그램을 직접 수정해 Lumina Agent 기능을 구현하지 않습니다.
- 참고한 코드를 그대로 복사하지 않고 라이선스와 저작권을 확인한 뒤 필요한 아이디어만 독립적으로 구현합니다.
- Lumina Agent에서 실제로 사용하는 코드는 `apps/`, `extensions/` 또는 적절한 프로젝트 폴더에 별도로 작성합니다.

Coding Agent는 `.examples/`의 내용과 현재 프로젝트 요구사항이 충돌할 경우 README와 `docs/project-context/`의 기준을 우선합니다.

## 사용자별 Agent 지침

루트 `AGENTS.md`는 프로젝트를 개발하는 Coding Agent의 공통 규칙입니다. 서비스 사용자가 설정하는 개인 지침은 이 파일과 분리합니다.

사용자별 Agent 지침의 원본은 개발 단계에서는 SQLite, 운영 단계에서는 PostgreSQL에 사용자 설정으로 저장합니다. 사용자가 Agent 세션을 시작하면 Backend가 허용된 설정만 검증하여 격리된 런타임 작업공간에 다음과 같이 생성할 수 있습니다.

```text
data/users/{user_id}/
└─ AGENTS.md                  # 해당 사용자의 런타임 지침
```

- 로그인만으로 파일을 매번 덮어쓰지 않고, 최초 사용자 생성 또는 지침 변경 시 갱신합니다.
- 사용자가 다른 사용자의 지침이나 작업공간을 읽을 수 없게 소유권을 검사합니다.
- 파일명에 사용자 입력을 직접 사용하지 않고 서버가 발급한 UUID를 사용합니다.
- 사용자 지침은 시스템 보안 정책, 조직 정책과 프로젝트 공통 규칙을 무시할 수 없습니다.
- API 키, 토큰, 인증서 및 비밀번호를 사용자 `AGENTS.md`에 기록하지 않습니다.
- Kubernetes 또는 다중 Backend 환경에서는 로컬 파일을 원본으로 사용하지 않고 DB의 지침을 각 실행 작업공간에 임시로 materialize합니다.

지침 적용 우선순위는 다음과 같습니다.

```text
시스템 보안 정책
→ 조직 정책
→ Agent 기본 정책
→ 사용자별 AGENTS.md
→ 현재 대화 요청
```

## 사용자 데이터 공유 모드

Lumina Agent는 사용자 데이터 공개 범위를 설정으로 선택할 수 있어야 합니다.

```text
private   → 사용자마다 채팅 내역과 artifacts를 분리
shared    → 모든 접속 사용자가 채팅 내역과 artifacts를 공유
```

기본값은 `private`입니다. 개발 또는 공동 디버깅 환경에서는 관리자가 `shared` 모드를 명시적으로 활성화할 수 있습니다.

```text
LUMINA_SHARING_MODE=private
LUMINA_SHARING_MODE=shared
```

공유 모드에서는 다음 데이터가 모든 인증된 사용자에게 표시됩니다.

- 채팅방 목록과 메시지
- Agent 실행 상태와 결과
- Tool 및 MCP 호출 결과 중 공개 가능한 정보
- 생성된 문서, 이미지와 기타 artifacts
- 공유 대화에 첨부된 파일

다음 데이터는 공유 모드에서도 공유하지 않습니다.

- 비밀번호, API 키, 인증 토큰과 인증서
- Provider Secret과 P-GPT 인증 정보
- 사용자별 `AGENTS.md`, 개인 계정 정보와 채팅 실행에 영향을 주지 않는 개인 UI 설정
- 관리자 전용 설정과 보안 감사 정보

공유 모드가 활성화되면 UI 상단과 채팅 입력 영역에 현재 대화와 artifacts가 모든 사용자에게 공개된다는 표시를 지속적으로 노출합니다. 관리자가 아닌 일반 사용자가 이 설정을 변경할 수 없게 합니다.

개발용 SQLite에서는 공유 대화에 `visibility=shared`를 기록하고 공유 artifacts를 `data/shared/artifacts/`에 저장할 수 있습니다. 운영 PostgreSQL에서는 동일한 공개 범위를 DB 필드와 권한 검사로 관리하며, 서버의 로컬 폴더를 공유 상태의 원본으로 사용하지 않습니다.

공유 모드를 끄더라도 기존 공유 데이터를 임의로 개인 데이터로 변경하거나 삭제하지 않습니다. 관리자가 기존 공유 데이터의 보관, 이전 또는 삭제 방법을 선택하게 합니다. 모든 생성·수정·삭제 기록에는 실제 작업 사용자 ID를 남깁니다.

## 사용자 옵션 기억

사용자가 변경할 수 있는 일반 옵션은 마지막 선택값을 저장하고 다음 접속이나 새 채팅에서 기본값으로 복원합니다. 저장 범위는 채팅 세션 공유 모드에 따라 달라집니다. 이 동작은 Provider, Model, Effort뿐 아니라 앞으로 추가되는 옵션의 기본 설계 원칙입니다.

```text
개인 모드에서 옵션 선택
→ Backend가 사용자 설정에 저장
→ 해당 사용자에게만 다음 기본값으로 복원

공유 모드에서 옵션 선택
→ Backend가 공유 작업공간 설정에 저장
→ 모든 사용자에게 동일한 기본값으로 복원
```

대표적인 사용자 설정은 다음과 같습니다.

- 마지막 Provider
- Provider별 마지막 Model
- Provider·Model별 마지막 Effort
- 마지막 Agent 또는 작업 모드
- 응답 표시와 UI 옵션
- 사용자가 직접 선택하는 Tool, Skill 및 MCP 활성화 옵션

예를 들어 사용자가 P-GPT의 특정 모델과 `high` Effort를 선택했다면 다음 새 채팅에서도 해당 조합을 기본으로 표시합니다. 이후 OpenAI Provider에서 다른 모델을 선택하더라도 P-GPT의 마지막 모델 선택은 별도로 유지할 수 있어야 합니다.

설정 원본은 브라우저 `localStorage`가 아니라 서버 DB입니다. 개인 모드에서는 사용자 설정에, 공유 모드에서는 공유 작업공간 설정에 저장합니다. 따라서 다른 PC에서 접속해도 해당 모드에 맞는 설정을 사용할 수 있습니다. `localStorage`는 로그인 전 UI 상태나 일시적인 캐시에만 사용할 수 있습니다.

설정 적용 우선순위는 다음과 같습니다.

```text
시스템 강제 정책
→ 조직 관리자 정책
→ 사용자 마지막 선택값
→ 애플리케이션 기본값
```

저장된 Provider나 Model이 삭제되었거나 조직 정책상 사용할 수 없게 된 경우에는 허용된 기본값으로 fallback하고 사용자에게 변경 사실을 알립니다. 유효하지 않은 저장값 때문에 앱 시작이나 채팅 생성이 실패해서는 안 됩니다.

다음 값은 마지막 선택 옵션으로 자동 저장하지 않습니다.

- API 키, 비밀번호, 인증 토큰 및 인증서
- 일회성 확인과 위험 작업 승인
- 현재 실행 중인 작업의 임시 상태
- 관리자가 통제하는 전역 공유 모드와 보안 정책

### 모드별 옵션 범위

| 모드 | 저장 범위 | 동작 |
|---|---|---|
| `private` | 사용자별 설정 | Provider, Model, Effort와 기타 옵션을 사용자마다 따로 기억합니다. |
| `shared` | 공유 작업공간 설정 | 모든 사용자가 동일한 Provider, Model, Effort와 기타 채팅 실행 옵션을 사용합니다. |

공유 모드에서는 마지막으로 옵션을 변경한 사용자의 선택이 공용 기본값이 되며 연결된 다른 사용자 화면에도 반영됩니다. 동시 변경 시에는 Backend가 저장 순서를 결정하고 최종 저장값을 모든 사용자에게 다시 전파합니다. 누가 어떤 옵션을 변경했는지 감사 기록에 남깁니다.

공유되는 옵션에는 Provider, Model, Effort, Agent 모드, Tool, Skill, MCP와 채팅 실행에 영향을 주는 설정이 포함됩니다. 비밀번호, API 키, 인증 토큰, 인증서, 사용자별 `AGENTS.md`, 보안 정책과 개인 계정 정보는 공유 모드에서도 공유하지 않습니다.

개인 모드에서 공유 모드로 전환할 때 특정 사용자의 개인 옵션을 자동으로 공용 설정에 복사하지 않습니다. 기존 공용 설정이 없으면 관리자가 정한 애플리케이션 기본값으로 시작합니다. 공유 모드에서 개인 모드로 돌아갈 때도 각 사용자가 이전에 저장한 개인 옵션을 복원합니다.

## Windows 실행 파일

Windows 사용자는 최상단 배치 파일을 통해 설치와 실행을 시작합니다.

```text
installer.bat       → 최초 설치와 환경 준비
run_lumina.bat      → 일반 사용자용 서비스 실행
run_lumina_dev.bat  → 프런트엔드·백엔드 개발 서버 실행
```

배치 파일은 사용자가 기억해야 할 명령을 최소화하는 제품 진입점입니다. `devtools/`는 일반 사용자 실행이 아니라 개발·검증·유지보수를 위한 내부 도구에만 사용합니다. 향후 Linux에서는 같은 역할의 셸 스크립트나 서비스 명령을 제공할 수 있습니다.

현재는 프로젝트 구조만 준비된 상태이므로 세 배치 파일은 구현 예정임을 알리고 오류 코드로 종료합니다. 앱과 의존성 구성이 확정되면 실제 설치·실행 명령을 연결합니다.

## CodeGraph

CodeGraph는 Coding Agent가 심볼, 호출 관계, 관련 파일과 변경 영향 범위를 빠르게 조회하기 위한 로컬 코드 인덱스입니다.

```powershell
powershell -ExecutionPolicy Bypass -File devtools/update_codegraph.ps1
```

업데이트 스크립트는 다음을 자동 처리합니다.

- `uvx`를 통해 `better-code-review-graph` 실행
- 첫 인덱스에서는 전체 빌드
- 이후 실행에서는 최근 Git 변경 기준 증분 업데이트
- `.codegraph/codegraph.db` 생성 및 수정 시각 출력

CodeGraph 2.x는 변경 이력을 연결할 실제 Git HEAD를 요구하므로 최초 인덱스 전에 저장소에 첫 커밋이 있어야 합니다. `.codegraph/`는 로컬 생성 데이터이며 `.gitignore`를 통해 커밋 대상에서 제외합니다.

Coding Agent는 기존 인덱스를 재생성하기 전에 `codegraph_status`를 확인하고, 코드 작업에서는 `codegraph_context`, `codegraph_search`, `codegraph_callers`, `codegraph_callees`와 `codegraph_impact`를 실제 파일 내용과 함께 사용합니다. `.examples/`와 `data/`는 인덱스 대상에서 제외합니다.

## 테스트 구조

테스트는 최상단 `tests/`에 모읍니다.

```text
tests/
├─ backend/                   # API, Agent, Provider, DB와 보안
├─ frontend/                  # React UI
├─ e2e/                       # 실제 사용자 흐름
└─ evals/                     # Agent 응답과 수행 품질
```

## 확장 기능 구조

최상단 `extensions/`에는 Agent가 읽거나 실행할 확장 자원을 저장합니다. 백엔드의 `apps/server/src/lumina/extensions/`는 이러한 자원을 불러오고 검증하고 실행합니다.

## AI Provider 구조

모델과 코딩 에이전트 연결은 Provider 계층으로 분리합니다.

```text
apps/server/src/lumina/
└─ providers/
   ├─ codex/                  # Codex 코딩 에이전트 실행
   ├─ openai/                 # 공식 OpenAI API
   ├─ openai_compatible/      # OpenAI 호환 API
   ├─ pgpt/                   # 회사 P-GPT 전용 연결
   ├─ anthropic/              # Claude
   └─ google/                 # Gemini
```

Provider별 역할은 다음과 같습니다.

| Provider | 용도 |
|---|---|
| `codex` | 코드 작성, 수정, 명령 실행 등 Codex 기반 개발 작업 |
| `openai` | 공식 OpenAI API와 Responses API 기반 Agent 실행 |
| `openai_compatible` | OpenAI 형식과 호환되는 외부 또는 사내 API 연결 |
| `pgpt` | Azure Landing Zone 기반 회사 P-GPT 연결 |
| `anthropic` | Anthropic Claude 모델 연결 |
| `google` | Google Gemini 모델 연결 |

OpenAI의 Agent 기능은 Responses API를 우선 지원하고, 필요한 경우 Chat Completions 호환 경로를 별도로 둡니다. ChatGPT 제품 구독과 OpenAI API 인증은 동일한 것으로 가정하지 않습니다.

모든 Provider는 공통 요청과 응답 모델을 사용하되, 다음 capability를 Provider별로 선언합니다.

- 텍스트 및 스트리밍 응답
- Tool 및 Function 호출
- 구조화된 출력
- 이미지 입력
- 추론 옵션과 사용량 정보
- 서버 측 대화 상태
- 내장 웹 검색 또는 외부 도구 연동

지원하지 않는 기능을 공통 인터페이스에서 흉내 내지 않고, 실행 전에 capability를 검사하여 UI와 Harness가 사용 가능한 기능만 요청하게 합니다. 모델 이름도 코드에 고정하지 않고 Provider 설정과 관리 UI에서 선택합니다.

### P-GPT

P-GPT는 일반 `openai_compatible` 설정의 별칭으로 처리하지 않고 별도 Provider로 유지합니다. OpenAI 호환 요청 형식을 재사용하더라도 회사 환경에 필요한 차이를 독립적으로 관리합니다.

- Azure Landing Zone 기반 사내 API 엔드포인트
- 회사 CA 인증서와 TLS 검증
- 사내 인증 헤더 또는 토큰 발급 방식
- 배포명과 모델명의 매핑
- API 버전과 URL 경로 차이
- 스트리밍, Tool Call, Structured Output 및 이미지 지원 여부
- 사내 프록시, 타임아웃, 재시도와 감사용 요청 ID

P-GPT의 실제 URL, 인증 토큰 및 인증서 경로는 코드나 사용자 세션에 저장하지 않고 환경변수 또는 Secret으로 주입합니다. Provider 설정에는 비밀값 자체가 아니라 Secret 참조만 보관합니다.

```text
PGPT_BASE_URL=...
PGPT_API_VERSION=...
PGPT_AUTH_SECRET_REF=...
PGPT_CA_CERT=/run/certs/company-ca.crt
```

Provider는 시스템 기본값, 조직 기본값, 사용자 선택값 순서로 결정합니다. 관리자는 조직별로 사용할 수 있는 Provider와 모델을 제한할 수 있으며, 각 Agent 실행 기록에는 실제 Provider, 모델 또는 배포명, 사용량과 오류 정보를 남깁니다.

## Agent Loop

Lumina Agent의 Harness는 모델이 최종 답변을 반환할 때까지 모델 호출과 Tool 실행을 반복합니다.

```text
사용자 메시지
→ Provider Stream
→ 최종 답변이면 종료
→ Tool Call이면 권한 확인과 실행
→ Tool Result를 Context에 추가
→ Provider를 다시 호출
```

OpenHarness 예제에서 확인한 Agent Loop 개념을 참고하되 코드를 복사하거나 런타임 의존성으로 사용하지 않고 Lumina의 Provider 추상화와 다중 사용자 서버 구조에 맞게 독립적으로 설계합니다.

Agent Loop는 다음을 기본으로 지원해야 합니다.

- 스트리밍 텍스트와 실행 상태 이벤트
- Tool 입력 검증, 권한 확인과 실행 전후 hook
- 독립 Tool Call 병렬 실행과 개별 오류 결과 보존
- 최대 Turn, timeout, Token과 비용 제한
- 긴 Context 자동 정리와 요약
- 실행 취소, 중단 상태 저장과 안전한 재개
- 큰 Tool 출력을 artifact로 전환
- 공유 대화별 단일 실행 lock 또는 queue
- Provider별 응답을 공통 이벤트로 정규화

상세 상태, 종료 조건, 재개 방식과 이벤트 계약은 [`docs/project-context/AGENT_LOOP.md`](docs/project-context/AGENT_LOOP.md)를 기준으로 합니다.

## 다중 사용자 서버 구조

사용자에게는 하나의 Lumina Agent 서비스로 보이게 하되, 내부에서는 Frontend, API 및 장시간 실행되는 Agent 작업을 독립적으로 분리합니다.

```text
사용자 브라우저
       ↓
https://lumina.company.com
       ↓
Gateway / Reverse Proxy
       ├─ /        → React Frontend
       ├─ /api/*   → FastAPI Backend
       └─ /stream/* → SSE 또는 WebSocket
                         ↓
                     Agent Worker
                         ├─ Harness
                         ├─ Models
                         ├─ Plugins
                         ├─ Skills
                         └─ MCP

FastAPI Backend
├─ SQLite 개발 DB → PostgreSQL 운영 DB
├─ Object Storage
└─ Redis 작업 큐
```

- 사용자는 하나의 주소, 로그인, 채팅 화면과 설정 화면을 사용합니다.
- Gateway 또는 Reverse Proxy가 요청 경로에 따라 Frontend와 Backend로 전달합니다.
- React Frontend와 FastAPI Backend는 서로 독립적인 애플리케이션과 프로세스로 실행합니다.
- FastAPI는 인증, 권한 검사, 대화 API 및 작업 접수를 담당합니다.
- PostgreSQL은 사용자, 대화, 메시지, 실행 이력 및 감사 기록의 운영 원본을 저장합니다.
- Redis 작업 큐와 Agent Worker는 장시간 실행되는 Agent 작업을 처리합니다.
- SSE 또는 WebSocket을 사용해 실행 상태와 답변을 사용자에게 스트리밍합니다.
- 첨부 파일과 생성 결과물은 S3 또는 MinIO 같은 오브젝트 스토리지에 저장합니다.

초기에는 Frontend와 Backend를 같은 장비에서 명령 하나로 함께 시작할 수 있습니다. 하지만 FastAPI가 React 소스 구조에 의존하거나 React가 Backend 비밀 정보에 접근하지 않도록 경계를 유지합니다. 이후에는 설정과 배포 위치만 바꿔 Frontend 서버, Backend 서버 및 Worker 서버를 각각 분리할 수 있어야 합니다.

```text
개발
└─ 하나의 개발 명령
   ├─ React :5173
   └─ FastAPI :8000

초기 운영
└─ 한 대의 서버
   ├─ Reverse Proxy + React
   └─ FastAPI + Agent Worker

확장 운영
├─ Frontend 서버
├─ Backend 서버
├─ Agent Worker 서버
└─ PostgreSQL 및 Redis
```

Frontend는 API 주소를 환경별 공개 설정으로 주입받고 비밀값을 포함하지 않습니다. Backend는 허용 Origin, 인증 Cookie 또는 토큰 정책, 스트리밍 연결 및 API 버전 호환성을 관리합니다. 프런트엔드와 백엔드 사이의 요청·응답 타입은 OpenAPI를 기준으로 동기화합니다.

## 사용자와 권한

모든 대화, 메시지, 실행 및 첨부 파일에는 소유 사용자와 필요한 경우 조직 정보를 기록합니다.

```text
Organization
├─ Users
└─ Conversations
   ├─ Messages
   ├─ Attachments
   └─ AgentRuns
      └─ ToolCalls
```

기본 역할은 일반 사용자, 관리자, 운영자로 구분합니다. 대화와 파일을 조회하거나 변경할 때는 항상 사용자 또는 조직 소유권을 검사합니다. 여러 부서나 회사를 분리해야 할 경우 주요 데이터에 `organization_id`를 포함합니다.

사용자별 동시 실행 수, 조직별 요청량, 최대 실행 시간, 토큰 사용량, 도구 호출 횟수 및 업로드 파일 크기도 제한할 수 있어야 합니다. 동일한 대화에서 여러 요청이 발생하면 초기에는 순차적으로 실행합니다.

## 채팅 세션 저장

개발 단계의 채팅과 실행 기록은 SQLite를 원본으로 사용합니다. 운영 단계에서는 PostgreSQL로 전환합니다. `data/sessions/`는 대화 내보내기, 장애 재현 및 테스트용 세션 재생에 사용합니다.

파일 기반 세션을 만들 때는 `data/sessions/` 아래에 세션별 폴더로 저장합니다.

```text
data/sessions/{날짜}_{세션 ID}/
├─ session.json               # 세션 기본 정보
├─ messages.jsonl             # 사용자와 AI의 메시지
├─ runs.jsonl                 # Agent 실행 이력
├─ tool-calls.jsonl           # 도구 및 MCP 호출 이력
├─ attachments/               # 사용자 첨부 파일
├─ artifacts/                 # Agent 생성 결과물
└─ logs/                      # 세션 단위 로그
```

세션 폴더 하나만 복사해도 대화 기록과 관련 파일을 함께 내보내거나 재현할 수 있도록 구성합니다. 운영 서버가 여러 대일 때 로컬 세션 폴더를 운영 데이터의 원본으로 사용하지 않습니다.

## 데이터베이스 전략

초기 개발은 별도 DB 서버 설정 없이 사용할 수 있는 SQLite로 진행하고, 다중 사용자 운영 단계에서는 PostgreSQL을 사용합니다.

```text
개발
└─ data/database/lumina.db

통합 테스트
└─ SQLite 기본 테스트 + PostgreSQL 호환성 테스트

운영
└─ PostgreSQL
```

프로그램 코드와 데이터는 분리합니다. 프로그램 버전을 교체해도 `data/`는 유지하며, 애플리케이션 시작 시 필요한 DB 마이그레이션을 적용합니다.

SQLite에서 PostgreSQL로 안전하게 이전할 수 있도록 다음 원칙을 지킵니다.

- SQLAlchemy를 통해 DB에 접근합니다.
- Alembic으로 스키마 변경 이력을 관리합니다.
- 주요 ID는 UUID를 사용합니다.
- 날짜와 시간은 UTC 기준으로 저장합니다.
- SQLite 전용 SQL과 `PRAGMA` 의존을 최소화합니다.
- 원시 SQL을 서비스 코드에 직접 작성하지 않습니다.
- DB 접근은 Repository와 Service 계층으로 분리합니다.
- PostgreSQL 호환성 통합 테스트를 정기적으로 실행합니다.
- 첨부 파일 원본은 DB에 넣지 않고 별도 스토리지에 저장합니다.

DB 연결은 환경변수로 선택할 수 있게 구성합니다.

```text
# 개발
DATABASE_URL=sqlite:///./data/database/lumina.db

# 운영
DATABASE_URL=postgresql+psycopg://...
```

SQLite를 백업하거나 프로그램 버전을 교체할 때는 애플리케이션을 정상 종료한 뒤 백업 기능을 사용합니다. WAL 모드에서는 `.db-wal`, `.db-shm` 파일이 존재할 수 있으므로 실행 중인 `.db` 파일만 복사하지 않습니다.

## 운영 데이터

PostgreSQL에는 다음 데이터를 저장합니다.

- 사용자, 조직 및 조직 구성원
- 대화와 메시지
- Agent 실행과 도구 호출
- 첨부 파일 메타데이터
- 사용자 작업 감사 기록

첨부 파일 자체는 오브젝트 스토리지에 저장하고 DB에는 소유자, 원본 파일명, 스토리지 키, 형식 및 크기만 기록합니다. 파일 접근 시에도 사용자 권한을 검사합니다.

## 확장 기능 권한

Plugins, Skills, MCP는 전체 사용자에게 무조건 노출하지 않습니다. 확장 기능별로 허용 조직, 관리자 전용 여부, 외부 네트워크 접근, 파일 시스템 접근 범위, 실행 시간 및 필요한 비밀 정보를 관리합니다.

초기 버전에서는 사용자가 임의의 Plugin이나 MCP 서버를 업로드해 서버에서 실행하는 기능을 제공하지 않습니다.

## 회사 인증서

개발 환경의 회사 인증서는 `data/certs/`에 배치하고 Git에는 포함하지 않는 것을 원칙으로 합니다. Python HTTP 클라이언트, Node.js 및 웹 검색 도구가 동일한 CA 인증서를 사용할 수 있도록 실행 환경에서 인증서 경로를 설정할 예정입니다.

운영 환경에서는 인증서와 API 키, DB 비밀번호, 토큰 서명 키를 Secret Manager 또는 읽기 전용 Secret 볼륨으로 주입합니다. 개인 키나 민감한 인증서 파일은 저장소에 커밋하지 않습니다.

## 공식 개발 및 실행 환경

Windows 개발 환경에서는 Docker Desktop에 의존하지 않고 `WSL2 + Ubuntu + Podman CLI`를 기본으로 사용합니다. GUI 도구는 필수로 설치하지 않으며 모든 컨테이너 작업은 명령어로 실행합니다.

```text
집 Windows
└─ WSL2 Ubuntu
   └─ Podman CLI

회사 Windows
└─ WSL2 Ubuntu
   └─ Podman CLI

회사 Linux 서버
└─ Podman CLI 또는 Kubernetes
```

Windows와 Linux에서 동일한 OCI 컨테이너 이미지와 Compose 설정을 사용하는 것을 원칙으로 합니다. 애플리케이션은 컨테이너 없이도 직접 실행할 수 있게 유지하며, Podman은 통합 환경과 운영 환경을 재현하기 위한 도구로 사용합니다.

기본 명령은 다음과 같습니다.

```text
podman build
podman run
podman compose up
podman compose down
```

Windows PowerShell에서 WSL 내부의 Podman을 호출해야 할 때는 `wsl podman ...` 형식을 사용할 수 있습니다. WSL2 설치와 가상화 기능 사용은 회사 보안 정책과 관리자 승인을 따릅니다.

## Kubernetes 준비

향후 Kubernetes 배포를 고려하여 로컬 검증은 Podman 기반 Kind와 `kubectl`을 사용합니다.

```text
일상 개발       → Windows 네이티브 또는 WSL2
서비스 통합     → podman compose
Kubernetes 검증 → Podman + Kind + kubectl
운영 배포       → 사내 Kubernetes
```

Kubernetes 배포 설정은 `infra/kubernetes/`에서 관리하고, 환경별 차이는 `base/`와 `overlays/`로 구분할 예정입니다. API와 Agent Worker는 로컬 상태를 갖지 않게 설계하고 PostgreSQL, Redis 및 오브젝트 스토리지를 외부 서비스로 사용합니다.

Kind는 개발과 배포 검증에만 사용하며 운영 클러스터로 사용하지 않습니다. 운영에서는 회사가 제공하는 Kubernetes를 우선 사용하고, 직접 구성해야 한다면 서버 규모와 고가용성 요구사항에 맞춰 별도로 선정합니다.

## 운영과 관측

다중 사용자 환경을 위해 다음 운영 기능을 준비합니다.

- 서버 생존 및 준비 상태 확인
- 요청 ID와 Agent Run ID가 포함된 구조화 로그
- 사용자별 요청량과 모델 토큰 사용량
- 실패율, 실행 시간 및 실행 중단 기능
- 사용자 작업 감사 로그
- 데이터 보관 기간과 삭제 정책

## 구현 우선순위

1. 사용자 인증과 사용자별 데이터 분리
2. SQLite 기반 개발용 대화 저장과 DB 마이그레이션 구성
3. SSE 기반 답변 스트리밍
4. 사용자별 동시 실행 제한
5. PostgreSQL 호환성 테스트 및 운영 DB 전환
6. 첨부 파일 스토리지 분리
7. Redis 작업 큐와 Agent Worker 도입
8. 관리자 UI와 확장 기능 권한 관리
9. 조직 단위 멀티테넌시

## 프로젝트 컨텍스트

`docs/project-context/`에는 다음과 같은 제작 기준을 정리할 예정입니다.

- 제품의 목적과 핵심 원칙
- 기능 및 비기능 요구사항
- Agent 행동 기준
- UI/UX 원칙
- 보안 및 데이터 보관 정책
- 아키텍처와 주요 설계 결정

구현을 시작하거나 구조를 변경할 때 이 문서를 먼저 확인하여 제품 방향을 일관되게 유지합니다.

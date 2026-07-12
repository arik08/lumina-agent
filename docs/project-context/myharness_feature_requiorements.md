# MyHarness 기반 답변 액션 및 Artifact 기능 요구사항

## 문서 목적

이 문서는 `.examples/MyHarness/`에서 확인한 중앙 채팅 답변 액션과 우측 Artifact 패널의 사용자 경험을 Lumina Agent의 필수 기능으로 정의합니다. MyHarness 코드를 런타임 의존성으로 사용하거나 그대로 복사하지 않고, Lumina의 `Organization → Project → Session → Run` 계층, Backend 원본 상태, 권한 격리와 event replay 원칙에 맞게 독립적으로 구현합니다.

상세 Agent 실행과 세션 복구는 `AGENT_LOOP.md`, Project·Workspace와 전문 산출물의 공통 계약은 `COWORK_FEATURE_REQUIREMENTS.md`, 로그인·관리자·대화 공유의 권한 계약은 `AUTH_AND_CONVERSATION_SHARING.md`를 함께 따릅니다.

## 필수 범위

```text
중앙 채팅 답변
├─ 답변 원문 복사
├─ 답변별·세션 누적 Token/비용 조회
├─ 답변 저장
├─ 답변 위치를 가리키는 공유 링크 복사
└─ 연결된 Artifact 카드 열기

우측 Artifact 패널
├─ 렌더링 Preview / 원본 Source 전환
├─ 수동 편집 / AI Assist 편집
├─ 저장·취소·충돌 방지·버전 전환
├─ Artifact 링크 복사
├─ 브라우저 다운로드
└─ 확대·축소·패널 크기 조절·닫기
```

위 기능은 부가 편의 기능이 아니라 Lumina의 초기 채팅·Artifact 경험에 포함하는 필수 범위입니다.

## 1. 중앙 채팅 답변 액션

### 표시 위치와 조건

- assistant 답변의 마지막, 본문과 연결된 Artifact 카드 아래에 한 줄의 compact action bar를 표시합니다.
- streaming 중인 미완료 답변에는 완료 전용 액션을 표시하지 않습니다. 답변 완료 이벤트와 최종 메시지 저장이 확인된 뒤 활성화합니다.
- 답변 완료 상태, 액션 아이콘, 답변 시각과 작업 상태 문구를 한 영역에 배치하되 본문보다 시각적으로 강하지 않게 합니다.
- 아이콘 버튼에는 접근 가능한 `aria-label`, keyboard focus와 앱 공통 tooltip을 제공합니다.
- 각 비동기 액션은 중복 실행을 막고 성공·실패 피드백을 action bar 안에서 즉시 제공합니다.

### 답변 원문 복사

- 렌더링된 DOM이 아니라 assistant 메시지의 canonical Markdown/text를 복사합니다.
- 화면에 숨겨진 구조화 Artifact 경로나 내부 Run metadata를 임의로 추가하지 않습니다.
- Clipboard API 실패 시 사용자가 원문을 잃지 않도록 명확한 오류와 재시도 가능한 fallback을 제공합니다.
- 성공 시 짧은 `복사됨` 피드백을 표시합니다.

### Token 및 비용 조회

- 답변별 usage와 현재 세션 누적 usage를 구분해 popover 또는 dialog로 제공합니다.
- 최소 표시 항목은 Provider, Model, Input, Cached Input, Uncached Input, Output과 Total token입니다.
- Provider가 reasoning token, cache write/read 또는 기타 세부 usage를 제공하면 공통 필드와 별도의 Provider 상세 항목으로 보존할 수 있습니다.
- usage 원본은 Backend가 Provider 응답에서 수집해 메시지와 Run에 저장합니다. Frontend가 텍스트 길이만으로 실제 token 사용량을 추정해 확정값처럼 표시하지 않습니다.
- 비용은 실제 Provider 청구 데이터가 있으면 이를 우선하고, 가격표 기반 계산이면 반드시 `예상 비용`으로 표시합니다. 가격표 버전, 통화, 환율 적용 시각을 추적할 수 있어야 합니다.
- 가격을 알 수 없는 사내 Provider나 사용자 계약 모델은 token만 표시하고 비용을 임의로 0원 처리하지 않습니다.
- usage가 없는 과거 메시지에는 버튼을 숨기거나 `사용량 정보 없음`을 표시하며 오류로 취급하지 않습니다.

### 답변 저장

- 답변 원문을 Project 또는 Session Artifact로 저장할 수 있게 합니다.
- `저장`은 사용자의 브라우저나 개인 PC 파일 시스템에 쓰는 동작이 아닙니다. Lumina Backend가 관리하는 서버 저장소에 Artifact를 생성하는 동작입니다.
- 초기 단일 PC 배포에서는 Lumina 프로그램이 구동되는 서버 또는 PC의 `data/` 관리 영역에 저장합니다. 브라우저를 실행하는 사용자 PC의 임의 폴더에는 접근하거나 자동 저장하지 않습니다.
- 파일명은 대화 제목과 답변 첫 문장을 기반으로 안전하게 생성하되, 사용자가 서버 내 Project 또는 Session 논리 위치와 이름을 확인·수정할 수 있어야 합니다. UI의 `저장 위치`는 사용자 PC 경로가 아니라 Lumina의 Project/Session Workspace를 뜻합니다.
- 저장 요청은 Backend가 현재 로그인 `user_id`, Project·Session 권한, quota와 파일명을 검증한 뒤 DB metadata와 실제 content를 함께 기록합니다.
- 저장된 답변은 Artifact 목록과 해당 assistant 메시지에 즉시 연결합니다.
- 사용자 입력 경로를 그대로 신뢰하지 않고 Backend에서 Project 범위, 파일명과 쓰기 권한을 검증합니다.

### 답변 공유 링크 복사

- 링크는 최소한 현재 Conversation과 정확한 assistant `message_id`를 식별하고, 열었을 때 해당 답변으로 이동·강조합니다.
- 기본 공유는 소유자가 Lumina의 특정 `login_id` 사용자를 수신자로 지정해 만드는 읽기 전용 `ConversationShareGrant`입니다. 수신자는 자신의 ID/PW로 로그인해야 하며 링크 token과 로그인 사용자가 모두 일치해야 합니다.
- 인증되지 않은 사용자가 공유 링크를 열면 로그인 화면으로 이동합니다. `아이디`와 `@주소`는 별도 입력이고 주소 기본값은 `posco.com`이며, 아이디 입력 후 `Tab`은 바로 비밀번호로 이동합니다. 로그인 성공 후 검증된 원래 공유 링크로 돌아갑니다.
- 유효한 server session은 Asia/Seoul 기준 다음 자정까지 유지하여 같은 날 공유 링크를 다시 열 때 로그인 정보를 재입력하지 않습니다.
- 기본 범위는 링크 생성 시점까지의 현재 대화 snapshot입니다. 이후 메시지, 원소유자의 다른 채팅 history, 최근 대화, 검색 결과, Project 목록과 이전·다음 대화는 노출하지 않습니다.
- 공유 viewer는 원소유자의 일반 대화 목록 API를 사용하지 않고 grant가 허용한 Conversation·Message·Attachment·Artifact만 반환하는 제한 DTO를 사용합니다.
- 공유 링크 복사는 전체 사용자 공간이나 Project 공개를 자동 활성화하지 않습니다. 링크 수신자는 대화를 수정하거나 새 Run을 시작하고 steer·승인·취소할 수 없습니다.
- 소유자는 활성 공유 대상, 만료와 최근 접근을 확인하고 언제든 grant를 취소할 수 있어야 합니다. 취소·만료 후에는 이미 열린 화면의 후속 조회와 다운로드도 거부합니다.
- 익명 외부 공개는 기본 기능에서 제외합니다. 필요하면 인증 사용자 대상 공유와 분리된 별도 정책·만료·취소·감사 계약으로 추가합니다.
- 로컬 파일 경로, 사용자 홈 경로, credential과 내부 식별자를 읽기 쉬운 query string으로 노출하지 않습니다. 불투명한 ID 또는 서명된 제한 토큰을 사용합니다.
- 성공 시 `공유 링크 복사됨`, 실패 시 원인을 표시합니다.

### 답변과 Artifact 연결

- 답변이 생성한 Artifact는 문자열 경로 탐지에만 의존하지 않고 메시지의 구조화된 `artifact_id` 목록으로 저장합니다.
- Artifact 카드는 파일명, 유형, 크기와 상태를 표시하며 선택하면 우측 패널에서 엽니다.
- 이동·이름 변경·새 버전 생성 후에도 안정적인 `artifact_id`로 메시지 연결을 유지합니다.
- 미완료 또는 존재하지 않는 파일을 성공한 Artifact처럼 표시하지 않습니다.

## 2. 우측 Artifact 패널

### 패널 기본 동작

- Artifact 카드를 선택하면 중앙 채팅을 유지한 채 우측 패널에서 엽니다.
- 패널은 resize, fullscreen, restore와 close를 지원하고 세션을 전환해도 Project/Session 범위에 맞는 열린 Artifact 상태를 복원할 수 있어야 합니다.
- 목록과 상세 화면을 구분하며 상세 화면에는 파일명, 유형, 크기, 버전과 저장 상태를 표시합니다.
- 로딩, 빈 파일, 지원하지 않는 형식, 렌더링 실패와 권한 오류를 각각 구분해 표시합니다.
- 닫지 않은 draft가 있으면 Artifact 전환·패널 닫기·페이지 이동 전에 저장 또는 폐기 여부를 확인합니다.

### 렌더링 Preview와 원본 Source

- 지원 형식은 렌더링 Preview와 원본 Source를 전환할 수 있어야 합니다.
- 초기 필수 Preview 범위는 HTML, Markdown, text, image와 PDF이며, DOCX/XLSX/PPTX는 `COWORK_FEATURE_REQUIREMENTS.md`의 전문 renderer 계약에 따라 확장합니다.
- Source는 저장된 canonical content를 표시하며 HTML의 DOM 변환 결과나 iframe에서 직렬화한 임시 문서를 원본으로 오인하지 않습니다.
- streaming 또는 저장 중인 불완전 content를 Preview할 때 렌더링 실패가 전체 패널 장애로 이어지지 않게 fallback을 제공합니다.
- HTML Preview는 sandboxed iframe 또는 동등한 격리를 사용합니다. script, network, navigation, download, popup과 clipboard 권한은 Artifact 신뢰 수준과 조직 정책에 따라 최소한으로 허용합니다.
- 외부 URL, embedded resource와 사용자 생성 script가 앱 origin의 인증 정보나 다른 Project 데이터에 접근할 수 없게 합니다.
- Markdown의 code fence, Mermaid, 표와 링크를 지원하되 렌더링 결과에 사용자 입력 HTML을 무검증 삽입하지 않습니다.
- Preview와 Source 전환 시 scroll 위치와 선택된 버전을 가능한 범위에서 유지합니다.

### 필수 Rich Content Renderer

MyHarness에서 확인한 렌더링 계열은 다음과 같습니다.

| Content | MyHarness에서 확인한 방식 | Lumina 필수 동작 |
|---|---|---|
| 데이터 차트 | HTML Artifact 안의 Apache ECharts 5 | ECharts option과 script를 포함한 독립 HTML Artifact를 sandbox Preview에서 실제 렌더링 |
| Diagram | Mermaid 11.14 | Markdown `mermaid` fence와 HTML의 `.mermaid`·`language-mermaid` block을 SVG로 렌더링 |
| Markdown | Marked 기반 변환 | heading, paragraph, list, quote, table, link, image, task list와 code fence 렌더링 |
| Code | highlight.js | fence language별 syntax highlighting과 원문 복사 |
| Math | KaTeX | inline/block LaTeX 수식 렌더링과 실패 시 원문 fallback |
| HTML | 독립 문서 iframe | CSS, SVG, Canvas와 허용된 script 기반 interactive visualization 실행 |

#### Apache ECharts

- Lumina에서 생성하는 기본 HTML chart Artifact의 표준 차트 엔진은 Apache ECharts 5 계열로 정합니다.
- 최소 지원 차트는 bar, line, area, pie/donut, scatter, stacked/combination chart이며 tooltip, legend, axis, responsive resize와 data label을 지원합니다.
- ECharts chart는 정적 placeholder가 아니라 Preview iframe에서 실제 Canvas 또는 SVG로 렌더링되어야 합니다.
- chart container에는 명시적 또는 계산 가능한 높이가 있어야 하며 패널 resize와 fullscreen 전환 시 `chart.resize()` 또는 동등한 갱신을 수행합니다.
- chart의 source data와 option은 Artifact Source에서 확인할 수 있어야 하며, AI 편집 시 chart data·option 변경도 새 Artifact version으로 저장합니다.
- 임의 버전 CDN URL에만 의존하지 않습니다. Lumina가 검증한 고정 version을 self-hosted vendor asset 또는 관리되는 asset proxy로 제공하는 방식을 기본으로 하고, 외부 CDN은 조직 정책이 허용한 경우에만 사용합니다.
- CDN 또는 network가 차단되어도 빈 영역으로 끝내지 않고 `차트를 불러오지 못했습니다` 오류, source 확인과 재시도 동작을 제공합니다.
- untrusted Artifact script는 sandbox 밖의 앱 state, cookie, token, filesystem과 다른 Project API에 접근할 수 없어야 합니다.

#### Mermaid

- Markdown에서 language가 `mermaid`인 완결된 fenced code block을 Mermaid SVG로 렌더링합니다. streaming 중 fence가 닫히기 전에는 parse를 반복하지 않고 `다이어그램 작성 중` placeholder를 표시합니다.
- flowchart, sequence, class, state, ER, Gantt, journey, mindmap과 Mermaid가 지원하는 주요 diagram을 검증합니다.
- 이미 렌더링된 Mermaid node는 이후 text delta나 Artifact 카드 갱신 때문에 불필요하게 unmount·재생성하지 않습니다.
- 큰 Mermaid SVG에는 확대 보기, zoom in/out, reset, fit, pan과 keyboard close를 제공합니다. inline 영역은 최대 높이와 내부 scroll을 가져 긴 다이어그램이 채팅 전체를 과도하게 밀지 않게 합니다.
- HTML Artifact 안의 raw Mermaid block도 같은 renderer로 SVG화할 수 있어야 합니다.
- 다운로드한 독립 HTML에서도 raw Mermaid는 렌더링되고, 이미 SVG로 변환된 Mermaid에는 renderer를 중복 삽입하지 않습니다. 확대·이동 기능도 다운로드본에서 동작해야 합니다.
- Mermaid parse 오류는 나머지 Markdown/HTML을 깨뜨리지 않고 해당 diagram 위치에 오류와 source 보기 동작을 제공합니다.

#### Markdown, Code와 Math

- Markdown renderer는 streaming 중 완결된 block과 아직 작성 중인 tail을 분리해 이미 안정화된 표·code·Mermaid가 매 delta마다 다시 mount되지 않게 합니다.
- 불완전한 table, link, HTML과 code fence는 안전한 pending 표현으로 보여주고 문법이 닫힌 뒤 최종 renderer로 전환합니다.
- heading anchor, GFM table, nested list, blockquote, task list, strikethrough, inline link와 image를 지원합니다.
- code block에는 language label, syntax highlighting, horizontal scroll과 code copy를 제공합니다. highlighting 실패 시 escaped plain code를 표시합니다.
- KaTeX inline/block 수식을 지원하되 잘못된 수식 때문에 전체 답변 렌더링이 실패하지 않게 원문 fallback을 제공합니다.
- Markdown 내부 raw HTML은 sanitization 정책에 따라 제한하며, interactive HTML 전체 문서는 별도 sandbox Artifact Preview로만 실행합니다.

#### 렌더러 일관성

- 같은 content는 중앙 채팅, 우측 Artifact Preview, 공유 링크와 다운로드본에서 의미상 같은 결과를 보여야 합니다.
- Preview 전용 editor marker, AI comment highlight, bridge script와 임시 UI는 Source 원본과 다운로드 파일에 의도치 않게 저장하지 않습니다.
- renderer 이름과 version을 Artifact version metadata 또는 render manifest에 기록하여 과거 Artifact를 재현하고 upgrade 회귀를 진단할 수 있게 합니다.
- renderer upgrade는 기존 Artifact fixture에 대한 visual regression을 통과한 뒤 적용합니다.

## 3. 수동 편집

### 편집 진입과 조작

- 편집 가능한 text, Markdown과 HTML Artifact에 `수동 편집` 액션을 제공합니다.
- HTML은 Preview 위에서 직접 본문을 수정하는 방식과 Source 편집 중 최소 하나를 제공하며, 최종 저장 content가 무엇인지 사용자가 확인할 수 있어야 합니다.
- 편집 중에는 `수정사항 반영`과 `편집 취소`를 명확히 표시합니다.
- 저장되지 않은 변경은 dirty state로 추적하고, 취소하면 마지막 저장본으로 정확히 복원합니다.
- keyboard 접근, undo/redo와 text selection을 지원하며 Preview 조작과 편집 조작이 충돌하지 않게 합니다.

### 저장과 동시 수정 충돌

- 수동 저장은 Backend의 현재 version 또는 ETag를 기준으로 optimistic concurrency check를 수행합니다.
- 편집 시작 이후 다른 사용자나 AI Run이 파일을 변경했다면 조용히 덮어쓰지 않고 비교·새 버전 저장·강제 덮어쓰기 권한 중 하나를 선택하게 합니다.
- 저장 성공 후 payload, mtime/version, Artifact 목록과 Preview를 동일한 응답 기준으로 갱신합니다.
- 저장 실패 시 draft를 보존하고 재시도 또는 복사할 수 있게 합니다.
- 모든 저장에는 사용자, 원본 version, 새 version, 시각과 변경 방식을 감사 기록으로 남깁니다.

## 4. AI Assist 편집

### 수정 의견 작성

- 우측 패널에는 Artifact 전체를 대상으로 자연어 프롬프트를 입력하는 AI 수정 Composer를 제공합니다. 사용자는 예를 들어 `표의 핵심 수치를 강조하고 결론을 더 간결하게 수정해줘`처럼 파일 전체 수정 요청을 바로 제출할 수 있어야 합니다.
- 사용자는 Preview에서 텍스트·요소·영역 또는 문서 전체를 선택해 자연어 수정 의견을 추가할 수 있습니다.
- 각 의견은 안정적인 ID, scope, 선택 text, 가능한 경우 구조화 locator와 instruction을 포함합니다.
- highlight와 번호를 Preview 및 의견 목록에 함께 표시하고, 의견 선택 시 대상 위치로 이동합니다.
- 의견은 적용 전에 수정·삭제할 수 있으며 여러 의견을 한 번에 제출할 수 있습니다.
- DOM index 하나만 locator로 사용하지 않습니다. source range, element fingerprint와 surrounding text 등 재검증 가능한 정보를 함께 저장하고 대상이 달라졌으면 사용자에게 알립니다.

### AI 편집 실행

- `AI 자동편집`은 중앙 Agent Run과 동일한 Queue, Provider, 권한, Tool, event replay 계약을 사용합니다. 별도의 숨은 LLM 호출로 실행하지 않습니다.
- 요청에는 Project, source `artifact_id`, source version, 의견 목록과 목표 형식을 snapshot으로 저장합니다.
- AI 편집은 원본을 절대 덮어쓰지 않고 항상 새 Artifact version을 생성합니다. 최초 생성본은 `v1`, 이를 대상으로 한 첫 AI 수정 결과는 `v2`, 다음 수정은 `v3`처럼 단조 증가합니다.
- 각 AI 수정 요청은 제출 시 선택된 source version에 고정됩니다. 예를 들어 사용자가 `v1`을 연 상태에서 수정하면 현재 최신 version이 `v3`이더라도 `v1`을 부모로 하는 새 version을 만들고 그 계보를 기록합니다.
- AI 편집 전 version은 삭제하거나 숨기지 않습니다. 사용자는 언제든 이전 version을 열람·Preview·Source 확인·공유·다운로드할 수 있어야 합니다.
- 새 version 생성이 완전히 저장되고 검증되기 전에는 current version을 변경하지 않습니다. 실패하거나 취소된 AI 요청은 원본 version에 어떤 변경도 남기지 않습니다.
- 완료 후 version selector에 새 version을 추가하고 결과를 엽니다. 사용자는 이전 version과 AI 결과를 전환·비교하고, 필요하면 이전 version을 기반으로 다시 새 version을 만들 수 있어야 합니다.
- 실행 중에는 요청 접수, model streaming, Tool 실행, 파일 저장, 검증과 완료 상태를 패널에 표시합니다.
- 사용자가 패널을 닫거나 세션을 전환해도 Run은 계속되고, 다시 열었을 때 snapshot·event replay로 진행 상태를 복원합니다.
- 같은 Artifact에 AI 편집과 수동 저장이 충돌하면 source version을 검사하고 자동 병합하지 않습니다.
- 실패해도 원본과 수정 의견을 보존하며 retry 또는 수동 편집으로 전환할 수 있게 합니다.

### 결과 검증

- AI 결과가 target 파일을 실제로 생성·저장했는지 Backend에서 확인한 뒤 완료로 표시합니다.
- HTML/Markdown은 parse와 기본 render 검증을 수행하고, DOCX/XLSX/PPTX/PDF는 각 전문 산출물의 render-and-verify 절차를 따릅니다.
- 검증 실패 결과는 정상 version으로 자동 승격하지 않고 오류와 복구 선택지를 표시합니다.

## 5. 버전과 파일 관리

- Artifact는 경로가 아닌 안정적인 `artifact_id`와 단조 증가하는 version number를 가집니다. version 하나는 저장 후 내용이 바뀌지 않는 immutable snapshot입니다.
- 화면에는 사용자 친화적인 `v1`, `v2`, `v3` label을 표시하고 각 version의 생성 시각, 작성 주체, 변경 방식, 부모 version과 수정 프롬프트 요약을 확인할 수 있게 합니다.
- 원본, 수동 편집본과 AI 편집본 사이를 version selector로 전환할 수 있게 하며, 선택한 이전 version을 단순 조회하는 동작이 current version을 바꾸지는 않습니다.
- 이전 상태로 되돌리기는 과거 version을 덮어쓰거나 번호를 재사용하지 않고, 선택한 과거 version의 내용을 복제한 새 version을 생성합니다. 예를 들어 최신이 `v3`일 때 `v1`로 복원하면 결과는 `v4`가 됩니다.
- AI 수정은 항상 새 version을 생성해야 하며 in-place overwrite API를 사용하지 않습니다. 수동 편집도 감사·복구가 중요한 Artifact에는 같은 version 생성 방식을 기본값으로 사용합니다.
- 파일명 변경은 확장자·Project 경계·중복 이름을 Backend에서 검증하며 메시지 연결과 공유 링크가 끊기지 않게 합니다.
- 삭제는 확인 절차를 거치고 권한과 현재 version을 재검증합니다. 공유 중이거나 다른 Run에서 사용하는 Artifact는 영향을 안내합니다.
- 목록에는 유형 필터, 최근/경로 정렬과 다운로드를 제공할 수 있으나 Preview·편집·공유·다운로드 구현보다 우선하지 않습니다.

## 6. Artifact 링크 복사

- 패널의 `링크 복사`는 현재 Artifact와 선택된 version을 식별하는 deep link를 생성합니다.
- 링크를 열면 Project 권한 확인 후 해당 Artifact 패널과 version을 직접 엽니다.
- 링크 자체에 서버의 실제 파일 경로를 포함하지 않습니다.
- private Project의 링크는 인증된 권한 사용자만 열 수 있으며, shared 모드도 조직 정책과 Artifact 공개 범위를 적용합니다.
- 외부 공개 링크는 기본 기능과 분리하고 만료·비밀번호·다운로드 허용·취소 가능한 share record를 Backend에 저장합니다.
- 링크 생성과 접근은 감사 가능해야 합니다.

## 7. 브라우저 다운로드

- 브라우저 다운로드만 서버에 저장된 Artifact의 사본을 사용자의 개인 PC로 전달하는 동작입니다. `저장`, AI Artifact 생성과 자동 version 생성은 다운로드를 발생시키지 않습니다.
- 다운로드가 끝나도 서버의 원본 Artifact, version, 소유권과 공유 상태는 그대로 유지합니다. 개인 PC의 다운로드 파일은 Lumina가 이후 자동 동기화하거나 원본으로 사용하지 않습니다.
- 모든 Artifact에 원본 파일 다운로드를 제공하고 Preview 미지원 형식은 다운로드를 기본 동작으로 안내합니다.
- 다운로드 endpoint는 불투명한 Artifact ID와 version을 받고 매 요청마다 사용자·조직·Project·공유 범위를 검증합니다.
- 응답에 정확한 MIME type, 안전한 `Content-Disposition` 파일명과 `Content-Length`를 제공합니다.
- 파일명은 CR/LF, path separator와 header injection 문자를 제거하고 Unicode 파일명 fallback을 처리합니다.
- 다운로드가 앱 Preview URL이나 로컬 filesystem 경로를 직접 노출하지 않게 합니다.
- 대용량 파일은 메모리에 전부 적재하지 않고 streaming하며, 중단·만료·삭제된 version에는 명확한 오류를 반환합니다.
- Download action은 브라우저 기본 저장 흐름을 사용하되 실패 시 새 빈 탭만 남기지 않고 오류를 표시합니다.

## 8. Backend 데이터 및 API 계약

최소 데이터 모델은 다음 관계를 표현해야 합니다.

```text
AssistantMessage
├─ message_id
├─ run_id
├─ canonical_text
├─ usage
└─ artifact_ids[]

Artifact
├─ artifact_id
├─ organization_id / project_id
├─ current_version
├─ display_name / kind / mime_type
└─ visibility

ArtifactVersion
├─ artifact_id / version
├─ storage_key
├─ content_hash / size
├─ created_by / created_at
├─ source_version
├─ parent_version
├─ change_prompt_summary
└─ change_type: generated | manual_edit | ai_edit | restore
```

Artifact content의 실제 저장은 Backend의 Storage Adapter를 통해 처리합니다.

```text
초기 단일 서버/PC
└─ LocalServerStorage
   └─ Lumina 구동 장비의 data/files 또는 data/artifacts 관리 영역

향후 분리 운영
└─ ObjectStorage
   └─ 별도 S3/MinIO 또는 조직 파일 저장 서버
```

- DB에는 사용자 PC 경로가 아니라 `storage_backend`, 불투명한 `storage_key`, content hash와 크기를 저장합니다.
- 애플리케이션 코드와 API는 LocalServerStorage의 실제 절대 경로에 의존하지 않습니다. 같은 Artifact ID와 API 계약을 유지한 채 Object Storage로 이전할 수 있어야 합니다.
- 별도 저장 서버로 이전할 때 content를 복사하고 hash를 검증한 뒤 storage pointer를 원자적으로 전환합니다. 이전 중에도 잘못된 사용자에게 파일이 노출되지 않게 소유권과 Project scope를 유지합니다.
- Backend와 Worker가 여러 장비로 분리된 이후에는 각 장비의 로컬 디스크를 canonical Artifact 원본으로 사용하지 않고 공유 Object Storage를 사용합니다.

API는 최소한 다음 의미의 동작을 제공합니다. 실제 route 이름은 Backend convention에 맞게 정합니다.

- 메시지 원문과 답변별·세션별 usage 조회
- 답변을 Artifact로 저장
- Artifact 목록·metadata·특정 version content 조회
- optimistic concurrency를 포함한 수동 저장
- AI edit Run 생성과 상태 조회
- version 목록·전환·이름 변경·삭제
- 권한 검증된 deep link 생성·해석
- 권한 검증된 원본 다운로드
- 수신자 지정 Conversation share 생성·목록·취소·해석
- 공유 snapshot 전용 메시지·첨부·Artifact 조회

모든 API는 Frontend가 보낸 경로, 사용자 ID, role, Project ID, Conversation ID, message ID, Artifact ID와 version을 신뢰하지 않고 현재 인증 주체의 소유권·관리자 role·정확한 share grant 범위를 다시 검증합니다. 비밀값, credential, 비밀번호, session cookie, share token 원문, 로컬 경로와 대화 원문 전체를 Run event나 일반 로그에 기록하지 않습니다.

## 9. 상태 복구와 동기화

- 열린 Artifact, 선택 version, Preview/Source 모드, dirty state와 AI edit 진행 상태를 구분합니다.
- canonical Artifact와 version metadata는 Backend가 원본입니다. 패널 폭·fullscreen처럼 순수 UI 설정만 Frontend에 저장할 수 있습니다.
- 세션 전환·새로고침·네트워크 재연결 후 열린 Artifact와 AI edit Run을 snapshot·event replay로 복원합니다.
- 로컬 dirty draft는 서버 저장본과 자동 합치지 않습니다. 복구 가능한 임시 draft로 별도 표시하고 version 충돌 검사를 거칩니다.
- AI edit 완료 이벤트를 받으면 대상 Artifact가 실제 조회 가능한지 확인한 뒤 version selector와 Preview를 갱신합니다.

## 10. 테스트 및 수용 기준

### 중앙 답변

1. 완료된 assistant 답변 끝에 복사, 사용량, 저장과 공유 액션이 표시되고 streaming 중에는 완료 액션이 나타나지 않습니다.
2. 복사는 canonical 원문과 정확히 일치하며 성공·실패 피드백을 제공합니다.
3. 답변별 usage와 세션 누적 usage가 섞이지 않고, 비용 추정값은 실제 청구값처럼 표시되지 않습니다.
4. 공유 링크는 지정된 수신자가 로그인했을 때 정확한 snapshot과 메시지로 이동하며, 원소유자의 다른 채팅 history·검색·Project·Artifact를 노출하지 않습니다.
5. 구조화된 Artifact 카드가 올바른 우측 패널 Artifact를 엽니다.
6. 답변 `저장`과 Artifact 생성은 Lumina 구동 서버의 관리 저장소에 기록되고 사용자 PC에는 브라우저 다운로드 전까지 파일이 생성되지 않습니다.

### Artifact 보기와 편집

7. Preview/Source 전환 후에도 같은 Artifact version이 유지되고 지원 형식별 fallback이 동작합니다.
8. 악성 HTML Artifact가 앱 origin, 인증 정보, 상위 window 또는 다른 Project 데이터에 접근하지 못합니다.
9. 수동 편집의 저장·취소·dirty 경고가 동작하고 동시 수정 충돌이 조용한 덮어쓰기로 끝나지 않습니다.
10. 여러 AI 수정 의견의 highlight, 삭제, 제출과 진행 상태가 일치합니다.
11. AI 프롬프트 편집은 선택한 source version을 그대로 보존하고 `v1 → v2 → v3`처럼 정확히 하나의 새 immutable version을 생성하며, 세션 전환·재연결 후에도 진행 상태와 결과를 복원합니다.
12. AI 결과 검증 실패 시 완료·채택된 version처럼 표시되지 않습니다.
13. 이전 version 열람·다운로드·공유가 가능하고, 이전 version 복원은 기존 version을 덮어쓰지 않고 새 version을 생성합니다.
14. ECharts HTML Artifact가 실제 chart로 렌더링되고 resize/fullscreen 후에도 크기와 interaction이 정상이며, asset 로드 실패 시 오류 fallback을 표시합니다.
15. Markdown의 표·code highlighting·KaTeX와 Mermaid diagram이 렌더링되고, 불완전 streaming fence와 parse 오류가 다른 본문을 깨뜨리지 않습니다.
16. 큰 Mermaid diagram의 확대·축소·fit·pan이 동작하고 이미 렌더링된 SVG가 후속 streaming delta 때문에 다시 생성되지 않습니다.

### 링크와 다운로드

17. Artifact deep link는 정확한 version을 열고 권한과 공유 범위를 다시 검증합니다.
18. 대화 링크를 다른 계정에 전달하거나 Conversation·Message ID를 변조해도 공유 범위가 확대되지 않습니다.
19. 공유 grant 취소·만료 후 메시지 조회, Artifact preview와 다운로드가 모두 거부됩니다.
20. 다운로드한 파일의 byte, 확장자, MIME type과 파일명이 서버에 저장된 Artifact version과 일치하며 개인 PC 사본이 서버 원본을 변경하지 않습니다.
21. 다운로드한 독립 HTML에서 ECharts와 raw Mermaid가 정책상 허용된 asset 경로를 통해 렌더링되고 Preview 전용 편집 marker는 포함되지 않습니다.
22. 권한 없는 Artifact ID·version·변조된 링크·path traversal 입력은 정보 노출 없이 거부됩니다.

### 실제 브라우저 검증

23. 실제 브라우저에서 긴 답변 action bar, Token popover, 우측 패널 resize/fullscreen, ECharts HTML, Mermaid, Markdown·code·math, image·PDF Preview, Source 전환, 수동 저장, AI edit 진행, version 전환, 링크 복사와 다운로드를 end-to-end로 확인합니다.
24. keyboard-only 조작, focus 이동, tooltip, screen reader label과 reduced-motion 환경을 확인합니다.
25. JSDOM 단위 테스트와 API 테스트만으로 완료 판정하지 않고, 다운로드 파일과 렌더링 화면을 실제로 검증합니다.

## 11. 구현 우선순위

### P0 — 핵심 필수

1. 답변 복사·usage 조회·공유 링크
2. 구조화된 Artifact 카드와 우측 패널
3. ECharts·Mermaid·Markdown·code·KaTeX를 포함한 HTML·Markdown·text·image·PDF Preview 및 Source
4. 수동 편집 저장·취소·충돌 방지
5. AI Assist 의견·새 version 생성·진행 복구
6. Artifact deep link와 권한 검증 다운로드

### P1 — 완성도

1. version 비교와 명시적 채택
2. 답변 저장의 위치·파일명 선택
3. Project 파일 필터·정렬·이름 변경·삭제
4. DOCX/XLSX/PPTX 전문 Preview와 편집 연결
5. 외부 공개 링크의 만료·취소·다운로드 정책

## 참고한 MyHarness 위치

- `.examples/MyHarness/frontend/web/src/components/AssistantActions.tsx`
- `.examples/MyHarness/frontend/web/src/components/AssistantArtifactCards.tsx`
- `.examples/MyHarness/frontend/web/src/components/ArtifactPanel.tsx`
- `.examples/MyHarness/frontend/web/src/components/ArtifactPreview.tsx`
- `.examples/MyHarness/frontend/web/src/api/artifacts.ts`
- `.examples/MyHarness/frontend/web/src/utils/chatShare.ts`
- `.examples/MyHarness/frontend/web/src/components/__tests__/ArtifactPanel.test.tsx`
- `.examples/MyHarness/frontend/web/src/components/__tests__/MessageList.test.tsx`

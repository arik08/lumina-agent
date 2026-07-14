# Lumina Agent Project Instructions

## 기본 원칙

- 사용자에게는 존댓말을 사용합니다.
- 작업 전 루트 `README.md`와 관련 `docs/project-context/` 문서를 확인합니다. 제품 방향과 구현이 충돌하면 임의로 바꾸지 말고 사용자에게 알립니다.
- 변경은 현재 요청 범위로 제한하고 Windows와 Linux에서 모두 동작하게 합니다. 실제 데이터·인증서·API 키·사용자 비밀값은 Git, 로그, Run event에 남기지 않습니다.

## 구현 기준

- Frontend는 `apps/web/`, Backend는 `apps/server/`, Provider는 `apps/server/src/lumina/providers/`, Plugin·Skill·MCP는 `extensions/`에 둡니다. 하나의 서비스처럼 보이되 Frontend·Backend·Agent Worker 경계는 유지합니다.
- UI 작업 전 `PRODUCT.md`와 `DESIGN.md`를 읽고 기존 token·공용 component·interaction pattern을 우선합니다. 반복 값은 화면별 하드코딩 대신 공용 token 또는 variant로 정의합니다.
- 작업 영역별 기준 문서를 따릅니다.
  - Agent 실행·Queue·중단·복구·event replay: `docs/project-context/AGENT_LOOP.md`
  - Composer의 `@파일명`, `$Skill`, `$MCP`: `docs/project-context/HERMES_USER_FEATURES.md`
  - Project·Plan·Workspace·Artifact·예약 작업: `docs/project-context/COWORK_FEATURE_REQUIREMENTS.md`
  - Skill·MCP Marketplace: `docs/project-context/EXTENSION_MARKETPLACE.md`와 `.examples/AI_Skill_MarketPlace/`
  - Provider model mapping·기본값·갱신 정책: `docs/LUMINA_DETAILED_DESIGN.md` 12.3. 새로 발견한 Model은 자동 활성화하지 않습니다.
  - P-GPT·회사 CA·proxy·Web Search: `docs/project-context/PGPT_CORPORATE_NETWORK.md`
- `.examples/`는 참고 전용입니다. 다룰 때 `.examples/AGENTS.md`를 따르고 Lumina의 import·build·test·package·deploy 대상에 포함하지 않습니다.

## 핵심 불변 규칙

- 기본 계층은 `Organization → Project → Session → Run`이며 Project별 파일·지침·기억·허용 확장을 격리합니다.
- 사용자 데이터는 기본 격리하고 명시적으로 활성화한 공유 모드에서만 공유합니다. 사용자별 `AGENTS.md`는 루트 규칙을 대체할 수 없으며 비밀값·개인 계정 정보와 함께 공유하지 않습니다.
- 서로 다른 Session의 Run은 병렬 실행할 수 있고 같은 Session은 한 Run만 실행하며 추가 요청은 Queue에 둡니다. 세션 이동·연결 종료가 Run을 중단하지 않으며, 재접속 시 Backend snapshot과 순번 event replay로 진행 상태를 복원합니다.
- Frontend가 보낸 파일 경로와 Skill·MCP 이름을 신뢰하지 말고 Backend에서 사용자·조직·공유 범위와 권한을 재검증합니다.
- 모든 MCP는 필요한 순간에만 사용 지침을 Context에 넣을 수 있도록 `extensions/skills/<wrapper>/SKILL.md`로 감싸고 frontmatter에 `source: skill-mcp:<mcp-slug>`를 둡니다. MCP wrapper는 저장·카탈로그·Composer에서 일반 Skill이 아니라 MCP로 분류하며 Skill과 MCP 양쪽에 중복 노출하지 않습니다. 새 MCP를 추가하거나 slug를 바꿀 때 manifest와 wrapper를 같은 변경에서 함께 갱신합니다.
- Skill WorkingDraft는 실제 Run에 즉시 사용할 수 있어야 하고 Run은 정확한 revision과 digest를 고정합니다. 명시적 저장만 immutable version을 만들며 새 Skill은 기본 Private입니다. 활성 Draft는 관련 UI에 `Draft rN`과 저장 action을 표시합니다. Folder 이동은 배치 metadata만 바꾸고 stable ID·version·digest·installation·Run snapshot은 보존합니다.
- 사용자가 형식을 지정하지 않은 보고서는 독립 실행형 HTML을 기본으로 생성합니다. 외부 연결은 전용 Connector/API → MCP → Browser 자동화 → Computer Use 순으로 우선합니다.
- TLS 오류를 `verify=False`로 우회하지 않고 public CA와 company CA를 결합한 Trust Manager를 사용합니다. P-GPT 기본 endpoint는 MyHarness와 같게 유지하고 `PGPT_BASE_URL`은 관리자 override로만 제공합니다.
- 개발 DB는 SQLite를 사용하되 PostgreSQL 이전 가능성을 유지합니다. 새 옵션은 저장 위치·기본값·복원 시점·fallback을 함께 정합니다. Provider·Model·Effort 등 지속 선택값의 원본은 서버 DB이며 개인 모드는 사용자 설정, 공유 모드는 공유 작업공간 설정에 저장합니다. 비밀값·승인·임시 실행 상태는 자동 저장하지 않습니다.

## UI 상호작용

- 사용자 노출 scrollbar는 공용 `thin` 스타일, 투명 track, `--cobalt` 기반 thumb를 사용합니다.
- Tooltip은 `GlobalTooltipProvider` 또는 `GlobalTooltipLayer`가 `document.body` Portal에 렌더링합니다. 기본은 trigger 위, 공간이 부족할 때만 아래로 전환하며 `title`, `::after`, clipping container 내부 구현은 사용하지 않습니다.
- 이름·라벨·제목은 별도 modal보다 보이는 자리에서 직접 편집하는 WYSWYR 방식을 우선하고 저장·취소·오류도 그 자리에 표시합니다.
- 삭제는 popup/modal 없이 같은 버튼의 2단계 확인을 사용합니다. 첫 클릭은 `한 번 더 눌러 삭제`, 두 번째 클릭은 실행이며 대상·화면 변경 시 확인 상태를 해제합니다.

## 테스트 포트와 사용자 화면 보호

- 자동 테스트·QA는 기본적으로 `LUMINA_FRONTEND_PORT=15252`, `LUMINA_BACKEND_PORT=15253`을 사용합니다. 사용 중이면 `5252`, `5253`을 제외한 빈 포트 쌍을 선택합니다.
- 여러 Agent가 동시에 작업할 때는 실행 전에 listener를 확인하고 Agent마다 서로 다른 Frontend·Backend 포트 쌍을 배정합니다. 다른 Agent가 시작한 테스트 runtime이나 포트를 재사용·종료하지 않으며, 자신이 선택한 포트를 작업 로그에 명시합니다.
- 테스트 중 사용자 포트 `5252`, `5253`을 점유·종료하지 말고, 격리 포트 없이 `run_lumina.bat` 또는 `run_lumina_dev.bat`를 실행하지 않습니다. 종료할 때는 직접 시작한 process만 종료합니다.
- UI/API 검증은 자신에게 배정한 격리 테스트 URL에서만 수행합니다. 사용자가 열어 둔 Lumina 탭·창·브라우저 context를 클릭·이동·새로고침·종료하지 않습니다. Codex 앱 화면 점검도 사용자 화면을 재사용하지 않는 별도 테스트 탭·창에서 수행하고, 분리할 수 없으면 사용자 화면을 건드리지 않는 격리 browser context를 fallback으로 사용합니다.
- 작업 완료 후 재시작이 필요한 변경을 실제 환경에 반영할 때만 사용자 runtime을 재시작하고 포트와 결과를 알립니다. 사용자가 UI를 직접 테스트 중이면 명시적인 요청 없이 사용자 runtime이나 화면을 재시작하지 않습니다.
- UI 점검용 screenshot·trace 등 임시 산출물은 저장소 루트가 아니라 `.lumina-ui-checks/` 아래에만 저장합니다. `artifact-output-*` 같은 점검 파일을 루트에 만들지 않으며, 직접 생성한 임시 산출물은 검증 후 정리합니다.
- UI 점검에서 Playwright·Chrome을 직접 실행하는 fallback은 browser/context 종료를 `finally`에서 보장하고, 바깥 실행기에도 제한시간을 둡니다. 정상 완료·오류·시간 초과 뒤에는 이번 점검에서 시작한 root PID의 process tree가 남지 않았는지 확인하고, 남아 있으면 그 tree만 종료합니다. 이름만으로 모든 `chrome.exe`를 일괄 종료하지 않습니다.

## CodeGraph

- 코드 작업 시작 시 `codegraph status --json .`과 `.codegraph/codegraph.db` 수정 시각을 확인합니다. graph가 없거나 pending change가 있거나 `reindexRecommended`가 true이면 `powershell -ExecutionPolicy Bypass -File devtools/update_codegraph.ps1`로 갱신하고 다시 확인합니다.
- 코드 수정·리뷰·리팩터링·영향 조사에는 MCP의 `codegraph_explore`를 우선합니다. MCP가 현재 세션에 없으면 `codegraph explore "<질문 또는 심볼>"` CLI를 사용합니다. 순수 문구 수정이나 영향이 명백한 국소 변경은 생략할 수 있습니다.
- 최신 CodeGraph MCP는 기본적으로 `codegraph_explore` 하나만 노출합니다. 과거의 `codegraph_status`, `codegraph_search`, `codegraph_node` 등 개별 도구가 없다는 이유로 연결 실패로 판단하지 않습니다.
- `.examples/`, `data/`, 비밀 정보와 생성 산출물은 인덱스에 포함하지 않습니다.

## 병렬 개발과 통합

- 둘 이상의 독립 작업을 동시에 진행할 때는 Agent·작업별로 별도 단기 브랜치와 Git worktree를 사용합니다. 같은 브랜치나 같은 작업 디렉터리를 여러 Agent가 공유하지 않으며 `main`은 통합과 최종 검증의 기준으로 유지합니다.
- 병렬 작업 전 Frontend·Backend·Provider·문서처럼 소유 영역과 수정 가능 파일을 나눕니다. 같은 공용 파일, DB schema, API 계약, 공용 type을 함께 바꿔야 하는 작업은 병렬로 진행하지 말고 선행 작업과 병합 순서를 정합니다.
- 브랜치는 독립 검증 가능한 작은 기능 단위로 짧게 유지하고 완료되는 즉시 하나씩 `main`에 병합합니다. 여러 장기 브랜치를 한꺼번에 합치지 않으며 각 병합 직후 관련 테스트와 통합 테스트를 실행합니다.
- 병합 전에 대상 브랜치를 최신 `main`과 동기화하고 diff·테스트·migration·공용 계약 변경을 확인합니다. 텍스트 충돌이 없더라도 API, event, DB, UI 동작의 의미 충돌이 없는지 점검합니다.
- 병합과 충돌 해결은 한 시점에 하나의 통합 작업만 수행합니다. 충돌 해결 과정에서 어느 한쪽 변경을 임의로 버리지 말고 양쪽 의도와 테스트를 확인합니다.
- 병렬화로 얻는 이점보다 충돌 가능성이 큰 작업은 순차 실행합니다. 작업 경계가 불명확하면 먼저 조사 또는 공용 기반 변경을 별도 브랜치에서 끝낸 뒤 후속 작업을 나눕니다.

## Git 체크포인트

- 작업과 검증이 끝나면 `git status`로 포함 대상을 확인하고 비밀값·runtime data·생성 cache를 제외한 뒤 변경사항을 stage합니다.
- `git commit -m "수정사항: <핵심 변경 요약>"` 형식으로 로컬 커밋합니다. commit은 최종 작업 종료까지 쌓아 두지 말고 작은 독립 변경의 검증이 끝날 때마다 수시로 남깁니다.
- 긴 작업과 병렬 작업은 기능·수정·문서처럼 독립적으로 되돌리고 검증할 수 있는 단위마다 중간 커밋을 남깁니다. 관련 없는 변경을 하나의 큰 커밋으로 묶지 않습니다.
- 원격 push는 사용자가 명시적으로 요청한 경우에만 수행합니다.
- 사용자의 `push`, `푸시` 지시는 별도의 `add`·`commit` 명령을 기다리라는 뜻이 아니라 현재 작업의 전체 게시 절차를 승인한 것으로 해석합니다. 즉시 `git status`와 diff를 확인하고, 현재 작업 범위의 안전한 미커밋 변경을 stage하고 필요한 commit을 만든 뒤 현재 브랜치를 push하며 같은 절차를 다시 확인받지 않습니다.
- `push` 지시가 있어도 비밀값·runtime data·생성 cache·다른 작업의 변경은 자동으로 포함하지 않습니다. 포함 범위가 정말 구분되지 않을 때만 사용자에게 확인합니다.
- 완료 보고에서 기본 정책대로 push하지 않았다는 사실이나 다른 작업의 변경을 건드리지 않았다는 사실을 매번 상투적으로 나열하지 않습니다. push 성공·실패, 예상 밖의 제외·충돌·잔여 변경처럼 사용자가 알아야 할 예외가 있거나 사용자가 직접 물었을 때만 알립니다.

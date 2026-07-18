# Lumina Agent Project Instructions

## 기본 원칙

- 사용자에게는 존댓말을 사용합니다.
- 변경은 현재 요청 범위로 제한하고 Windows와 Linux에서 모두 동작하게 합니다.
- 실제 데이터, `.env`, 인증서, API key와 사용자 비밀값을 Git, 로그, Run event에 남기지 않습니다.
- 문서에 적힌 기능을 구현 완료로 간주하지 않습니다. 현재 source, migration과 통과하는 test를 함께 확인합니다.

## 기준 문서

- 요구사항이 겹치면 루트 `AGENTS.md` → `docs/LUMINA_DESIGN.md` → 기능별 `docs/project-context/` 문서 → `README.md` → `.examples/` 순으로 해석합니다. 구현과 설계가 충돌하면 임의로 맞추지 말고 차이와 영향을 사용자에게 알립니다.
- `README.md`는 제품 개요와 사용 안내, `docs/LUMINA_DESIGN.md`는 통합 구현 계약의 원본입니다.
- 사용자 요청을 해석하고 작업 범위·완료 증거를 정할 때 `docs/DEVELOPMENT_INSTRUCTION_PATTERNS.md`의 관련 heading을 공통 참고합니다. 이 문서는 반복 지시의 해석 guide이며 제품 계약을 대체하지 않고, 현재 사용자의 가장 최근 명시적 지시가 항상 우선합니다.
- UI 작업 전 `PRODUCT.md`와 `DESIGN.md`를 읽고 공용 token, component와 interaction pattern을 우선합니다.
- 영역별 상세 기준은 다음 문서를 사용합니다.
  - Agent Run, Queue, 복구와 event: `docs/project-context/AGENT_LOOP.md`
  - Composer, Session UX와 알림: `docs/project-context/HERMES_USER_FEATURES.md`
  - Project, Plan, Workspace, Artifact와 예약 작업: `docs/project-context/COWORK_FEATURE_REQUIREMENTS.md`
  - Skill·MCP Marketplace: `docs/project-context/EXTENSION_MARKETPLACE.md`
  - P-GPT, 회사 CA, proxy와 Web Search: `docs/project-context/PGPT_CORPORATE_NETWORK.md`
  - 설치, 테스트 명령과 격리 포트: `docs/project-context/INSTALLATION_AND_DIAGNOSTICS.md`
- `.examples/`는 참고 전용입니다. 조사할 때 `.examples/AGENTS.md`를 따르고 Lumina의 import, build, test, package 또는 deploy 대상에 포함하지 않습니다.

## 구현 불변 조건

- Frontend는 `apps/web/`, Backend는 `apps/server/`, Provider는 `apps/server/src/lumina/providers/`, Skill·MCP는 `extensions/` 경계를 유지합니다.
- 기본 계층은 `Organization → Project → Session → Run`입니다. 사용자·Project 데이터는 기본 격리하고 명시적으로 허용한 범위에서만 공유합니다.
- 서로 다른 Session의 Run은 병렬 실행할 수 있지만 같은 Session은 한 Run만 실행하고 추가 요청은 Queue에 둡니다. 화면 이동이나 연결 종료로 Run을 중단하지 않으며 재접속 시 Backend snapshot과 순번 event replay로 복원합니다.
- Frontend가 보낸 경로, ID와 Skill·MCP 이름을 신뢰하지 말고 Backend에서 사용자, 조직, Project, 공유 범위와 권한을 다시 검증합니다.
- Run이 사용하는 파일, 지침, Provider 설정과 Skill·MCP는 정확한 version·revision·digest를 snapshot으로 고정합니다.
- 새 Provider Model은 자동 활성화하지 않습니다. 지속 선택값의 원본은 서버 DB이며 새 옵션에는 저장 scope, default, restore 시점과 invalid fallback을 함께 정의합니다.
- TLS 오류를 `verify=False`로 우회하지 않고 public CA와 company CA를 결합한 Trust Manager를 사용합니다.
- MCP definition과 `extensions/skills/<wrapper>/SKILL.md`의 `source: skill-mcp:<mcp-slug>`를 함께 관리하고 Skill과 MCP로 중복 노출하지 않습니다.

## UI 변경

- GUI 요청은 `docs/DEVELOPMENT_INSTRUCTION_PATTERNS.md`의 `4. GUI 관련 요청 패턴 상세 분석`에서 요청 표현, 국소 변경, 상태 전이, 디자인 취향과 실제 화면 검증 기준을 먼저 확인합니다. 긴 문서 전체를 매번 읽지 말고 현재 요청과 관련된 `4.x` heading을 검색해 적용합니다.
- 시각 규칙은 `PRODUCT.md`와 `DESIGN.md`를 원본으로 사용하며 화면별 하드코딩이나 중복 component를 추가하지 않습니다.
- 이름·라벨·제목은 가능한 한 보이는 자리에서 직접 편집하고 저장·취소·오류도 같은 위치에 표시합니다.
- 삭제는 popup이나 modal 대신 같은 버튼의 인라인 2단계 확인을 사용합니다. 대상이나 화면이 바뀌면 확인 상태를 해제합니다.
- 실제 UI를 수정한 경우 단위 test만으로 완료하지 않고 격리된 브라우저에서 화면, 반응형 배치와 console 오류를 확인합니다.

## 검증과 사용자 환경 보호

- 변경 범위에 맞는 test, typecheck와 build를 실행합니다. 전체 기본 명령은 `docs/project-context/INSTALLATION_AND_DIAGNOSTICS.md`를 따릅니다.
- 코드 작업 전 `codegraph status --json .`과 `.codegraph/codegraph.db` 수정 시각을 확인합니다. graph가 없거나 pending change 또는 `reindexRecommended`가 있으면 `powershell -ExecutionPolicy Bypass -File devtools/update_codegraph.ps1`로 갱신합니다. 순수 문서·문구 수정이나 영향이 명백한 국소 변경은 생략할 수 있습니다.
- 영향 조사에는 `codegraph_explore`를 우선하고 MCP가 없으면 `codegraph explore "<질문 또는 심볼>"` CLI를 사용합니다.
- 개별 도구가 없다는 이유로 연결 실패로 판단하지 않습니다. 사용 가능한 CodeGraph MCP 도구나 CLI 명령으로 동일한 조사를 계속합니다.
- 자동 QA의 기본 포트는 Frontend `15252`, Backend `15253`입니다. 사용 중이면 사용자 포트 `5252`, `5253`을 제외한 빈 포트 쌍을 선택합니다.
- 사용자의 runtime, 포트, Lumina 탭과 browser context를 재사용·종료·이동·새로고침하지 않습니다. 자신이 시작한 격리 process와 browser context만 종료합니다.
- UI 점검용 screenshot·trace는 `.lumina-ui-checks/`에 두고 검증 후 정리합니다. 개선 결과를 보고할 screenshot은 저장소 밖에 보관해 첨부합니다.
- Playwright·Chrome fallback에는 제한시간과 `finally` 정리를 두고, 시작한 root PID의 process tree만 정리합니다. 이름으로 모든 `chrome.exe`를 종료하지 않습니다.

## 병렬 작업과 Git

- 둘 이상의 독립 작업을 병렬화할 때는 Agent별 단기 branch와 worktree, 수정 파일과 테스트 포트를 분리합니다. 공용 schema, API, event 또는 type 변경은 순서를 정해 통합하고 병합 직후 검증합니다.
- 작업 후 `git status`와 diff로 범위를 확인하고 비밀값, runtime data, cache와 다른 작업의 변경을 제외해 stage합니다.
- 검증된 독립 변경은 `git commit -m "수정사항: <핵심 변경 요약>"` 형식으로 로컬 commit합니다.
- 원격 push는 사용자가 명시적으로 요청한 경우에만 수행합니다. `push` 또는 `푸시` 요청은 현재 작업 범위의 stage, commit과 push 전체를 승인한 것으로 해석합니다.

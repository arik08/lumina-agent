# Lumina Agent Project Instructions

## Language

- 사용자에게는 존댓말을 사용합니다.

## Project Context

- 작업 전에 루트 `README.md`와 관련된 `docs/project-context/` 문서를 확인합니다.
- 제품 방향과 구현이 충돌하면 임의로 변경하지 않고 차이를 사용자에게 알립니다.

## Architecture

- 사용자에게는 하나의 서비스로 보이게 하되 Frontend, Backend와 Agent Worker의 경계를 유지합니다.
- Frontend 코드는 `apps/web/`, Backend 코드는 `apps/server/`에 작성합니다.
- Provider 구현은 `apps/server/src/lumina/providers/`에 둡니다.
- Plugin, Skill과 MCP 자원은 `extensions/`에 둡니다.
- Agent 실행은 `docs/project-context/AGENT_LOOP.md`의 반복, 권한, 제한, 중단·재개와 이벤트 규칙을 따릅니다.
- 개발 DB는 SQLite를 사용하되 PostgreSQL 이전 가능성을 유지합니다.
- 실제 데이터, 인증서, API 키와 사용자 비밀값을 Git에 커밋하지 않습니다.
- 사용자 데이터는 기본적으로 격리하며, 명시적으로 활성화된 공유 모드에서만 대화와 artifacts를 사용자 간 공유합니다.
- 개인 세션에서는 마지막 선택값을 사용자 설정에 저장하고, 공유 세션에서는 마지막 선택값을 공용 설정에 저장하여 모든 사용자가 같은 옵션을 사용합니다.

## Reference Programs

- `.examples/`는 참고 전용이며 Lumina Agent의 구성요소가 아닙니다.
- `.examples/`를 확인하거나 다룰 때는 `.examples/AGENTS.md`를 따릅니다.
- 참고 프로그램을 import, 빌드, 테스트, 패키징 또는 배포 대상에 포함하지 않습니다.

## Changes

- 현재 요청에 필요한 범위만 변경합니다.
- Windows와 Linux에서 모두 동작할 수 있도록 경로와 실행 환경을 처리합니다.
- 사용자별 `AGENTS.md`는 프로젝트 루트 규칙을 대체하지 않으며 허용된 사용자 설정만 추가할 수 있습니다.
- 공유 모드에서도 비밀값, 인증 정보, 사용자별 `AGENTS.md`와 개인 계정 정보는 공유하지 않습니다.
- 새 옵션을 만들 때는 저장 위치, 기본값, 복원 시점과 유효하지 않은 값의 fallback을 함께 설계합니다.
- Provider, Model, Effort를 포함한 선택값은 서버 DB를 원본으로 사용합니다. 개인 모드는 사용자 설정, 공유 모드는 공유 작업공간 설정에 저장하며 브라우저 저장소에만 의존하지 않습니다.
- 비밀번호, 토큰, 일회성 확인, 위험 작업 승인과 임시 실행 상태는 마지막 선택값으로 자동 저장하지 않습니다.

## CodeGraph

- 코드 수정, 리뷰, 리팩터링과 영향 범위 조사에서는 기존 CodeGraph 인덱스의 조회를 우선 활용합니다.
- 여러 파일이 얽힌 작업에서는 `codegraph_context`, `codegraph_search`, `codegraph_callers`, `codegraph_callees`와 `codegraph_impact`를 실제 파일 확인과 함께 사용합니다.
- 순수 문구 수정이나 영향 범위가 명백한 국소 변경에는 CodeGraph 조회를 생략할 수 있습니다.
- 그래프가 없거나 오래된 것으로 보이면 `codegraph_status`와 `.codegraph/codegraph.db` 수정 시각을 확인합니다.
- `.examples/`, `data/`, 비밀 정보와 생성 산출물은 CodeGraph 인덱스에 포함하지 않습니다.
- 재인덱싱은 사용자가 요청했거나 최신 그래프가 작업 안전성에 필요한 경우에만 수행합니다.

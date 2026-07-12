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
- Provider별 초기 Model, 표시명·runtime ID mapping, 기본값과 갱신 정책은 `docs/LUMINA_DETAILED_DESIGN.md` 12.3을 따르며 신규 발견 Model을 자동 활성화하지 않습니다.
- Plugin, Skill과 MCP 자원은 `extensions/`에 둡니다.
- Skill·MCP Marketplace의 관리 화면, 카탈로그, 설치·해제, Fork, 불변 버전, 검토와 Secret binding을 구현·리뷰할 때는 `docs/project-context/EXTENSION_MARKETPLACE.md`와 `.examples/AI_Skill_MarketPlace/`를 함께 참고합니다. 예제는 참고 전용이며 Lumina runtime에 import하거나 build·package·deploy 대상으로 포함하지 않습니다.
- Harness 대화에서 만든 Skill WorkingDraft는 소유자의 실제 Run에 즉시 사용할 수 있어야 하며, Run은 정확한 draft revision과 digest를 고정합니다. Draft autosave는 공개 version을 만들지 않고 사용자가 명시적으로 저장할 때만 immutable `v1`, `v2`, `v3`를 생성합니다. 새 Skill은 기본 Private이고 공용 공개는 admin 또는 Marketplace Auto permission 정책을 따릅니다.
- 활성 WorkingDraft는 candidate, Composer·채팅 pill, Skill 결과 card와 Run detail에서 `Draft rN`으로 명확히 표시하고 `v1로 저장` 또는 `새 버전으로 저장` action을 제공하여 미저장 Draft 사용 사실을 숨기지 않습니다.
- Skill이 많아질 때는 논리적 Skill Folder tree로 계층화합니다. Folder·Skill 이동은 배치 metadata만 변경하고 Skill stable ID, Draft revision, immutable version, digest, installation과 Run snapshot을 바꾸지 않습니다. scope를 넘는 이동은 단순 drag가 아니라 Project 배치 또는 공용 공개 workflow를 사용합니다.
- Agent 실행은 `docs/project-context/AGENT_LOOP.md`의 반복, 권한, 제한, 중단·재개와 이벤트 규칙을 따릅니다.
- 한 사용자는 서로 다른 채팅 세션에서 Agent Run을 병렬 실행할 수 있어야 하며, 실행 잠금은 사용자 전체가 아니라 채팅 세션 단위로 적용합니다.
- 같은 채팅 세션에는 기본적으로 동시에 하나의 Agent Run만 허용하고 추가 요청은 Queue로 처리합니다.
- 사용자가 다른 세션으로 이동하거나 브라우저 연결을 종료해도 Backend의 Run은 계속 실행되고 재접속 시 상태를 복구해야 합니다.
- 실행 중인 세션으로 돌아오면 부분 응답, 현재 Step, Tool 진행 상태와 경과 시간이 끊김 없이 복원되어 사용자가 계속 보고 있었던 것처럼 보여야 합니다.
- Frontend의 세션 전환은 Run을 소유하거나 중단하지 않습니다. Backend snapshot과 순번이 있는 event replay를 기준으로 누락·중복 없이 다시 연결합니다.
- 채팅 Composer는 `@파일명` Context 연결과 `$Skill`·`$MCP` 명시 호출을 지원해야 하며, 상세 계약은 `docs/project-context/HERMES_USER_FEATURES.md`를 따릅니다.
- Frontend가 보낸 파일 경로나 Skill·MCP 이름을 신뢰하지 말고 Backend에서 사용자·조직·공유 범위와 권한을 다시 검증합니다.
- Project, 다단계 Plan, 파일 Workspace, 전문 산출물, 동적 Tool 접근, 예약 작업과 Live Artifact 구현은 `docs/project-context/COWORK_FEATURE_REQUIREMENTS.md`를 따릅니다.
- 사용자가 파일 유형을 지정하지 않고 보고서 작성을 요청하면 독립 실행 가능한 HTML 보고서를 기본 산출물로 생성합니다. 사용자가 DOCX, XLSX, PPTX, PDF, Markdown 등 다른 형식을 명시하면 해당 형식을 우선합니다.
- 기본 업무 계층은 `Organization → Project → Session → Run`이며 Project별 파일·지침·기억·허용 확장을 격리합니다.
- 외부 시스템 연결은 전용 Connector/API, MCP, Browser 자동화, Computer Use 순서로 우선합니다.
- P-GPT, 회사 CA, proxy와 Web Search 구현은 `docs/project-context/PGPT_CORPORATE_NETWORK.md`를 따릅니다.
- TLS 오류를 `verify=False`로 우회하지 않고 public CA와 company CA를 결합한 Trust Manager를 사용합니다.
- P-GPT의 실제 인증 envelope 필드와 환경변수 계약은 `PGPT_CORPORATE_NETWORK.md`대로 구현하되 실제 credential·사번·인증서 원문은 공개 저장소·로그·Run event에 기록하지 않습니다.
- P-GPT endpoint는 MyHarness와 동일한 기본값을 사용하고 `PGPT_BASE_URL`은 선택적 관리자 override로만 제공합니다. 일반 사용자는 입력하지 않아도 됩니다.
- 개발 DB는 SQLite를 사용하되 PostgreSQL 이전 가능성을 유지합니다.
- 실제 데이터, 인증서, API 키와 사용자 비밀값을 Git에 커밋하지 않습니다.
- 사용자 데이터는 기본적으로 격리하며, 명시적으로 활성화된 공유 모드에서만 대화와 artifacts를 사용자 간 공유합니다.
- 개인 세션에서는 마지막 선택값을 사용자 설정에 저장하고, 공유 세션에서는 마지막 선택값을 공용 설정에 저장하여 모든 사용자가 같은 옵션을 사용합니다.

## Reference Programs

- `.examples/`는 참고 전용이며 Lumina Agent의 구성요소가 아닙니다.
- `.examples/`를 확인하거나 다룰 때는 `.examples/AGENTS.md`를 따릅니다.
- 참고 프로그램을 import, 빌드, 테스트, 패키징 또는 배포 대상에 포함하지 않습니다.

## Test Runtime Ports

- Codex와 자동화 도구가 테스트·QA·화면 점검을 위해 Lumina를 실행할 때 사용자의 기본 실행 포트 `5252`와 `5253`을 사용하거나 점유·종료하지 않습니다.
- 테스트 실행에는 기본적으로 `LUMINA_FRONTEND_PORT=15252`, `LUMINA_BACKEND_PORT=15253`을 Process Environment로 지정합니다. 해당 포트가 이미 사용 중이면 `5252`, `5253`을 제외한 다른 빈 포트 쌍을 선택합니다.
- 테스트를 위해 `run_lumina.bat` 또는 `run_lumina_dev.bat`를 그대로 실행하지 않습니다. 이 실행기는 설정된 포트의 기존 listener를 종료할 수 있으므로, 테스트 전용 포트를 명시한 격리된 Process Environment에서만 사용합니다.
- 테스트 종료 시에는 해당 테스트가 직접 시작한 process만 종료합니다. 테스트 시작 전에 이미 실행 중이던 listener와 사용자가 실행한 Lumina process는 종료하지 않습니다.
- 브라우저 기반 UI 점검과 API 검증은 실제로 선택한 테스트 전용 Frontend·Backend URL을 대상으로 수행합니다.
- 단, 작업과 테스트가 모두 완료된 뒤 `.py` 등 재시작해야 반영되는 변경을 사용자의 실제 실행 환경에 적용할 때는 예외적으로 사용자가 실행한 `5252` 또는 `5253` Lumina process를 재시작할 수 있습니다. 이 예외는 변경 반영을 위한 최종 재시작에만 적용하며, 재시작한 포트와 결과를 사용자에게 알립니다.

## Changes

- 현재 요청에 필요한 범위만 변경합니다.
- 사용자에게 보이는 세로·가로 스크롤 영역은 브라우저 기본 스크롤바를 그대로 노출하지 않습니다. `scrollbar-width: thin`과 투명 track을 기본으로 하고, thumb는 현재 테마의 `--cobalt`를 `color-mix`한 공용 스타일을 사용합니다. 다크 테마에서도 같은 색상 토큰으로 명도만 조정하며, 특정 화면마다 임의의 회색·고정 색상 스크롤바를 새로 만들지 않습니다.
- Windows와 Linux에서 모두 동작할 수 있도록 경로와 실행 환경을 처리합니다.
- 사용자별 `AGENTS.md`는 프로젝트 루트 규칙을 대체하지 않으며 허용된 사용자 설정만 추가할 수 있습니다.
- 공유 모드에서도 비밀값, 인증 정보, 사용자별 `AGENTS.md`와 개인 계정 정보는 공유하지 않습니다.
- 새 옵션을 만들 때는 저장 위치, 기본값, 복원 시점과 유효하지 않은 값의 fallback을 함께 설계합니다.
- Provider, Model, Effort를 포함한 선택값은 서버 DB를 원본으로 사용합니다. 개인 모드는 사용자 설정, 공유 모드는 공유 작업공간 설정에 저장하며 브라우저 저장소에만 의존하지 않습니다.
- 비밀번호, 토큰, 일회성 확인, 위험 작업 승인과 임시 실행 상태는 마지막 선택값으로 자동 저장하지 않습니다.
- 이름·라벨·제목처럼 화면에 표시된 값을 수정하는 UI는 별도 modal이나 편집 화면보다 WYSWYR(보이는 자리에서 직접 수정) 방식을 우선합니다. 표시값을 누르면 같은 위치에서 입력 상태로 전환하고, 저장·취소·오류 상태도 그 자리에서 보여줍니다.
- 사용자 삭제 동작은 별도 브라우저 팝업이나 modal을 열지 않습니다. 첫 클릭에는 같은 화면의 해당 삭제 버튼을 경고 상태와 `한 번 더 눌러 삭제` 안내로 바꾸고, 같은 버튼의 두 번째 클릭에만 삭제를 실행합니다. 대상이나 화면이 바뀌면 확인 상태를 해제하며 실행 중 상태와 오류를 같은 위치에 표시합니다.

## CodeGraph

- 코드 수정, 리뷰, 리팩터링과 영향 범위 조사에서는 기존 CodeGraph 인덱스의 조회를 우선 활용합니다.
- 여러 파일이 얽힌 작업에서는 `codegraph_context`, `codegraph_search`, `codegraph_callers`, `codegraph_callees`와 `codegraph_impact`를 실제 파일 확인과 함께 사용합니다.
- 순수 문구 수정이나 영향 범위가 명백한 국소 변경에는 CodeGraph 조회를 생략할 수 있습니다.
- Codex가 코드 작업을 시작할 때 `codegraph_status`와 `.codegraph/codegraph.db` 수정 시각으로 graph 존재 여부와 최신성을 먼저 확인합니다.
- graph가 없으면 init하고, 마지막 graph 갱신 뒤 source 또는 Git HEAD가 변경되어 오래된 경우에는 sync한 다음 작업합니다. 두 경우 모두 `powershell -ExecutionPolicy Bypass -File devtools/update_codegraph.ps1`을 사용하며 script가 최초 full build와 이후 증분 update를 자동 선택합니다.
- init 또는 sync 후 `codegraph_status`와 DB 수정 시각을 다시 확인하고, 갱신 실패를 무시한 채 오래된 graph를 근거로 영향 범위를 판단하지 않습니다.
- `.examples/`, `data/`, 비밀 정보와 생성 산출물은 CodeGraph 인덱스에 포함하지 않습니다.

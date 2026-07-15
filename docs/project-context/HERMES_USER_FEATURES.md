> 생성일: 2026-07-12

# Hermes Agent 사용자 체감 기능 분석

## 목적

이 문서는 `.examples/hermes-agent/` 샘플의 Frontend와 Backend 구현을 읽고, Lumina Agent 사용자가 직접 체감할 기능으로 채택한 요구사항을 정리합니다.

Hermes 코드를 Lumina의 구성요소나 런타임 의존성으로 사용하지 않습니다. 기능 아이디어와 동작 계약만 참고하고 Lumina의 다중 사용자 웹 구조에 맞게 독립적으로 구현합니다. 아래 항목은 별도로 제외 또는 후순위라고 명시된 경우를 제외하고 Lumina의 제품 방향에 반영합니다.

## 결론

Hermes에서 Lumina가 가장 먼저 참고할 가치는 도구의 개수가 아니라 다음 사용자 경험입니다.

1. 실행 중인 여러 세션을 자유롭게 오가고 다시 접속해도 상태를 복구하는 경험
2. 과거 대화를 검색·재개·분기·내보내는 세션 관리
3. 생성된 파일·이미지·링크를 한곳에서 찾고 원래 대화로 돌아가는 Artifact Library
4. Agent가 무엇을 하는지 보여주는 Tool·Terminal·승인 UI
5. Provider·Model·사용량·Context 상태를 이해하기 쉽게 노출하는 제어 UI
6. 백그라운드 완료 알림과 자연어 예약 작업
7. 대화에서 축적된 Memory와 Skill을 사용자가 확인하고 통제하는 학습 경험
8. `@파일명`으로 Context를 연결하고 `$이름`으로 Skill·MCP를 명시적으로 호출하는 Composer

Lumina는 개인용 데스크톱 앱이 아니라 다중 사용자 서버이므로 Hermes의 Profile, 로컬 경로와 데스크톱 IPC 개념을 그대로 가져오기보다 사용자·조직·공유 세션·권한·Worker 구조로 재해석해야 합니다.

## 채택 상태

- 1단계 기능은 초기 제품의 필수 범위입니다.
- 2단계 기능은 핵심 채팅 안정화 후 순차적으로 반영합니다.
- 3단계 기능은 권한·감사·복구 체계를 갖춘 뒤 반영합니다.
- “초기에는 가져오지 않을 기능”은 제품 요구사항에서 제외하거나 별도 결정 전까지 보류합니다.

## 1. 여러 세션을 오가도 작업이 계속되는 경험

### Hermes에서 확인한 점

- Desktop에 세션 전환, 세션 상태 cache, route 기반 resume와 session watchdog이 분리되어 있습니다.
- TUI Gateway 이벤트에는 `session_id`가 포함되며 현재 세션과 무관한 이벤트가 화면에 섞이지 않게 처리합니다.
- 최근 세션 자동 재개와 비정상 종료 후 세션 복구 상태를 사용자에게 표시합니다.
- 백그라운드 완료 이벤트와 알림을 현재 화면과 별도로 처리합니다.

주요 참고 위치:

- `.examples/hermes-agent/apps/desktop/src/store/session-switcher.ts`
- `.examples/hermes-agent/apps/desktop/src/app/session/hooks/use-session-state-cache.ts`
- `.examples/hermes-agent/apps/desktop/src/app/session/hooks/use-route-resume.ts`
- `.examples/hermes-agent/ui-tui/src/app/createGatewayEventHandler.ts`

### Lumina에 적용할 기능

- 사이드바에서 세션별 `queued`, `running`, `approval`, `completed`, `failed` 상태를 표시합니다.
- 사용자가 실행 중인 세션을 떠나도 Backend 또는 Worker가 Run을 계속합니다.
- 다른 세션을 열어도 각 세션의 stream과 메시지가 섞이지 않습니다.
- 재접속 시 DB에서 메시지, Run 상태와 마지막 완료 이벤트를 복원합니다.
- 완료된 다른 세션이 있으면 앱 내부 알림을 표시하고 클릭 시 해당 세션으로 이동합니다.
- 실행 중인 세션으로 돌아오면 assistant 부분 응답, 현재 Tool과 Plan 단계가 계속 보고 있었던 것처럼 즉시 복원됩니다.
- 세션별 마지막 event sequence를 기준으로 떠나 있던 동안의 이벤트를 replay하고 live stream에 다시 연결합니다.

### 사용자 가치

사용자는 긴 분석을 기다리며 화면을 붙잡고 있을 필요가 없습니다. 세션 A가 작업하는 동안 세션 B에서 다른 업무를 처리할 수 있습니다.

### 우선순위

최우선입니다. Lumina의 세션별 병렬 실행 설계와 직접 연결됩니다.

### 수용 기준

1. 세션 A의 응답이 streaming 중일 때 세션 B로 이동해도 A의 Run이 계속됩니다.
2. A로 돌아오면 빈 화면이나 처음부터 다시 재생하지 않고 현재까지 생성된 text와 Tool 상태가 즉시 보입니다.
3. 화면을 떠난 동안 완료된 Tool과 artifacts가 빠짐없이 표시됩니다.
4. event replay와 live stream 전환에서 text나 Tool 결과가 중복되지 않습니다.
5. 네트워크를 끊었다 다시 연결해도 동일한 방식으로 현재 상태를 복원합니다.
6. assistant text는 불규칙한 Provider chunk를 그대로 깜박이며 붙이지 않고 점진적으로 표시되며, 완료 시 저장된 최종 text와 정확히 일치합니다.
7. 사용자가 응답 하단을 보고 있을 때 scrollbar는 커지는 streaming tail을 부드럽게 추종합니다.
8. 사용자가 위로 스크롤해 과거 내용을 읽기 시작하면 자동 추종이 중단되고, 하단 근처로 돌아오거나 명시적으로 최신 응답으로 이동할 때만 재개됩니다.
9. 실행 중인 세션으로 돌아왔을 때 replay된 과거 text는 타자 효과 없이 즉시 복원됩니다. 이전에 tail을 추종 중이었다면 이후 live delta부터 현재 하단을 자연스럽게 추종하며, reduced-motion 설정도 준수합니다.
10. 사용자가 과거 내용을 읽는 동안 새 text가 도착하면 위치를 빼앗지 않고 새 내용 affordance를 표시하며, 사용자가 이를 선택하면 최신 응답으로 이동해 추종을 재개합니다.

세부 text reveal, scroll follow 상태 계약과 필수 단위·브라우저 검증 시나리오는 `AGENT_LOOP.md`의 "텍스트 스트리밍과 메시지 하단 추종"을 따릅니다. 참고 구현인 MyHarness에도 연속 streaming follow, 사용자 scroll 의도, 하단 재진입과 세션 복원 동작을 검증하는 컴포넌트 테스트가 있으므로 Lumina에서도 동등한 회귀 방지 범위를 확보합니다.

## 2. 세션 검색·재개·분기·내보내기

### Hermes에서 확인한 점

- SQLite SessionDB가 메시지 전체를 보관하고 FTS5 검색을 제공합니다.
- 세션 제목, Provider·Model 설정, 비용, parent session 관계를 함께 저장합니다.
- `/resume`, history, title, branch 같은 기능이 동일한 세션 저장소를 사용합니다.
- Desktop에는 세션 검색, branch tree, export와 session picker가 별도 모듈로 존재합니다.
- CJK 부분 검색을 위한 trigram FTS fallback까지 고려되어 있습니다.

주요 참고 위치:

- `.examples/hermes-agent/hermes_state.py`
- `.examples/hermes-agent/apps/desktop/src/lib/session-search.ts`
- `.examples/hermes-agent/apps/desktop/src/lib/session-branch-tree.ts`
- `.examples/hermes-agent/apps/desktop/src/lib/session-export.ts`
- `.examples/hermes-agent/apps/desktop/src/app/session-picker-overlay.tsx`

### Lumina에 적용할 기능

- 제목과 메시지 내용을 동시에 검색합니다.
- 한국어 검색을 고려해 SQLite FTS 사용 가능 여부를 검증하고 단순 LIKE fallback을 둡니다.
- 세션을 복제하거나 특정 메시지에서 분기하여 원본을 보존한 채 다른 접근을 시도할 수 있게 합니다.
- 대화를 JSON 또는 Markdown으로 내보내고 관련 artifacts를 함께 묶을 수 있게 합니다.
- 검색 결과에서 일치 문장, 세션 제목, 날짜, 사용자와 Provider를 보여줍니다.

### 긴 대화와 세션 목록의 점진 로딩 설계

채팅 본문과 좌측 세션 목록은 전체 데이터를 한 번에 내려받지 않습니다. 두 영역은 서로 독립된 cursor pagination을 사용하며, Frontend가 이미 받은 항목만 다시 정렬하거나 검색하는 방식에 의존하지 않습니다.

#### 채팅 본문 로딩 단위

채팅 본문의 pagination 단위는 개별 Message가 아니라 하나의 **대화 Turn Set**입니다.

```text
Turn Set
├─ 사용자의 질문 또는 후속 지시 1개
├─ 해당 요청에서 발생한 assistant 진행 과정
│  ├─ 부분 응답
│  ├─ Plan·Step 상태
│  ├─ Tool·Skill·MCP 호출과 공개 가능한 결과
│  └─ 승인·중단·재개 상태
└─ 해당 요청의 최종 assistant 답변
```

- 세션을 처음 열면 가장 최근 Turn Set 3개를 기본으로 불러옵니다.
- 사용자가 메시지 영역의 위쪽으로 스크롤하면 바로 앞의 Turn Set을 오래된 방향으로 순차 로딩합니다. 한 Turn Set은 중간에서 잘라 내려받지 않습니다.
- Backend는 `before_cursor`, `limit_turn_sets`, `has_more_before`를 기준으로 응답하며 cursor는 Message 개수나 화면 index가 아닌 안정적인 서버 발급값을 사용합니다.
- 새 메시지와 live Run event는 하단에 계속 결합하되, 과거 Turn Set 로딩과 같은 Message 또는 event가 중복되지 않도록 `message_id`, `run_id`, event sequence로 병합합니다.
- 위쪽에 과거 Turn Set을 삽입한 뒤에도 사용자가 보고 있던 첫 visible Message의 위치를 유지합니다. 과거 항목 추가 때문에 화면이 갑자기 위나 아래로 튀지 않아야 합니다.
- 새로고침·세션 복귀 시에는 최근 3개를 무조건 다시 보여주는 데서 끝내지 않고, 현재 Run snapshot과 event replay를 결합해 진행 중인 Turn Set을 정확히 복원합니다.
- 질문 없이 생성된 system notice나 세션 상태 event는 가장 가까운 관련 Turn Set에 포함합니다. 독립적으로 보존해야 하는 event는 별도 system Turn Set으로 취급하여 누락하지 않습니다.

#### 좌측 세션 목록 로딩

- 좌측 패널을 처음 열 때는 현재 viewport를 채울 수 있는 수량만 요청합니다. Frontend가 패널 높이와 행 높이로 초기 `limit`을 계산하되 Backend는 최소·최대 허용 범위를 적용합니다.
- 사용자가 목록 아래쪽으로 스크롤하면 다음 cursor를 사용해 더 오래된 세션을 추가로 가져옵니다.
- 기본 정렬은 `즐겨찾기 우선 → 최근 활동 시각 내림차순 → session_id`의 안정적인 순서로 고정합니다. 같은 시각의 세션이나 로딩 중 갱신된 세션 때문에 누락·중복이 생기지 않아야 합니다.
- 즐겨찾기 변경, 제목 수정 또는 새 활동으로 정렬 위치가 바뀌면 해당 행을 낙관적으로 갱신할 수 있지만, Backend 응답을 원본으로 삼아 목록 cursor를 재검증합니다.
- 세션을 전환해도 각 세션의 Run은 Backend에서 계속되며, 목록의 점진 로딩 여부가 Run 소유권이나 실행 상태에 영향을 주지 않습니다.

#### 좌측 패널 제목 검색

좌측 패널의 검색은 빠른 세션 이동을 위한 **세션 제목 전용 검색**입니다. 위의 제목·메시지 내용 통합 검색과 UI 및 API 목적을 구분합니다.

- 검색어는 Backend에 보내며, 현재 브라우저가 아직 로딩하지 않은 세션도 전체 허용 범위에서 찾습니다.
- 검색은 대소문자를 구분하지 않고 앞뒤 공백과 연속 공백을 정규화합니다. 한국어와 부분 문자열 검색을 지원합니다.
- 검색 결과도 cursor pagination을 사용하며 기본 세션 목록의 cursor와 섞지 않습니다.
- 검색어가 비어 있으면 기존 기본 목록과 scroll 위치로 돌아갑니다. 검색 결과를 기본 목록 데이터에 임의로 합쳐 정렬을 깨뜨리지 않습니다.
- Backend는 현재 사용자·조직·Project·공유 모드의 권한 범위를 먼저 적용한 뒤 제목을 검색합니다. 권한 없는 세션의 존재, 제목 또는 결과 개수를 노출하지 않습니다.

#### 세션별 더보기 메뉴

새 세션의 기본 제목이 `제목 없음` 또는 `새 작업`인 경우 사용자가 첫 메시지를 전송하는 즉시, 네트워크 응답을 기다리지 않고 그 입력을 공백 정규화한 최대 60자의 **임시 제목**으로 상단과 Sidebar에 표시합니다. Run 생성이 실패하면 원래 placeholder로 되돌리고, 성공하면 같은 값을 서버에도 저장해 새로고침·다른 기기에서 복원합니다. 첫 답변을 생성하는 동일한 LLM 호출은 visible answer나 Tool Call보다 먼저 `{"session_title":"..."}` JSON 제어행을 출력하며, Backend는 이 행을 사용자 응답에서 제거하고 검증한 제목만 `conversation_title_updated` event와 Session revision으로 저장·전달합니다. 별도 제목 생성 호출은 하지 않습니다. JSON이 없거나 유효하지 않으면 임시 제목을 안전한 fallback으로 유지하고, 생성 결과가 오기 전에 사용자가 제목을 수정했다면 snapshot의 임시 값과 revision이 달라지므로 LLM 제목으로 덮어쓰지 않습니다.

각 세션 행의 오른쪽에는 `…` 더보기 버튼을 두고 다음 작업을 제공합니다.

- **즐겨찾기/즐겨찾기 해제**: 서버 DB에 세션 속성으로 저장하며 다른 기기와 재접속 후에도 복원합니다. 즐겨찾기 세션은 기본 목록 상단 그룹 안에서 최근 활동 순으로 정렬합니다.
- **제목 수정**: 현재 제목을 입력값으로 연 inline dialog를 제공하고 저장·취소를 지원합니다. Backend는 공백 제거, 빈 제목 거부, 최대 길이와 허용 문자를 검증하며 성공한 제목을 검색 index에도 즉시 반영합니다.
- **삭제**: 별도 브라우저 팝업이나 modal을 열지 않습니다. 첫 클릭에는 같은 메뉴의 삭제 버튼을 경고 상태와 `한 번 더 눌러 삭제` 안내로 바꾸고, 같은 버튼의 두 번째 클릭에만 삭제합니다. 다른 대상·화면으로 이동하거나 메뉴를 닫으면 확인 상태를 해제합니다. 실행 중이거나 승인 대기·Queue가 남은 세션은 바로 삭제하지 않고 먼저 Run과 Queue를 중단해야 함을 같은 화면에서 알립니다. 삭제 성공 후 목록, 제목 검색 결과와 현재 선택 상태에서 제거하고, 현재 열어 둔 세션이었다면 안전한 빈 채팅 또는 다음 세션으로 이동합니다.

더보기 버튼은 행 선택과 별개의 keyboard focus와 접근성 이름을 가지며, 버튼을 누르는 동작 자체가 세션을 열지 않아야 합니다. 메뉴를 닫아도 세션 목록의 scroll 위치를 유지합니다.

#### API 응답 계약 예시

```text
GET /sessions?cursor=...&limit=...
→ items[], next_cursor, has_more

GET /sessions/search?title_query=...&cursor=...&limit=...
→ items[], next_cursor, has_more

GET /sessions/{session_id}/turn-sets?before_cursor=...&limit_turn_sets=3
→ turn_sets[], previous_cursor, has_more_before

PATCH /sessions/{session_id}
→ title 또는 is_favorite 변경

DELETE /sessions/{session_id}
→ 실행 상태와 권한 검증 후 삭제
```

실제 endpoint 이름은 Backend routing 규칙에 맞게 조정할 수 있지만, 서버 검색·독립 cursor·권한 검증·Turn Set 원자성은 유지합니다.

#### 검증 기준

1. 수천 개의 세션이 있어도 첫 화면 요청은 좌측 viewport를 채울 수량만 반환합니다.
2. 아직 좌측 목록에 로딩하지 않은 세션도 제목 검색으로 찾을 수 있습니다.
3. 매우 긴 세션을 열면 최근 Turn Set 3개만 먼저 반환하고, 위로 스크롤할 때 이전 Turn Set이 중복·누락 없이 추가됩니다.
4. 과거 Turn Set 추가 전후에 사용자가 읽던 Message의 화면상 위치가 유지됩니다.
5. 즐겨찾기, 제목 수정과 삭제 결과가 새로고침·재접속 후에도 서버 상태와 일치합니다.
6. 개인 세션과 권한 없는 공유 세션은 기본 목록, 제목 검색과 mutation API 어디에서도 노출되거나 변경되지 않습니다.
7. 실행 중 세션을 삭제하려 할 때 Run이나 Queue를 고아 상태로 남기지 않습니다.

### 사용자 가치

과거에 수행한 분석을 다시 찾거나 좋은 대화를 기반으로 새로운 작업을 시작하기 쉬워집니다.

### 주의점

공유 모드에서는 검색 결과도 공유 범위와 권한을 따라야 합니다. 개인 세션이 다른 사용자 검색 결과에 노출되면 안 됩니다.

## 3. Artifact Library

### Hermes에서 확인한 점

- Desktop에 Artifacts 전용 화면이 존재합니다.
- 이미지, 파일과 링크를 구분해 필터링하고 검색·페이지네이션을 제공합니다.
- Artifact가 생성된 세션 제목과 시간을 표시합니다.
- Artifact에서 원래 채팅으로 바로 이동할 수 있습니다.
- 원격 이미지의 thumbnail을 파일 bridge를 통해 표시하는 경로도 있습니다.

주요 참고 위치:

- `.examples/hermes-agent/apps/desktop/src/app/artifacts/index.tsx`
- `.examples/hermes-agent/apps/desktop/src/app/artifacts/artifact-utils.ts`
- `.examples/hermes-agent/tools/tool_result_storage.py`
- `.examples/hermes-agent/tools/tool_output_limits.py`

### Lumina에 적용할 기능

- 채팅과 별도로 전체 Artifact Library를 제공합니다.
- 이미지, 문서, 코드, 데이터 파일과 링크 유형으로 필터링합니다.
- Artifact 이름, 원본 세션, 생성 사용자, 생성 시각과 크기를 표시합니다.
- Artifact를 클릭하면 preview·다운로드·원본 채팅 열기를 제공합니다.
- 공유 모드에서는 공용 Library, 개인 모드에서는 사용자 Library를 보여줍니다.
- 큰 Tool 결과는 채팅에 전부 출력하지 않고 artifact로 보관하고 요약만 보여줍니다.

### 사용자 가치

사용자가 생성 결과물을 찾기 위해 긴 대화를 다시 스크롤할 필요가 없습니다. Lumina의 artifacts 공유 모드를 실제로 유용하게 만드는 핵심 화면입니다.

### 우선순위

세션 기본 기능 다음의 높은 우선순위입니다.

## 4. Tool 실행을 이해할 수 있는 채팅 UI

### Hermes에서 확인한 점

- Tool 실행 상태, Terminal 출력, 코드·diff, JSON 문서, 이미지 생성 결과를 서로 다른 UI로 표시합니다.
- 긴 출력은 expandable block이나 log tail로 접고 필요한 부분만 확장합니다.
- 명령 실행 승인 요청을 채팅 흐름 안에서 표시합니다.
- Browser 진행 상황과 Background 완료 상태가 별도 이벤트로 전달됩니다.
- 첨부 대상에 파일·폴더·URL·이미지뿐 아니라 Terminal context도 포함됩니다.

주요 참고 위치:

- `.examples/hermes-agent/apps/desktop/src/components/chat/terminal-output.tsx`
- `.examples/hermes-agent/apps/desktop/src/components/chat/diff-lines.tsx`
- `.examples/hermes-agent/apps/desktop/src/components/chat/expandable-block.tsx`
- `.examples/hermes-agent/apps/desktop/src/components/assistant-ui/tool/approval.tsx`
- `.examples/hermes-agent/apps/desktop/src/app/chat/composer/attachments.tsx`
- `.examples/hermes-agent/apps/desktop/src/app/right-sidebar/terminal/`

### Lumina에 적용할 기능

- Tool Call을 단순 JSON 대신 `대기 → 실행 → 성공/실패` 상태로 표시합니다.
- 파일 수정은 diff, Terminal은 streaming log, 이미지는 thumbnail, 웹 검색은 출처 목록으로 렌더링합니다.
- 위험 작업은 채팅 안에서 승인·거부할 수 있게 합니다.
- 반복되는 Tool Call은 접어서 보여주되 현재 진행 중인 항목은 자동으로 노출합니다.
- 사용자가 이해할 수 있는 상태 문구를 제공하고 내부 event 이름을 그대로 노출하지 않습니다.
- Tool 실행 시간과 실패 이유를 표시합니다.

### 사용자 가치

Agent가 멈춘 것인지 작업 중인지, 무엇을 변경하려는지, 왜 실패했는지를 사용자가 즉시 이해할 수 있습니다.

## 5. Provider·Model 선택과 상태가 명확한 UI

### Hermes에서 확인한 점

- Provider 설정, Model 설정, Model picker, 노출할 Model 선택과 preset이 각각 분리되어 있습니다.
- Provider가 없을 때 설정 진입을 유도하는 onboarding과 오류 안내가 있습니다.
- Context 사용량, Token·비용 기간별 분석과 활성 subagent 수를 노출합니다.
- 설정은 비밀 credential과 일반 동작 옵션을 분리합니다.

주요 참고 위치:

- `.examples/hermes-agent/apps/desktop/src/app/model-picker-overlay.tsx`
- `.examples/hermes-agent/apps/desktop/src/app/settings/providers-settings.tsx`
- `.examples/hermes-agent/apps/desktop/src/app/settings/model-settings.tsx`
- `.examples/hermes-agent/apps/desktop/src/store/model-presets.ts`
- `.examples/hermes-agent/apps/desktop/src/app/shell/context-usage-panel.tsx`
- `.examples/hermes-agent/apps/desktop/src/app/command-center/index.tsx`

### Lumina에 적용할 기능

- Provider → Model → Effort 순서로 선택하고 지원 capability에 따라 옵션을 동적으로 제한합니다.
- 연결 실패, 인증서 문제, 권한 문제와 지원하지 않는 기능을 구분해 안내합니다.
- 마지막 선택값을 private 모드에서는 사용자별, shared 모드에서는 공용으로 복원합니다.
- Provider별 마지막 Model과 Model별 마지막 Effort를 기억합니다.
- 현재 Context 사용률과 자동 압축 여부를 표시합니다.
- 사용량 화면에서 사용자·Provider·Model·기간별 Token과 비용을 확인할 수 있게 합니다.

### 사용자 가치

사용자는 모델 이름만 보고 추측하지 않고, 현재 어떤 설정으로 얼마만큼 사용하고 있는지 이해할 수 있습니다.

## 6. 완료 알림과 Background Run

### Hermes에서 확인한 점

- Gateway event handler가 Background 완료, 일반 알림, 사용량 경고와 승인 요청을 구분합니다.
- Desktop에는 앱 내부 알림과 native notification store가 별도로 있습니다.
- 알림 action에 session ID를 포함해 해당 세션으로 이동할 수 있습니다.

주요 참고 위치:

- `.examples/hermes-agent/ui-tui/src/app/createGatewayEventHandler.ts`
- `.examples/hermes-agent/apps/desktop/src/store/notifications.ts`
- `.examples/hermes-agent/apps/desktop/src/store/native-notifications.ts`
- `.examples/hermes-agent/apps/desktop/src/components/notifications.tsx`

### Lumina에 적용할 기능

- 다른 세션의 작업 완료, 실패와 승인 대기를 알립니다. Context 압축은 종료 알림이 아니라 같은 Run의 진행 상태로 표시합니다.
- 알림을 클릭하면 해당 채팅과 관련 Tool 또는 Artifact 위치로 이동합니다.
- 읽음·안 읽음 상태를 서버에 저장해 다른 PC에서도 동기화합니다.
- 브라우저 알림은 사용자가 명시적으로 허용한 경우에만 사용합니다.

### 사용자 가치

긴 작업을 기다리지 않고 다른 업무를 하다가 결과가 준비되었을 때 돌아올 수 있습니다.

## 7. 자연어 예약 작업

### Hermes에서 확인한 점

- Cron scheduler가 정기 작업을 실행하고 여러 플랫폼으로 결과를 전달합니다.
- Desktop 사이드바와 전용 화면에서 Cron 작업을 관리합니다.
- 일일 보고서, 백업, 주간 감사처럼 unattended 작업을 주요 사용자 기능으로 취급합니다.

주요 참고 위치:

- `.examples/hermes-agent/cron/`
- `.examples/hermes-agent/apps/desktop/src/app/cron/index.tsx`
- `.examples/hermes-agent/apps/desktop/src/app/chat/sidebar/cron-jobs-section.tsx`

### Lumina에 적용할 기능

- 사용자가 자연어로 예약 작업을 만들고 실행 주기를 확인·수정·일시정지할 수 있게 합니다.
- 예약 작업마다 실행할 Agent, Provider·Model·Effort, Tool 범위와 결과 전달 위치를 저장합니다.
- 최근 실행, 다음 실행, 성공·실패와 생성 artifacts를 보여줍니다.
- 공유 모드의 예약 작업 생성·수정은 관리자 또는 허용 역할로 제한합니다.

### 우선순위

핵심 채팅과 Worker가 안정된 뒤 도입합니다. 초기 버전의 필수 기능은 아닙니다.

## 8. Memory와 Skill의 사용자 통제

### Hermes에서 확인한 점

- 세션 검색, 지속 Memory, 사용자 모델링과 Skill 생성을 하나의 학습 loop로 묶습니다.
- Background review가 대화 후 저장할 Memory와 Skill을 검토합니다.
- Desktop에 Skills Hub, Skill 관리와 Memory 연결 화면이 있습니다.
- Background review의 결과를 사용자에게 알리는 경로가 있습니다.

주요 참고 위치:

- `.examples/hermes-agent/agent/memory_manager.py`
- `.examples/hermes-agent/agent/background_review.py`
- `.examples/hermes-agent/apps/desktop/src/app/skills/`
- `.examples/hermes-agent/apps/desktop/src/app/settings/memory/`

### Lumina에 적용할 기능

- Agent가 기억한 내용을 사용자가 조회·수정·삭제할 수 있게 합니다.
- Memory가 어느 대화에서 생성되었는지 출처를 표시합니다.
- 자동 저장, 저장 전 확인, 저장 안 함을 사용자 또는 조직 정책으로 선택할 수 있게 합니다.
- Skill이 추가·변경되면 변경 이유와 적용 범위를 보여줍니다.
- 공유 모드의 공용 Memory와 개인 Memory를 명확히 구분합니다.

### 사용자 가치

사용자는 Agent가 무엇을 기억하는지 알 수 있고 잘못된 기억을 직접 교정할 수 있습니다. 장기적으로 반복 설명이 줄어듭니다.

### 주의점

Hermes처럼 초기부터 자율 Skill 개선을 강하게 도입하면 다중 사용자 환경에서 예측 가능성과 권한 문제가 커집니다. Lumina 초기에는 Memory 조회·수정과 명시적 Skill 설치부터 시작하고 자동 학습은 감사·승인 기능 이후 도입하는 편이 안전합니다. Skill·MCP·Plugin의 작성, 설치 범위, Fork와 불변 버전 누적 계약은 `EXTENSION_MARKETPLACE.md`를 따릅니다.

### Lumina 도입 결정

Hermes의 Memory를 파일이나 외부 Provider 형태로 그대로 복제하지 않고 다음 세 층으로 재해석합니다.

1. **Curated UserMemory**: 사용자 역할·응답 방식·반복 선호처럼 안정된 항목을 구조화해 저장하고 자동 저장·확인·중지 정책과 출처를 유지합니다.
2. **Relevant recall**: Run 생성 시 현재 요청과 관련된 소수의 UserMemory와 Project Memory를 선택해 snapshot으로 고정합니다. 회상 결과는 system prompt를 변경하지 않고 현재 사용자 Context tail에 주입해 prompt cache와 Run 재현성을 함께 보존합니다.
3. **Session search**: 장기 대화 전체를 Memory로 복제하지 않고 기존 대화 검색을 향후 Agent가 호출할 수 있는 읽기 전용 Tool로 확장합니다. “지난번에 무엇을 결정했지?”처럼 정확한 과거 근거가 필요할 때만 사용합니다.

완료 Turn 뒤 학습은 Hermes의 범용 background-review Agent fork 대신 Lumina의 제한된 structured extractor를 유지합니다. extractor는 사용자 작성 Message만 입력받고 Memory 후보 schema만 출력하며 원래 Run의 Message·Session을 쓸 수 없습니다. 외부 Memory Provider는 사내 데이터 반출, 사용자·Project 격리, 삭제 전파와 audit 계약을 만족하는 Adapter가 준비되기 전까지 기본 범위에서 제외합니다.

다음 단계는 lexical overlap만 사용하는 recall을 `정확 키워드 + FTS + 선택적 embedding rerank`로 확장하되, embedding 원문과 query가 승인되지 않은 외부 서비스로 전송되지 않게 하는 것입니다. recall 결과에는 선택 이유와 score를 남겨 운영자가 과잉 회상·누락을 진단할 수 있게 합니다.

## 9. Context 압축과 사용량 설명

### Hermes에서 확인한 점

- 사용자가 직접 Context 압축을 실행하고 현재 사용량을 확인할 수 있습니다.
- Backend가 Context 최대치, 사용률, 압축 횟수와 활성 subagent 수를 계산합니다.
- 장기 세션은 prompt cache를 유지하는 것을 중요한 비용·성능 원칙으로 취급합니다.

주요 참고 위치:

- `.examples/hermes-agent/agent/conversation_compression.py`
- `.examples/hermes-agent/agent/context_compressor.py`
- `.examples/hermes-agent/tui_gateway/server.py`
- `.examples/hermes-agent/apps/desktop/src/app/shell/context-usage-panel.tsx`

### Lumina에 적용할 기능

- Context 사용률을 단순한 진행 막대로 보여줍니다.
- 자동 압축이 발생하면 무엇이 요약되었는지 상태 메시지를 남깁니다.
- 사용자가 필요할 때 수동 압축을 요청할 수 있게 합니다.
- 대화 중 system prompt와 Tool schema를 불필요하게 바꾸지 않아 Provider cache를 활용합니다.
- Codex GPT-5.4·5.5·5.6 계열만 서비스 정책상 272K Context와 85% 자동 압축 임계값을 적용하여 36K 수준에서 원문 prefix와 cache lineage를 불필요하게 끊지 않습니다. P-GPT와 다른 표준 API Provider는 각 API model의 실제 Context window를 사용합니다.
- Provider·Model 변경은 새 Run부터 적용하고 진행 중인 Run의 Context 계약을 바꾸지 않습니다.

### 사용자 가치

긴 대화가 갑자기 실패하거나 비용이 늘어나는 이유를 사용자가 이해할 수 있습니다.

## 10. Onboarding과 상태 진단

### Hermes에서 확인한 점

- Provider 설정이 없을 때 단순 오류 대신 onboarding과 설정 화면으로 연결합니다.
- 설치, 연결, Provider, credential과 업데이트 상태를 별도의 UI로 관리합니다.
- 세션 DB가 불가능할 때도 빈 목록만 보여주지 않고 실제 원인을 사용자에게 전달하려고 합니다.

주요 참고 위치:

- `.examples/hermes-agent/apps/desktop/src/components/onboarding/`
- `.examples/hermes-agent/apps/desktop/src/app/settings/provider-config-panel.tsx`
- `.examples/hermes-agent/apps/desktop/src/components/boot-failure-overlay.tsx`
- `.examples/hermes-agent/hermes_state.py`

### Lumina에 적용할 기능

- 최초 관리자에게 DB, 인증서, Provider와 저장소 연결 상태를 단계별로 안내합니다.
- 일반 사용자에게는 관리자 설정이 필요한 문제와 본인이 해결할 수 있는 문제를 구분합니다.
- P-GPT 연결 실패 시 DNS·CA 인증서·인증·API 경로·Model 배포명 오류를 분리해 보여줍니다.
- `/health` 결과를 그대로 노출하지 않고 사용자용 상태 문구로 변환합니다.

### 사용자 가치

사용자가 검은 오류 화면이나 모호한 “연결 실패” 대신 다음 행동을 알 수 있습니다.

## 11. Command Palette와 빠른 탐색

### Hermes에서 확인한 점

- Desktop Command Palette에서 Terminal, Artifacts, Cron, Usage 등 주요 화면으로 이동할 수 있습니다.
- 세션·모델 picker와 검색 overlay가 별도 UI로 존재합니다.

주요 참고 위치:

- `.examples/hermes-agent/apps/desktop/src/app/command-palette/index.tsx`
- `.examples/hermes-agent/apps/desktop/src/app/model-picker-overlay.tsx`
- `.examples/hermes-agent/apps/desktop/src/app/session-picker-overlay.tsx`

### Lumina에 적용할 기능

- 키보드로 새 채팅, 세션 검색, Model 변경, Artifact 열기와 설정 이동을 실행합니다.
- 명령어를 외워야 하는 slash-command 중심 UX보다 발견 가능한 검색 UI를 우선합니다.
- 관리 권한이 없는 사용자의 관리자 명령은 검색 결과에 노출하지 않습니다.

### 우선순위

기능 수가 늘어 탐색이 어려워지는 시점에 도입합니다.

## 12. `@` 파일 연결과 `$` Skill·MCP 호출

이 기능은 초기 채팅 Composer의 필수 범위로 채택합니다.

### Hermes에서 확인한 점

- Composer가 `@` 입력을 감지해 file, folder, line, terminal 등의 Context 후보를 자동완성합니다.
- 선택된 참조를 편집 불가능한 chip으로 렌더링하면서 실제 전송 text에는 해석 가능한 reference를 유지합니다.
- Drag & Drop으로 들어온 프로젝트 파일은 upload와 workspace reference를 구분합니다.
- Backend가 메시지 안의 Context reference를 파싱하고 허용된 경로의 내용을 Context에 추가합니다.

주요 참고 위치:

- `.examples/hermes-agent/apps/desktop/src/app/chat/composer/hooks/use-at-completions.ts`
- `.examples/hermes-agent/apps/desktop/src/app/chat/composer/hooks/use-composer-trigger.ts`
- `.examples/hermes-agent/apps/desktop/src/app/chat/composer/inline-refs.ts`
- `.examples/hermes-agent/apps/desktop/src/components/assistant-ui/directive-text.tsx`
- `.examples/hermes-agent/agent/context_references.py`

Hermes의 slash command UX는 참고하되 Lumina에서는 Skill과 MCP의 명시 호출 기호로 `$`를 사용합니다.

### 사용자 문법

```text
@보고서.pdf 요약해줘
@분기자료 지난 분기 자료 전체를 참고해줘
@src/main.tsx 이 컴포넌트의 문제를 찾아줘
$web-research 최신 자료를 조사해줘
$internal-search 사내 규정을 찾아줘
```

- `@` 뒤에는 현재 사용자가 접근할 수 있는 파일, 폴더와 artifacts를 검색합니다.
- `$` 뒤에는 현재 사용자의 활성 Skill WorkingDraft와 현재 사용자·Project에서 설치된 Skill·MCP를 함께 검색합니다.
- 자동완성 후보는 Composer 입력란 바로 위에 표시하고 파일·Artifact·Skill·MCP를 이름, 유형 icon, 설명과 상태로 구분합니다. Skill에는 현재 Folder breadcrumb를 보조 정보로 표시합니다.
- 선택된 항목은 Composer와 전송된 user Message에서 이름과 유형 icon이 있는 독립 pill로 표시합니다.
- 키보드 방향키, Enter, Tab과 Escape로 자동완성 목록을 조작할 수 있게 합니다.
- 입력 중인 일반 이메일 주소, 통화 기호와 코드 문자열을 잘못된 trigger로 해석하지 않도록 token 경계에서만 감지합니다.

### `@` 참조 종류

초기 버전은 다음 참조를 지원합니다.

```text
@file       → 업로드 또는 허용된 workspace 파일
@folder     → 사용자가 업로드한 폴더와 선택 시점의 하위 파일 전체
@artifact   → 이전에 생성된 artifact
```

향후 필요하면 특정 line 범위와 terminal snapshot을 추가할 수 있습니다. 사용자가 보는 chip은 `@파일명`, `@폴더명`처럼 단순하게 표시하되 Backend에는 안정적인 reference ID와 종류를 구조화해 전송합니다. 폴더는 논리 경로에서 결정적으로 생성한 ID와 하위 파일 digest snapshot으로 검증합니다.

```text
표시: @매출보고서.xlsx
전송: { type: "file", id: "file_uuid", display_name: "매출보고서.xlsx" }
```

원본 파일명이 같아도 UUID로 구분합니다. 메시지 저장 시 표시 text만 저장하지 않고 구조화된 reference를 함께 저장하여 세션 재개, 공유와 내보내기에서도 연결이 유지되게 합니다.

### `$` 호출 종류

```text
$skill-name    → Skill을 이번 요청에 명시적으로 적용
$mcp-name      → 해당 MCP의 Tool을 이번 요청에서 사용할 수 있게 활성화
```

Skill과 MCP 이름이 충돌하면 자동완성 목록에서 유형을 구분하고 사용자가 선택하게 합니다. text 직접 입력의 모호성을 해소하기 위해 다음 qualified 문법도 지원합니다.

```text
$skill:web-research
$mcp:internal-search
```

`$` 호출은 무조건 Tool을 즉시 실행한다는 의미가 아닙니다. Skill은 해당 요청의 절차와 Context에 명시적으로 포함하고, MCP는 허용된 Tool을 Agent Loop에 노출합니다. 실제 Tool 실행은 모델의 판단과 권한 정책을 따르며 기본 `approval_mode=yolo`에서는 허용 범위 안의 Tool을 별도 확인 없이 실행합니다.

### Frontend 책임

- `@`와 `$` trigger 감지 및 debounce 검색
- 파일·Artifact·Skill·MCP 후보를 유형별로 묶어 표시
- 후보 panel을 Composer 바로 위에 배치하고 높이를 넘으면 내부 scroll 처리
- 접근할 수 없거나 비활성화된 항목을 선택하지 못하게 처리
- 선택 항목을 chip으로 렌더링하고 삭제·재선택 지원
- message 전송 전에 reference와 invocation의 구조화 payload 생성
- 세션 재개 시 저장된 chip 복원
- 전송된 채팅 Message에서 reference token 구간만 inline pill로 렌더링하고 click 시 file Preview 또는 Skill·MCP 상세 표시
- 공유 Project에서 허용된 Skill·MCP와 artifacts의 공개 범위 표시

### Backend 책임

- 사용자·조직·Project scope 기준 검색 후보 필터링
- reference ID를 서버 측에서 다시 검증하고 안전한 파일 경로 또는 Object Storage key로 해석
- 파일 크기, 형식, Token 예산과 악성 콘텐츠 정책 적용
- Skill 전체 지침을 필요한 시점에 읽고 출처와 버전을 Run snapshot에 기록
- MCP 연결 상태, 허용 Tool과 사용자 권한 검증
- 명시 호출된 Skill·MCP를 Run 옵션 snapshot에 고정
- 접근 거부, 삭제된 파일과 연결 실패를 사용자용 오류로 반환
- 누가 어떤 파일·Skill·MCP를 참조했는지 감사 기록

### 보안과 Project 공유

- Frontend가 보낸 raw path를 신뢰하지 않습니다.
- 사용자가 접근 가능한 workspace root와 Object Storage 범위 안에서만 파일을 해석합니다.
- `../`, 절대경로와 symbolic link를 이용한 범위 탈출을 차단합니다.
- 개인 모드의 파일·Skill·MCP 선택은 다른 사용자에게 노출하지 않습니다.
- 공유 Project에서는 공용으로 허용된 파일·artifacts·Skill·MCP만 구성원에게 보입니다.
- 개인 credential이 필요한 MCP는 공유 Project에서도 credential 자체를 공유하지 않습니다.
- 메시지를 나중에 다시 열었을 때 권한이 사라졌다면 metadata는 표시하되 내용 재조회는 차단합니다.

### 사용자 가치

사용자는 파일 선택 버튼을 반복해서 누르거나 “이전에 만든 파일”을 장황하게 설명하지 않아도 됩니다. Skill과 MCP도 설정 화면을 오가지 않고 현재 요청에서 명확하게 지정할 수 있습니다.

## Frontend 권장 구성

```text
Frontend
├─ Chat Workspace
│  ├─ 세션 상태가 표시되는 Sidebar
│  ├─ 메시지와 Tool Timeline
│  ├─ 첨부·승인·중단 Composer
│  └─ Context·Provider 상태
├─ Artifact Library
├─ Session Search / Branch / Export
├─ Notifications
├─ Provider / Model Settings
├─ Usage
├─ Skills / Memory
└─ Scheduled Jobs
```

상태는 하나의 거대한 React hook에 몰지 않고 세션, stream, notifications, models와 artifacts가 각자 store와 action을 소유하게 합니다. 현재 보고 있는 세션의 UI state와 서버가 소유하는 Run state를 분리해야 합니다.

## Backend 권장 구성

```text
Backend
├─ Session Service
│  ├─ 검색·재개·분기·내보내기
│  └─ private/shared 권한 필터
├─ Run Service
│  ├─ 세션별 lock과 사용자별 동시 실행 한도
│  ├─ Queue·취소·재개
│  └─ Event 저장과 stream 전달
├─ Artifact Service
│  ├─ 저장·검색·preview·download
│  └─ 원본 세션 연결
├─ Approval Service
├─ Notification Service
├─ Provider / Usage Service
├─ Memory / Skill Service
└─ Scheduler Service
```

SSE 또는 WebSocket은 화면 전달 수단일 뿐 실행 상태의 원본이 아닙니다. 세션, Run, 승인, 알림과 artifacts는 DB 및 스토리지에 저장하고 재접속 시 복구합니다.

## 추천 도입 순서

### 1단계: 사용자가 바로 체감하는 기본기

1. 세션별 병렬 Run과 상태 표시
2. 재접속 복구와 완료 알림
3. 세션 검색·제목·재개
4. Tool 상태·오류·승인 UI
5. Provider·Model·Effort 선택과 마지막 값 복원
6. 첨부 파일과 기본 Artifact 저장
7. `@파일명` Context 연결과 `$Skill`·`$MCP` 호출

### 2단계: 작업 관리 경험

1. Artifact Library
2. 세션 분기와 내보내기
3. Context 사용률과 압축 안내
4. 사용량·비용 화면
5. 자연어 예약 작업

### 3단계: 학습과 확장

1. Memory 조회·수정·삭제
2. Skill Hub와 설치 관리
3. 공용 Memory와 개인 Memory 분리
4. 승인 가능한 Background review
5. Command Palette

## 초기에는 가져오지 않을 기능

- Telegram·Discord 등 다수 메시징 채널: Lumina의 웹 다중 사용자 경험이 안정된 뒤 검토합니다.
- 데스크톱 Profile과 로컬 IPC: Lumina에서는 사용자·조직·공유 작업공간으로 대체합니다.
- 여섯 종류의 Terminal backend: 우선 회사 Linux Worker와 제한된 Terminal 도구에 집중합니다.
- 자동 Skill 자기개선: 다중 사용자 감사·승인·rollback이 준비되기 전에는 도입하지 않습니다.
- 게임화와 Achievement: 핵심 업무 생산성에 직접 기여하지 않으므로 초기 범위에서 제외합니다.
- 대규모 Tool 기본 노출: Tool schema는 비용과 Context를 차지하므로 필요한 Tool만 capability와 정책에 따라 노출합니다.
- 설치된 MCP schema가 모델 Context의 10%를 넘는 Run은 core Tool과 `tool_search`·`tool_describe`·`tool_call`만 모델에 노출하고, Run snapshot에 고정된 허용 catalog를 필요할 때 검색합니다. bridge 호출도 직접 MCP 호출과 동일한 권한·승인·감사 경계를 우회할 수 없습니다.

## Hermes에서 가져갈 설계 원칙

### 긴 대화의 Context를 불필요하게 흔들지 않기

대화 도중 system prompt와 Tool 목록을 계속 재구성하면 Provider prompt cache가 깨지고 속도와 비용이 악화될 수 있습니다. Run 시작 시 옵션 snapshot을 고정하고 필요한 변경은 다음 Run부터 적용합니다.

Tool 결과도 개별 호출 제한만으로는 충분하지 않습니다. 여러 중간 크기 결과가 한 Turn에 합쳐질 때 전체 합계 예산을 적용하고, 원문은 Run에 보존한 채 bounded preview와 같은 Run 전용 readback 참조만 Provider에 전달합니다.

### 핵심은 좁게, 기능은 확장 영역에 두기

사용자가 체감하는 기능을 모두 Agent core Tool로 추가하지 않습니다. 기존 Tool 확장, Skill, Plugin, MCP 순서로 구현 위치를 결정하고 거의 모든 사용자에게 필요한 기능만 core에 둡니다.

### 실패를 숨기지 않기

세션 DB, Provider, Tool 또는 stream이 실패했을 때 빈 화면이나 무한 loading으로 보이지 않게 합니다. Backend가 원인을 분류하고 Frontend가 사용자가 취할 수 있는 다음 행동을 보여줍니다.

### Snapshot보다 행동 계약 테스트

Model 목록 개수 같은 현재 값보다 “선택 가능한 모든 Model에 capability 정보가 있다”, “모든 Tool Call에는 Tool Result가 있다”, “권한 없는 사용자는 개인 세션을 검색할 수 없다” 같은 관계와 불변 조건을 테스트합니다.

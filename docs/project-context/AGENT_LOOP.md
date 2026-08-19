> 생성일: 2026-07-11

# Agent Loop

Lumina Agent의 Harness는 사용자 요청을 한 번의 모델 호출로 끝내지 않고, 모델이 최종 답변을 반환할 때까지 모델 호출과 Tool 실행을 반복하는 Agent Loop를 사용합니다.

이 문서는 `.examples/OpenHarness/`의 Agent Loop 개념을 참고하되 Lumina Agent의 다중 사용자, Provider 추상화, 공유 세션과 서버 운영 요구사항에 맞게 독립적으로 정의한 설계 기준입니다.

## 기본 흐름

```text
사용자 메시지
→ 실행 옵션과 대화 Context 고정
→ Provider에 메시지와 Tool 목록 전달
→ 응답 Stream 처리
→ 최종 답변이면 저장 후 종료
→ Tool Call이면 검증·권한 확인·실행
→ Tool Result를 대화에 추가
→ Provider를 다시 호출
→ 종료 조건까지 반복
```

Harness가 실행 방법과 안전을 책임지고, 모델은 다음 행동 또는 최종 답변을 선택합니다.

## 상태

Agent Run은 최소한 다음 상태를 가집니다.

```text
queued
→ preparing
→ model_streaming
→ awaiting_approval | awaiting_input
→ tools_running
→ model_streaming
→ completed | failed | cancelled | interrupted
```

상태 변경과 주요 이벤트를 DB에 기록하고 SSE 또는 WebSocket으로 Frontend에 전달합니다. Backend나 Worker가 재시작되어도 저장된 상태를 기준으로 실패 여부를 판단하거나 안전하게 이어갈 수 있어야 합니다.

각 Run은 생성 시 조직의 관리자 실행 안전 한도와 전역 YOLO mode를 snapshot으로 고정합니다. 기본값은 Run당 400 model Turn, 총 4,000,000 Token, 시작 후 10,080분(7일), 예상 비용 $100, YOLO mode 사용이며 관리자가 `설정 → 관리자 설정`에서 모두 조정할 수 있습니다. YOLO mode를 사용하면 모든 Tool 작업을 승인 요청 없이 실행하고, 사용하지 않으면 위험 기반 승인을 적용합니다. 권한·Project 격리·sandbox 경계와 Secret 비저장 정책은 두 모드에서 모두 유지합니다. 한도와 모드는 Session 누적이 아니라 Run마다 새로 계산하고, 변경된 설정은 새 Run부터 적용합니다. 한도에 도달하면 부분 결과, 사용량과 checkpoint를 보존한 채 `limit_reached`로 종료합니다. Context가 모델 입력 창에 가까워지면 원본 메시지와 Tool 실행 근거는 저장소에 유지한 채 이전 대화와 진행 상태를 복구 가능한 요약으로 압축하고, 최신 메시지와 미완료 Plan을 보존하여 같은 Run의 다음 Turn을 계속합니다. 압축은 `context_compacted` 이벤트와 revision·source hash를 남겨 재접속과 감사 시 동일한 진행 상태를 복원할 수 있어야 합니다.

## 한 Turn의 처리

1. 시스템·조직·Agent·사용자 지침과 대화 기록을 조합합니다.
2. Run 시작 시점의 Provider, Model, Effort, Tool, Skill, MCP 설정을 snapshot으로 고정합니다.
3. Provider Adapter가 공통 요청을 각 Provider 형식으로 변환합니다.
4. 텍스트 delta, 상태, 사용량과 Tool Call을 공통 Stream Event로 정규화합니다.
5. Tool Call이 없으면 assistant 메시지와 사용량을 저장하고 Run을 완료합니다.
6. Tool Call이 있으면 각 입력을 schema로 검증하고 권한 정책과 `pre_tool_use` hook을 실행합니다.
7. 승인이 필요한 Tool은 `awaiting_approval` 상태에서 사용자 또는 관리자의 결정을 기다립니다.
8. 결과를 크게 바꿀 모호함이 있으면 `request_user_input`을 단독 호출하여 질문 묶음을 저장하고 `awaiting_input`에서 계정 소유자의 답변을 기다립니다. 답변에 종속된 후속 결정이 있으면 같은 Run에서 다시 호출할 수 있지만 전체 질문은 최대 10개입니다.
9. Tool을 실행하고 성공 또는 실패 결과를 반드시 원래 Tool Call ID와 연결합니다.
10. `post_tool_use` hook과 artifact 저장을 처리한 뒤 Tool Result를 대화에 추가합니다.
11. 갱신된 Context로 다음 모델 Turn을 실행합니다.

확인 질문의 기본 민감도는 계정별 `agent.clarification_mode`에 영구 저장하며 `autonomous`, `balanced`, `confirming` 중 하나를 사용합니다. 새 Run은 시작 시점의 값을 snapshot에 고정합니다. 각 질문은 2~4개의 객관식 선택지를 제공하며 Frontend가 직접 답변 입력을 항상 함께 표시합니다. 사용자는 현재 묶음에 한해 `이번에는 AI가 판단`을 선택할 수 있고 이 선택은 계정 기본값을 바꾸지 않습니다. 답변은 `input_submitted` 이벤트와 checkpoint에 저장한 뒤 같은 Run을 `queued`로 되돌려 재개합니다. 독립적이고 이미 알려진 사실·결정은 각각 별도 질문으로 나눠 같은 묶음에 제시하며, 여러 사실을 하나의 질문이나 직접 입력 안내에 합치지 않습니다. 명시적 인터뷰·접수에서는 현재 예상 가능한 고가치 질문을 Run 한도 안에서 첫 묶음에 모두 제시하고, 알려진 질문을 제출·대기 흐름으로 의도적으로 나누지 않습니다. 답변 전에는 합리적으로 예상할 수 없었던 중대한 차단 쟁점이 새로 드러난 경우에만 후속 질문 묶음을 요청합니다. 이전 질문 카드는 실행 과정에 답변과 함께 남고 새 질문 카드가 별도 단계로 이어집니다. 같은 Run에서 해결된 질문 ID를 다시 사용할 수 없으며 모든 묶음을 합쳐 최대 10개까지만 질문합니다. 사용자가 `$ask-me`를 명시적으로 적용하면 이 적응형 질의응답으로 목표·제약·완료 조건을 구체화하고, 그 실행 계약에 따라 작업을 수행·검증합니다. 사용자가 개인적으로 무엇을 해야 하는지 묻고 누락된 사용자 사실이 권고·긴급성·안전·범위·다음 행동을 실질적으로 바꿀 수 있으면, 일반적인 조건문 목록으로 대신하지 않고 최소한의 고가치 사실을 질문 UI로 먼저 확인합니다. 직업 역할을 부여한 문장은 사용자 사실을 제공한 것으로 보지 않습니다. 파일·사내 검색·MCP·웹 검색 등으로 대상을 찾는 요청도 대화에 검색 대상을 구분할 정보가 없으면 도구 호출 전에 주제·목적·범위·최신성·소유자·문서 유형 중 가장 정보량이 큰 누락 기준을 질문 UI로 확인합니다. 모든 필터를 기계적으로 묻지 않으며, 앞선 대화·선택 파일·프로젝트 문맥만으로 검색 대상이 충분히 특정되면 바로 검색합니다. 반대로 일반 지식, 명백한 가상 사례, 개인 결정을 요구하지 않는 브레인스토밍과 이미 충분한 사실이 있는 요청에는 이 규칙만으로 질문 UI를 열지 않습니다. 이미 확인 가능한 사실, 되돌릴 수 있는 세부사항과 결과를 크게 바꾸지 않는 선택은 묻지 않습니다.

Provider가 `max_tokens`, `length` 같은 출력 한도 종료를 보고하면 해당 응답을 최종 답변으로 확정하지 않습니다. 이미 저장한 assistant text를 Context tail에 그대로 두고 짧은 이어쓰기 지시만 추가하여 제한된 횟수 안에서 자동으로 계속하며, 완료 시 누적 draft와 최종 Message가 한 번만 이어진 동일한 text로 수렴해야 합니다. 내용도 Tool Call도 없는 정상 종료는 빈 답변으로 완료하지 않고 한 번 재시도하며, 반복되면 부분 draft와 이벤트를 보존한 채 명시적인 Provider 오류로 종료합니다. 출력 한도에 걸린 Tool Call은 인자가 완전하다고 증명할 수 없으므로 실행하지 않습니다.

Tool 실패는 가능한 경우 전체 Loop를 즉시 중단하지 않고 구조화된 오류 결과로 모델에 돌려보냅니다. 모델이 대안 행동을 선택하거나 사용자에게 실패 원인을 설명할 수 있게 합니다.

## Tool 실행

- Tool Registry에 등록된 Tool만 실행합니다.
- Tool 입력은 실행 전에 schema 검증을 통과해야 합니다.
- 파일 경로, 명령, 네트워크 대상과 사용자 권한을 실행 전에 검사합니다.
- 복수 Tool Call은 입력을 정상적으로 해석할 수 있고 전부 read-only 또는 외부 read로 분류된 경우에만 병렬 실행합니다. Plan·Skill 같은 제어 Tool, workspace·외부 쓰기, 파괴적 Tool과 의미가 불명확한 MCP Tool이 하나라도 포함되면 같은 batch를 원래 순서대로 직렬 실행합니다.
- 병렬 실행 중 하나가 실패해도 다른 결과를 취소하거나 잃지 않습니다.
- 모든 Tool Call에는 대응하는 Tool Result를 생성하여 대화 상태가 깨지지 않게 합니다.
- 큰 출력은 메시지에 전부 넣지 않습니다. 전체 Tool 종류에 모델 Context window 기반 개별 결과·한 Turn 합계 예산을 적용하고, 원문은 `ToolExecution`에 보존한 뒤 preview와 Tool Call ID만 Context에 넣습니다. 모델이 추가 원문이 필요하면 같은 Run으로 권한이 제한된 `read_tool_result`를 offset·limit 방식으로 호출합니다.
- 완료된 대화 Context를 압축할 때는 최소 최근 4개 Message를 유지하고 유효 입력 예산의 8% 범위에서 최대 20개까지 연속된 최신 Message를 추가 보존합니다. 요약에는 source Message·Run·Tool Call ID를 남기며, 누락된 정확한 표현이나 결정이 필요하면 `retrieve_conversation_context`가 현재 Run의 사용자 권한과 Conversation을 다시 확인한 뒤 활성 압축 범위만 검색하고 Message ID별 원문을 offset·limit으로 반환합니다. 다른 Conversation과 아직 압축되지 않은 Message는 조회하지 않습니다.
- 허용된 MCP Tool schema의 예상 크기가 모델 Context window의 10% 이상이면 core Tool은 유지하고 MCP Tool은 `tool_search`·`tool_describe`·`tool_call` bridge 뒤에 둡니다. bridge는 Run snapshot에 고정된 MCP catalog만 조회·호출하며 직접 호출과 동일한 schema 검증, 승인, Secret binding, 감사와 결과 예산을 통과합니다.
- Web·외부 MCP처럼 신뢰하지 않는 출처의 결과는 provider Context에 넣기 전에 구조화된 불신 경계로 감싸고, 결과 본문이 경계 종료 문자열을 위조해도 탈출할 수 없도록 delimiter를 무력화합니다.
- 완료된 Tool Call의 큰 문자열 인자와 결과 preview는 다음 model Turn 전에 유효한 JSON과 Tool Call/Result ID 관계를 유지한 채 축약합니다. 전체 입력과 결과는 DB·Artifact 원본에 남기고, Context에는 경로 같은 짧은 식별 정보와 head/tail preview, 복구 가능 marker만 보존합니다. Provider가 Tool Call에 검증용 서명을 붙인 경우에는 서명된 호출 인자를 바꾸지 않습니다.
- Tool Result의 Artifact ID, storage key, 서버 경로, content hash와 digest는 Agent Loop 내부의 구조화 참조로만 사용합니다. 공통 System Prompt는 모델이 이 값을 진행 메시지나 최종 답변에 출력하지 못하게 명시해야 합니다.
- 생성 파일은 최종 답변에서 사용자 표시명과 결과 요약으로만 안내합니다. 열기·다운로드 동작은 문자열 링크를 모델이 만들지 않고 Backend의 구조화 Artifact metadata를 Frontend 카드가 렌더링합니다.
- Frontend의 내부 식별자 제거는 과거 응답과 Provider 지침 이탈을 위한 최종 안전망이며, 모델 출력 규칙을 대신하는 주 처리 방식으로 사용하지 않습니다.
- Tool별 timeout, 재시도 정책과 출력 크기 제한을 적용합니다.
- `write_file`처럼 모델이 큰 파일 본문을 Tool 인자로 생성하는 작업은 Tool Call 인자 streaming 시작을 실행 Timeline의 시작 시각으로 기록합니다. 표시 소요 시간은 인자 생성부터 실제 파일 저장 완료까지 이어지며 디스크 I/O 시간만 별도로 축소해 보여주지 않습니다.
- `write_file` 인자 streaming 중에는 누적 추정 Token과 줄 수, 안전하게 추출한 대상 파일명을 durable `tool_progress` event로 갱신합니다. Frontend는 5,000 Token마다 같은 게이지를 왼쪽부터 다시 채우며 0~5,000은 파란색, 5,000~10,000은 녹색, 10,000~15,000은 노란색, 15,000~20,000 이상은 빨간색으로 표시합니다. `파일명`, `N 토큰 (N줄)` 카운터를 같은 Tool 행에 표시하며, 이 바는 완료율이 아니라 누적 생성량입니다. 재접속 시 snapshot과 event replay로 동일한 시작 시각과 최신 카운터를 복원합니다.

## 종료와 제한

Agent Loop는 다음 조건 중 하나에서 끝납니다.

- 모델이 Tool Call 없는 최종 답변을 반환
- 사용자가 실행 취소
- Run snapshot의 model Turn·총 Token·경과 시간·예상 비용 안전 한도 도달
- 관리자의 조직 전체 비상 중단
- 복구할 수 없는 Provider·저장소 오류
- 서버 종료 또는 Worker 중단

실행기는 매 model Turn 전후에 `modelTurns`, `inputTokens + outputTokens`, `costUsd`와 `started_at` 기준 경과 시간을 검사합니다. 이 값은 Run 단위이며 같은 Session에서 다음 작업으로 생성된 새 Run은 0부터 시작합니다. 사용자가 Effort를 명시하면 Run 전체에서 고정하고, `Auto`를 선택하면 별도 모델 호출 없이 요청의 산출물·첨부·참조·조사 범위에 따라 실효 Effort를 결정합니다. 기본은 `low`이며 일반 조사·복잡 작업·산출물 생성·첨부 또는 참조 3개 이상은 `medium`, 사용자가 심층·철저·전수 조사 범위를 명시한 경우만 `high`를 사용합니다. Model Turn이 이어졌다는 이유만으로 Effort를 올리지 않습니다. 각 Turn의 요청·실효 Effort, TTFT, 전체 시간, cached·uncached input Token과 cache hit ratio는 `model_turn_completed` event와 snapshot에 저장합니다. Provider 호출의 첫 응답 대기, 첫 event 수신 후 stream 대기와 자동 재시도는 `provider_activity_changed`·`provider_retry_scheduled` event 및 Run snapshot에 남기고, Frontend는 현재 시도, 남은 무응답 제한시간과 재시도 원인을 Thinking 행에서 즉시 표시하여 이유를 알 수 없는 무반응 대기를 만들지 않습니다. Context는 별도로 각 model Turn 전에 계산하고 기본적으로 유효 입력 예산의 75%를 넘으면 이전 assistant·Tool 구간을 구조화된 요약으로 축약하되 최근 Tool Call/Result pair는 그대로 보존합니다. 272K 이후 장문 Context의 가격·사용량 배수가 적용되는 P-GPT·OpenAI GPT 계열은 관리자 설정에서 `표준`과 `최대` 용량 모드를 제공합니다. 기본 `표준` 모드는 272K 가격 경계에서 20K만 남긴 약 252K 추정 입력에 도달하면 압축하고, 명시적으로 선택하는 `최대` 모드만 1.05M Context와 75% 임계값 및 보수적 token 추정 padding을 사용합니다. 표준 모드의 20K 여유와 최대 모드의 비율은 용량 모드와 함께 저장되어 임의 조합을 허용하지 않으며 새 Run snapshot에 고정합니다. Codex의 GPT-5.4·5.5·5.6 계열은 서비스 정책상 272K Context와 85% 임계값으로 고정합니다. 그 밖의 P-GPT, OpenAI API, Gemini API와 Claude API는 각 표준 API model capability의 Context window를 사용합니다. 축약 전에는 `컨텍스트 축약 중`, 완료 후에는 축약 전·후 추정 Token과 보존 범위를 Timeline에 표시하고 snapshot과 event replay에 남깁니다. 개별 Provider·Tool 호출의 transport timeout은 해당 호출의 실패·재시도 조건이며 Run 전체의 경과 시간 한도와 구분합니다.

Composer의 `analysis_depth=auto | brief | standard | deep`와 `answer_length=auto | brief | standard | detailed`는 Provider Effort와 분리한 Run별 실행 옵션입니다. 둘 다 기본 `auto`이며 전송 시 Run snapshot, user Message metadata, Steering과 Queue 승격 정보에 고정합니다. `analysis_depth`는 웹 검색·페이지 확인 상한과 자료 탐색·교차 검증 범위를 조절하되 상한을 목표 횟수처럼 채우지 않고, 최신성·안전·권한에 필요한 검증은 `brief`에서도 생략하지 않습니다. `answer_length`는 최종 산출물이 채팅일 때의 보이는 답변 분량만 조절하며 분석 범위나 Provider Effort를 낮추지 않습니다. 문서 분량은 별도의 `target_output_tokens`로 유지하고 `auto`와 `file` 출력 모드에서 사용할 수 있으며 `chat` 모드에는 적용하지 않습니다.

## Context 관리

각 Turn 전에 예상 Context 크기를 검사합니다. 임계치를 넘으면 오래된 Tool 출력 정리, artifact 전환 또는 대화 요약을 적용합니다. 완료된 대화 기록뿐 아니라 아직 Message로 확정되지 않은 현재 Run의 assistant·Tool loop도 같은 검사 대상입니다. 요약 후에도 사용자 목표, 중요한 결정, 활성 artifacts, 검증된 결과와 다음 작업은 유지해야 합니다.

Provider의 출력 Token 제한이 요청값보다 작으면 Provider capability에 맞게 안전한 값으로 조정하고 상태 이벤트를 남깁니다.

## 중단과 재개

관리자의 비상 전체 중단은 같은 조직의 `running`, `awaiting_approval`, `paused`, `queued`, `interrupted` Run과 대기 Message를 취소하고 현재 process의 실행 task에도 즉시 cancellation을 전달합니다. 실행 중 Tool과 승인 대기는 취소 상태로 정리하며 조치자, 사유와 대상 수를 감사 기록에 남깁니다.

Tool Result까지 저장되었지만 다음 모델 Turn 전에 중단된 Run은 `interrupted`로 표시합니다. 재개할 때 새 사용자 메시지를 임의로 추가하지 않고, 저장된 Tool Result부터 다음 모델 Turn을 이어갑니다.

다음 항목을 저장해야 합니다.

- Run 상태와 현재 Turn
- 입력 메시지와 assistant 응답
- Tool Call과 Tool Result의 ID 관계
- 실행 옵션 snapshot
- 사용량과 제한 소비량
- 승인 대기 상태
- 마지막으로 완료된 단계

부작용이 있는 Tool을 재실행하기 전에 이전 실행 완료 여부와 idempotency key를 확인합니다. 각 `ToolExecution`은 실행 시점의 effect, replay 허용 여부, 완료 결과 재사용 여부, unknown-outcome fail-closed 여부와 idempotency 요구를 revision과 함께 snapshot으로 고정하며, 복구 시 현재 Tool 이름으로 정책을 다시 추론하지 않습니다. MCP Tool 호출은 durable idempotency key를 Tool 인자와 분리된 표준 `tools/call.params._meta`에 전달합니다. MCP 서버가 이 key를 실제 중복 제거에 사용한다고 가정하지 않으며, 지원 여부가 불명확한 외부 부작용은 계속 unknown-outcome fail-closed로 복구합니다.

## 다중 사용자와 공유 모드

개인 모드에서는 한 사용자의 Run이 다른 사용자 세션에 영향을 주지 않습니다. 공유 모드에서는 모든 사용자가 같은 대화와 실행 상태를 보지만, 동일 대화에 대한 Agent Loop는 기본적으로 한 번에 하나만 실행합니다.

- 공유 대화별 실행 lock 또는 queue를 사용합니다.
- Run 도중 공용 옵션이 변경되어도 진행 중인 Run의 snapshot은 바꾸지 않습니다.
- 변경된 공용 옵션은 다음 Run부터 적용합니다.
- 실행 취소와 승인 권한은 역할 정책으로 제한합니다.
- 누가 메시지, 옵션, 승인과 취소를 수행했는지 감사 기록에 남깁니다.

## 세션별 병렬 실행

한 사용자는 여러 채팅 세션을 만들고 서로 다른 세션에서 Agent Run을 동시에 실행할 수 있습니다. 실행 잠금 범위는 사용자 전체가 아니라 `conversation_id`입니다.

```text
사용자 A
├─ 세션 1 → Run 실행 중
├─ 세션 2 → 별도 Run 실행 중
├─ 세션 3 → Queue 대기
└─ 세션 4 → 완료 결과 열람
```

- 같은 세션에는 기본적으로 동시에 하나의 Run만 허용합니다.
- 같은 세션에 실행 중 추가 요청이 들어오면 세션 Queue에 순서대로 저장합니다.
- 서로 다른 세션의 Run은 사용자와 서버 한도 안에서 병렬 실행합니다.
- 사용자별 최대 동시 Run과 서버 전체 최대 동시 Run을 관리자가 설정합니다.
- 한도를 초과한 Run은 실패시키지 않고 `queued` 상태로 대기시킵니다.
- 공유 세션도 동일한 세션 단위 lock과 Queue를 사용합니다.

초기 기본값은 다음을 권장합니다.

```text
세션별 동시 Run       = 1
사용자별 동시 Run     = 3
서버 전체 동시 Run    = 운영 환경 설정
```

사용자가 실행 중인 세션에서 다른 세션으로 이동하거나 브라우저 연결을 종료해도 Run을 취소하지 않습니다. Run은 Backend 또는 Worker에서 계속되며, Frontend는 재접속 시 DB의 Run 상태와 저장된 이벤트를 조회해 화면을 복구합니다.

Frontend의 채팅 목록에는 `queued`, `running`, `completed`, `failed`, `cancelled` 상태를 표시하고 실행 완료 알림을 제공할 수 있어야 합니다. 스트리밍 연결은 화면 표시 수단일 뿐 Run의 생명주기를 소유하지 않습니다.

SQLite 개발 환경에서는 WAL 모드, 짧은 트랜잭션과 쓰기 충돌 재시도를 사용합니다. 각 Run이 장시간 DB 트랜잭션을 유지하지 않게 하며, Backend와 Worker를 여러 프로세스나 Pod로 확장할 때는 PostgreSQL 기반 lock과 Queue로 전환합니다.

## 실행 중 세션 전환과 무손실 재부착

사용자가 실행 중인 세션 A에서 세션 B로 이동한 뒤 다시 A로 돌아오면, A의 작업은 계속 실행 중이어야 하며 화면도 사용자가 계속 보고 있었던 것처럼 복원되어야 합니다.

복원 대상에는 다음이 포함됩니다.

- 스트리밍 중인 assistant 부분 응답
- 현재 Plan·Step·Subtask와 진행 상태
- 실행 중인 Tool 이름, 입력 요약, 시작 시각과 경과 시간
- 완료된 Tool Result와 생성된 artifacts
- 승인 대기, retry, context compact와 오류 상태
- Run 취소·일시 정지·재개 가능 여부

### Backend 이벤트 계약

각 Run 이벤트는 단조 증가하는 `sequence`를 가집니다.

```text
run_id
conversation_id
sequence
event_type
payload
created_at
```

- Backend는 현재 Run snapshot과 복구에 필요한 이벤트를 저장합니다.
- Frontend는 세션별로 마지막 적용 `sequence`를 기억합니다.
- 세션에 다시 연결할 때 `after_sequence` 또는 `Last-Event-ID`를 전달합니다.
- Backend는 snapshot 이후 누락된 이벤트를 순서대로 replay한 뒤 live stream에 연결합니다.
- replay와 live 전환 사이에 이벤트가 빠지지 않도록 동일한 cursor 경계를 사용합니다.
- 동일 이벤트가 다시 전달되어도 Frontend는 `run_id + sequence`로 중복 적용하지 않습니다.
- stream이 끊겨도 Run에는 영향을 주지 않으며 자동 재연결 후 같은 방식으로 복구합니다.

이벤트 전체를 무제한 보관하지 않아도 되지만, 현재 상태를 완전히 표현하는 snapshot과 감사·복구에 필요한 주요 이벤트는 유지합니다. 세밀한 text delta를 정리할 때는 누적된 assistant draft를 snapshot에 포함합니다.

### Frontend 상태 계약

- 세션별 message, assistant draft, Run snapshot과 마지막 event sequence를 독립 store에 보관합니다.
- 화면 전환 시 현재 세션 state를 삭제하거나 다른 세션 state로 덮어쓰지 않습니다.
- 돌아올 때 cache를 즉시 표시하고 Backend snapshot·event replay로 동기화합니다.
- cache가 오래되었더라도 화면을 빈 상태로 되돌리지 않고 동기화 중임을 표시합니다.
- replay 중 text delta와 Tool 이벤트가 중복 렌더링되지 않게 idempotent reducer를 사용합니다.
- 현재 보고 있지 않은 세션의 상태도 sidebar badge와 알림을 갱신합니다.
- 경과 시간은 저장된 `started_at`을 기준으로 계산하며 화면을 떠난 시간 동안 멈추지 않습니다.

여러 세션 이벤트는 하나의 WebSocket에서 multiplex하거나 세션별 SSE로 연결할 수 있습니다. 구현 방식과 관계없이 사용자가 보고 있는 세션만 정상이고 다른 세션은 stale해지는 구조는 허용하지 않습니다.

### 텍스트 스트리밍과 메시지 하단 추종

Provider의 text delta는 누적 assistant draft에 즉시 반영합니다. 이 draft가 저장·복구·중복 제거에 사용하는 canonical state이며, 화면용 reveal buffer는 손실되어도 다시 만들 수 있는 일시적 UI state입니다. 화면에는 짧고 상한이 있는 buffer와 animation frame 기반 reveal을 적용해 불규칙한 chunk가 한꺼번에 튀거나 글자가 지나치게 잘게 깜박이지 않게 하되, reveal 때문에 사용자가 응답 시작을 체감하는 시간이 불필요하게 늦어져서는 안 됩니다. 완료 이벤트를 받으면 남은 buffer를 즉시 비우고 저장된 최종 assistant 메시지와 동일한 텍스트로 수렴해야 합니다. Markdown은 스트리밍 중 불완전한 code fence, 표, 링크와 HTML을 안전한 임시 표현으로 렌더링하고, 문법이 완성되면 최종 렌더링으로 전환합니다.

메시지 영역의 자동 스크롤은 단순한 매 delta별 `scrollIntoView` 호출이 아니라, 높이가 계속 증가하는 스트리밍 tail을 animation frame 단위로 부드럽게 추종하는 별도 상태로 관리합니다.

- 자동 추종은 세션별 `following`, `detached`, `restoring` 상태로 관리합니다. `following`만 하단을 움직이고, `detached`는 사용자 위치를 보존하며, `restoring`은 snapshot·replay 적용이 끝날 때까지 자동 이동 여부를 결정하지 않습니다.
- 사용자가 메시지를 전송한 직후 시작되는 새 응답은 `following`으로 시작합니다. 백그라운드 Run, 재연결 또는 replay로 발견한 응답은 사용자의 기존 세션별 추종 상태를 유지하며 임의로 하단으로 이동하지 않습니다.
- 스트리밍으로 `scrollHeight`가 계속 커져도 현재 애니메이션을 매번 재시작하지 않고, 변하는 하단 목표를 연속적으로 따라갑니다.
- 사용자가 wheel, touch 또는 scrollbar로 위쪽을 탐색하면 자동 추종을 즉시 중단하고 현재 위치를 보존합니다. 새 delta가 도착했다는 이유로 강제로 하단으로 끌어내리지 않습니다.
- 사용자가 하단 근처로 돌아오거나 명시적인 "최신 응답으로 이동" 동작을 실행하면 자동 추종을 재개합니다.
- 세션을 전환할 때 세션별 scroll 위치와 하단 추종 여부를 분리해 보존합니다. 실행 중인 세션으로 돌아왔고 사용자가 이전에 tail을 따라가던 상태라면 snapshot·event replay를 애니메이션 없이 한 번에 적용한 뒤 현재 하단에서 live delta만 부드럽게 추종합니다. replay된 과거 delta를 타자 효과처럼 다시 재생하지 않습니다.
- 사용자가 `detached`인 동안 새 내용이 도착하면 위치를 유지하고 "새 응답" 또는 "최신 응답으로 이동" affordance를 표시해 새 내용의 존재와 복귀 동작을 명확히 합니다.
- `prefers-reduced-motion: reduce`에서는 보간 애니메이션을 생략하고 즉시 목표 위치로 이동합니다.
- Tool 진행 UI나 Plan Timeline이 메시지 tail 안에서 커질 때도 text delta와 같은 추종 정책을 사용합니다.

구현 시 canonical draft, 텍스트 reveal과 scroll follow를 분리합니다. draft reducer는 "어떤 텍스트가 확정적으로 누적되었는지", reveal은 "그중 얼마나 화면에 보여줄지", scroll follow는 "사용자가 tail을 따라가고 있는지"만 책임지게 하여 네트워크 chunk 간격, replay, Markdown 재배치와 사용자 스크롤 의도가 서로 덮어쓰지 않게 합니다.

Frontend 단위·컴포넌트 테스트에는 최소한 다음 시나리오를 포함합니다.

1. 불규칙한 text delta가 순서와 문자 손실 없이 점진적으로 표시되고 완료 시 최종 텍스트와 일치합니다.
2. 스트리밍 중 하단 목표가 갑자기 증가해도 scroll 위치가 역행하거나 순간 이동하지 않고 연속적으로 수렴합니다.
3. 사용자가 위로 스크롤하면 자동 추종이 해제되고 이후 delta에도 위치가 유지됩니다.
4. 하단 근처 복귀 또는 명시적 이동 동작 후 자동 추종이 다시 활성화됩니다.
5. 실행 중 세션의 snapshot·event replay는 과거 delta를 다시 애니메이션하지 않고 즉시 복원하며, 중복 텍스트 없이 이후 live delta의 하단 추종만 이어집니다.
6. reduced-motion 환경에서는 애니메이션 없이 동일한 최종 위치와 상태가 보장됩니다.
7. `detached` 상태에서 새 delta가 도착해도 위치가 유지되고 새 내용 affordance가 표시되며, 이를 실행하면 `following`으로 전환됩니다.

브라우저 E2E에서는 실제로 긴 스트리밍 응답을 발생시켜 텍스트가 점진적으로 보이는지, scrollbar가 자연스럽게 내려가는지, 사용자가 과거 메시지를 읽는 동안 위치를 빼앗기지 않는지를 시각적으로 확인합니다. JSDOM의 수치 기반 scroll 테스트만으로 완료 판정하지 않습니다.

## Plan, Subtask와 중간 개입

복잡한 업무는 구조화된 Plan과 Step으로 관리합니다. Plan은 사용자에게 보여주기 위한 임시 설명문이 아니라 Backend가 상태와 의존 관계를 추적하는 실행 객체입니다.

```text
Run
└─ Plan
   ├─ Step A → completed
   ├─ Step B → running
   │  ├─ Subtask B1 → running
   │  └─ Subtask B2 → running
   └─ Step C → queued, depends_on B
```

- 독립 Subtask는 사용자·서버 동시 실행 한도 안에서 병렬로 실행합니다.
- 각 Step은 입력, Context, 옵션, dependency, 결과, artifacts와 오류를 저장합니다.
- 사용자는 실행 중 `steer`, `pause`, `resume`, `cancel`, `retry_step` action을 보낼 수 있습니다.
- steer는 현재 Tool을 위험하게 중단하지 않고 다음 안전한 Turn 또는 Step 경계에서 적용합니다.
- 실패 Step 재실행은 다른 완료 Step을 되돌리지 않고 저장된 입력 snapshot을 사용합니다.
- 진행 중 Plan 수정과 action 수행자는 감사 기록에 남깁니다.
- 최종 답변과 사용자용 업무 계획은 상세 Tool log와 분리합니다.
- Backend 실행 Plan은 상태 전이·재시도·Subtask를 책임지고, 모델이 `update_plan`으로 작성하는 사용자용 업무 계획은 실제 요청의 대상과 결과가 드러나는 3~7개 단계로 별도 유지합니다. 고정된 `준비 → 분석 → 도구 → 답변` 문구를 사용자 계획처럼 노출하지 않습니다.
- 사용자용 업무 계획은 한 번에 하나의 `in_progress` 단계만 허용하고 `work_plan_updated` event와 Run snapshot에 저장하여 재접속과 event replay에서도 같은 단계와 상태를 복원합니다.
- Agent 내부 raw reasoning과 chain-of-thought는 사용자에게 노출하지 않습니다. 대신 판단 결과와 다음 행동만 정리한 사용자 공개용 `progress_summary`를 Tool event와 같은 순번의 실행 Timeline에 기록합니다.

### 답변 생성 중 Steer와 순차 입력

같은 세션에서 Run이 실행 중일 때도 Composer를 잠그지 않습니다. 사용자가 보내는 추가 메시지는 전송 전에 다음 두 동작 중 하나로 명확히 구분합니다.

```text
steer       → 현재 Run의 목표·제약·우선순위를 수정
queue_next  → 현재 Run이 끝난 뒤 새 Run으로 순차 실행
```

Frontend는 실행 중 Composer에 현재 전송 동작을 표시합니다. Run 실행 중 기본 전송은 `steer`이며 `Enter` 또는 기본 전송 버튼은 `현재 작업에 반영`, `Ctrl+Enter`는 `다음 요청으로 대기(queue_next)`, `Shift+Enter`는 줄바꿈으로 동작합니다. 전송 버튼 주변에 `Ctrl+Enter로 다음 요청 대기` 안내를 제공하고, 키보드 입력과 동일한 동작을 선택할 수 있는 보조 메뉴를 둡니다. 전송 직후 메시지에 실제 적용 방식을 표시합니다. 아직 적용되지 않은 Queue는 Composer 입력란 바로 위에 접수 순서대로 누적해 표시하며 각 항목에서 `현재 작업 조정`으로 steer 전환하거나 취소할 수 있습니다. Queue 항목에는 순번을 표시하며 drag reorder 같은 복잡한 편집은 초기 범위에서 제외합니다.

`steer`의 처리 계약은 다음과 같습니다.

- Backend는 사용자 메시지를 먼저 저장하고 고유한 `action_id`와 접수 순서를 부여한 뒤 Worker에 전달합니다. 브라우저 연결이 끊겨도 지시를 잃지 않습니다.
- 모델이 text를 streaming 중이면 Provider가 안전한 취소를 지원할 때 현재 생성을 협력적으로 중단하고, 이미 표시·저장된 부분 응답을 `interrupted_by_steer`로 남긴 뒤 steer를 포함한 다음 model Turn을 같은 Run에서 시작합니다.
- Provider 취소를 지원하지 않거나 취소 확인이 불확실하면 현재 model Turn의 출력을 끝까지 수신하되 사용자에게 노출되는 상태를 `steer 대기`로 표시하고, Turn 완료 직후 steer를 적용합니다.
- Tool이 실행 중이면 읽기 전용 Tool은 취소 가능 정책에 따라 중단할 수 있지만, 파일 쓰기·외부 전송 같은 부작용 Tool은 강제로 끊지 않습니다. Tool Result를 저장한 다음 안전한 Turn·Step 경계에서 steer를 적용합니다.
- 여러 steer가 적용 전에 도착하면 접수 순서를 보존해 하나의 다음 Turn Context로 병합할 수 있습니다. 서로 모순되는 지시는 마지막 지시가 자동으로 이전 지시를 지운다고 가정하지 말고, 충돌이 작업 결과를 바꾸면 사용자 확인 대상으로 표시합니다.
- steer는 새 Run을 만들지 않으며 원래 Run의 Provider·Model·권한 snapshot을 유지합니다. 새 파일 첨부나 `$Skill`·`$MCP` 참조는 현재 Run 권한 범위에서 Backend가 다시 검증합니다.

`queue_next`의 처리 계약은 다음과 같습니다.

- 메시지는 현재 Run과 분리된 `queued` 요청으로 저장하고 세션 Queue의 뒤에 추가합니다. 현재 Run의 Context나 출력 방향을 바꾸지 않습니다.
- 현재 Run이 `completed`, `failed`, `cancelled` 또는 `interrupted`의 terminal state에 도달하면 Queue의 첫 요청으로 새 Run을 시작합니다. 앞 Run이 실패해도 기본적으로 다음 요청을 버리지 않습니다.
- 각 queued 요청은 실행을 시작하는 시점의 대화 기록을 Context로 사용하되, 전송 당시 선택한 첨부·Provider·Model·Effort·Skill·MCP 의도는 별도 snapshot으로 보존하고 실행 직전에 권한과 유효성을 다시 검증합니다.
- 사용자는 대기 중인 요청의 내용과 순번을 확인하고 실행 전 취소할 수 있습니다. 동일 `action_id` 재전송은 중복 Queue 항목을 만들지 않습니다.

다음 상태와 이벤트를 snapshot·replay 대상에 포함합니다.

```text
steer_received
steer_waiting_safe_boundary
steer_applied
steer_cancelled
queued_message_added
queued_message_cancelled
queued_message_promoted_to_run
```

수용 기준은 다음과 같습니다.

1. text streaming 중 steer를 보내면 부분 응답을 잃거나 중복시키지 않고 같은 Run에서 수정된 지시가 반영됩니다.
2. 부작용 Tool 실행 중 steer를 보내도 Tool Call·Result 관계가 깨지지 않고 다음 안전한 경계에서 적용됩니다.
3. `queue_next` 메시지는 현재 응답에 영향을 주지 않으며 앞 Run 종료 후 정확히 한 번 새 Run으로 시작됩니다.
4. steer와 Queue 상태는 세션 전환·새로고침·네트워크 재연결 후에도 snapshot·event replay로 복원됩니다.
5. 여러 추가 입력의 접수 순서가 유지되고, 취소한 대기 입력은 실행되지 않습니다.
6. Run 실행 중 `Enter`는 steer, `Ctrl+Enter`는 `queue_next`, `Shift+Enter`는 줄바꿈으로 동작하며, 각 추가 메시지가 현재 Run에 반영되는지 다음 Run으로 대기하는지 전송 후 식별할 수 있습니다.

Project, 파일 Workspace와 전문 산출물까지 포함한 제품 요구사항은 `COWORK_FEATURE_REQUIREMENTS.md`를 따릅니다.

## Provider Adapter 계약

Codex, OpenAI, OpenAI Compatible, P-GPT, Claude와 Gemini는 서로 다른 응답 형식을 사용하더라도 Agent Loop에는 다음 공통 형태를 제공합니다.

- 정규화된 assistant text delta
- 정규화된 Tool Call ID, 이름과 입력
- Tool Call 여부와 종료 이유
- Token 및 비용 사용량
- Provider 오류 분류와 재시도 가능 여부
- Provider capability
- Provider가 제공하는 reasoning summary가 있으면 raw reasoning과 분리해 취급하며, 사용자 공개 정책을 통과한 요약만 `progress_summary`로 정규화할 수 있습니다.

Provider별 특수 처리는 Adapter 내부에 제한하고 Agent Loop는 특정 Provider 응답 구조에 의존하지 않습니다.

## 관측 이벤트

Frontend와 감사 로그를 위해 최소한 다음 이벤트를 제공합니다.

```text
run_started
turn_started
model_turn_completed
progress_summary
work_plan_updated
assistant_text_delta
assistant_turn_completed
approval_requested
input_requested
input_submitted
input_checkpoint_consumed
tool_started
tool_completed
context_compacted
retry_scheduled
run_completed
run_failed
run_cancelled
run_interrupted
```

`progress_summary`는 비공개 chain-of-thought 원문이 아니라 “무엇을 확인했고 다음에 무엇을 하는지”를 설명하는 사용자 공개용 진행 메시지입니다. Backend는 이를 durable sequence가 있는 Run event로 저장하고 snapshot에 Tool 시작 event와 함께 정렬된 activity Timeline을 제공해야 합니다. Frontend는 재접속·replay 시 중복 없이 복원하며 Tool log와 진행 요약의 원래 순서를 유지합니다.

Run 프롬프트에 실제 적용된 Skill은 자동 선택, `$Skill` 명시 호출, 예약 실행 snapshot을 구분하여 이름, 간단한 적용 이유와 고정 revision/version을 activity Timeline 첫머리에 항상 표시합니다. 설치되어 있지만 적용되지 않은 Skill은 표시하지 않습니다.

Stream 이벤트가 유실되어도 최종 상태와 대화 내용은 DB에서 다시 조회할 수 있어야 합니다.

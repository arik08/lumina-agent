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
→ awaiting_approval
→ tools_running
→ model_streaming
→ completed | failed | cancelled | limit_reached | interrupted
```

상태 변경과 주요 이벤트를 DB에 기록하고 SSE 또는 WebSocket으로 Frontend에 전달합니다. Backend나 Worker가 재시작되어도 저장된 상태를 기준으로 실패 여부를 판단하거나 안전하게 이어갈 수 있어야 합니다.

## 한 Turn의 처리

1. 시스템·조직·Agent·사용자 지침과 대화 기록을 조합합니다.
2. Run 시작 시점의 Provider, Model, Effort, Tool, Skill, MCP 설정을 snapshot으로 고정합니다.
3. Provider Adapter가 공통 요청을 각 Provider 형식으로 변환합니다.
4. 텍스트 delta, 상태, 사용량과 Tool Call을 공통 Stream Event로 정규화합니다.
5. Tool Call이 없으면 assistant 메시지와 사용량을 저장하고 Run을 완료합니다.
6. Tool Call이 있으면 각 입력을 schema로 검증하고 권한 정책과 `pre_tool_use` hook을 실행합니다.
7. 승인이 필요한 Tool은 `awaiting_approval` 상태에서 사용자 또는 관리자의 결정을 기다립니다.
8. Tool을 실행하고 성공 또는 실패 결과를 반드시 원래 Tool Call ID와 연결합니다.
9. `post_tool_use` hook과 artifact 저장을 처리한 뒤 Tool Result를 대화에 추가합니다.
10. 갱신된 Context로 다음 모델 Turn을 실행합니다.

Tool 실패는 가능한 경우 전체 Loop를 즉시 중단하지 않고 구조화된 오류 결과로 모델에 돌려보냅니다. 모델이 대안 행동을 선택하거나 사용자에게 실패 원인을 설명할 수 있게 합니다.

## Tool 실행

- Tool Registry에 등록된 Tool만 실행합니다.
- Tool 입력은 실행 전에 schema 검증을 통과해야 합니다.
- 파일 경로, 명령, 네트워크 대상과 사용자 권한을 실행 전에 검사합니다.
- 독립적인 복수 Tool Call은 병렬 실행할 수 있습니다.
- 병렬 실행 중 하나가 실패해도 다른 결과를 취소하거나 잃지 않습니다.
- 모든 Tool Call에는 대응하는 Tool Result를 생성하여 대화 상태가 깨지지 않게 합니다.
- 큰 출력은 메시지에 전부 넣지 않고 artifact로 저장한 뒤 요약과 참조만 Context에 넣습니다.
- Tool별 timeout, 재시도 정책과 출력 크기 제한을 적용합니다.

## 종료와 제한

Agent Loop는 다음 조건 중 하나에서 끝납니다.

- 모델이 Tool Call 없는 최종 답변을 반환
- 사용자가 실행 취소
- 최대 Turn 도달
- 전체 실행 시간 초과
- Token 또는 비용 한도 도달
- 복구할 수 없는 Provider·저장소 오류
- 서버 종료 또는 Worker 중단

무한 반복을 막기 위해 `max_turns`, 전체 timeout, Tool timeout, Token 한도와 비용 한도를 둡니다. 제한값은 시스템 및 조직 정책을 넘을 수 없습니다.

## Context 관리

각 Turn 전에 예상 Context 크기를 검사합니다. 임계치를 넘으면 오래된 Tool 출력 정리, artifact 전환 또는 대화 요약을 적용합니다. 요약 후에도 사용자 목표, 중요한 결정, 활성 artifacts, 검증된 결과와 다음 작업은 유지해야 합니다.

Provider의 출력 Token 제한이 요청값보다 작으면 Provider capability에 맞게 안전한 값으로 조정하고 상태 이벤트를 남깁니다.

## 중단과 재개

Tool Result까지 저장되었지만 다음 모델 Turn 전에 중단된 Run은 `interrupted`로 표시합니다. 재개할 때 새 사용자 메시지를 임의로 추가하지 않고, 저장된 Tool Result부터 다음 모델 Turn을 이어갑니다.

다음 항목을 저장해야 합니다.

- Run 상태와 현재 Turn
- 입력 메시지와 assistant 응답
- Tool Call과 Tool Result의 ID 관계
- 실행 옵션 snapshot
- 사용량과 제한 소비량
- 승인 대기 상태
- 마지막으로 완료된 단계

부작용이 있는 Tool을 재실행하기 전에 이전 실행 완료 여부와 idempotency key를 확인합니다.

## 다중 사용자와 공유 모드

개인 모드에서는 한 사용자의 Run이 다른 사용자 세션에 영향을 주지 않습니다. 공유 모드에서는 모든 사용자가 같은 대화와 실행 상태를 보지만, 동일 대화에 대한 Agent Loop는 기본적으로 한 번에 하나만 실행합니다.

- 공유 대화별 실행 lock 또는 queue를 사용합니다.
- Run 도중 공용 옵션이 변경되어도 진행 중인 Run의 snapshot은 바꾸지 않습니다.
- 변경된 공용 옵션은 다음 Run부터 적용합니다.
- 실행 취소와 승인 권한은 역할 정책으로 제한합니다.
- 누가 메시지, 옵션, 승인과 취소를 수행했는지 감사 기록에 남깁니다.

## Provider Adapter 계약

Codex, OpenAI, OpenAI Compatible, P-GPT, Claude와 Gemini는 서로 다른 응답 형식을 사용하더라도 Agent Loop에는 다음 공통 형태를 제공합니다.

- 정규화된 assistant text delta
- 정규화된 Tool Call ID, 이름과 입력
- Tool Call 여부와 종료 이유
- Token 및 비용 사용량
- Provider 오류 분류와 재시도 가능 여부
- Provider capability

Provider별 특수 처리는 Adapter 내부에 제한하고 Agent Loop는 특정 Provider 응답 구조에 의존하지 않습니다.

## 관측 이벤트

Frontend와 감사 로그를 위해 최소한 다음 이벤트를 제공합니다.

```text
run_started
turn_started
assistant_text_delta
assistant_turn_completed
approval_requested
tool_started
tool_completed
context_compacted
retry_scheduled
run_completed
run_failed
run_cancelled
run_interrupted
```

Stream 이벤트가 유실되어도 최종 상태와 대화 내용은 DB에서 다시 조회할 수 있어야 합니다.

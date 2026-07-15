# Agent Harness 성능 요소와 Hermes 대비 Lumina Gap 분석

- 작성일: 2026-07-15
- 분석 관점: 같은 기반 모델을 사용할 때 Harness가 Agent의 성공률·일관성·복구력·비용·지연에 미치는 영향
- Lumina 기준: 현재 작업 디렉터리의 on-disk 구현 (`HEAD 97b5152`와 분석 시점의 미커밋 변경 포함)
- Hermes 기준: `.examples/hermes-agent` 참고 구현
- 관련 선행 문서:
  - `docs/project-context/LUMINA_AGENT_RELIABILITY_HERMES_MYHARNESS_ANALYSIS_2026-07-15.md`
  - `docs/project-context/MYHARNESS_AGENT_RELIABILITY_ANALYSIS.md`
  - `docs/project-context/AGENT_LOOP.md`

## 1. 결론

동일한 모델을 고정해도 실제 Agent 성능은 Harness에 따라 크게 달라진다.

> 실제 Agent 성능 ≈ 모델 능력 × 컨텍스트 품질 × Tool 사용성 × 실행 루프 × 런타임 생존성 × 검증 능력

이 관계는 덧셈보다 곱셈에 가깝다. 어느 한 요소가 0에 가까우면 모델이 나머지 영역에서 아무리 강해도 최종 작업 성공률은 급격히 낮아진다.

현재 Lumina는 Hermes보다 전반적으로 열등한 Harness가 아니다. 특히 다음은 Lumina가 강하거나 제품 요구에 더 잘 맞는다.

- Backend가 소유하는 영속 Run과 순번 Run event
- 재접속 snapshot과 event replay
- 동일 Session의 단일 Run, 추가 요청 Queue, 서로 다른 Session의 병렬 실행
- Tool call ID 기준 결과 재사용과 중복 side effect 방지
- Project·사용자·조직 권한을 포함한 Run snapshot
- Artifact 생성·구조 검증·렌더 검증
- 위험 Tool 승인과 사용자·Project 데이터 격리

반면 순수 Agent 성공률을 더 끌어올리는 관점에서는 Hermes 대비 다음 격차가 남아 있다.

1. Provider의 실제 요청별 usage를 반영하는 컨텍스트 압력 자기보정과 anti-thrashing
2. MCP·Plugin Tool이 많아질 때 schema를 필요 시점에만 공개하는 progressive tool disclosure
3. 단순 어휘 중첩을 넘어서는 의미 기반 Memory recall과 비동기 prefetch
4. 본 작업 모델에게 Memory 추출·UI control 계약까지 함께 맡기는 상시 prompt 부담
5. Provider·stream·output truncation·불완전 Tool Call을 더 세밀하게 구분하는 recovery policy
6. 독립 하위 작업을 격리된 context에서 처리하는 bounded delegation
7. 동일 task bank를 반복 실행해 pass@1, 일관성, 비용과 복구율을 비교하는 Agent eval harness

가장 먼저 해야 할 일은 기능 추가가 아니라 **반복 가능한 평가 기준선과 context/tool schema 계측을 만드는 것**이다. 그 다음 실제 실패가 확인된 순서로 context calibration, progressive tool disclosure, memory recall, recovery taxonomy를 적용해야 한다. Subagent나 별도 critic은 그 이후에 eval로 이득이 증명될 때만 도입하는 편이 안전하다.

## 2. 순수 Agent 성능에 영향을 주는 Harness 요소

### 2.1 컨텍스트 엔지니어링

모델이 무엇을 알고 판단할지를 결정하는 가장 큰 요소다.

- System instruction의 명확성과 우선순위
- 현재 작업에 필요한 정보만 선택하는 능력
- 파일·문서·Memory의 적시 검색
- 오래된 대화와 Tool 결과의 압축 순서
- 목표, 사용자 제약, 실패 이력, 완료된 side effect와 Artifact 보존
- 불필요하거나 충돌하는 정보 제거
- Tool schema와 출력 예약분을 제외한 실제 입력 예산 계산

컨텍스트가 길다고 성능이 좋아지는 것은 아니다. 중요한 것은 필요한 순간에 정확한 정보를 넣고, 압축할 때 미래 행동에 필요한 구조를 잃지 않는 것이다. `assistant tool call → tool result` 관계를 깨거나 성공·실패 시도의 차이를 지우면 Agent는 같은 행동을 반복하거나 이미 완료한 side effect를 다시 실행할 수 있다.

공식 Agent engineering 자료도 장기 작업의 핵심으로 compaction, structured memory, 적시 검색을 강조한다.

- Anthropic: <https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
- Anthropic: <https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents>

### 2.2 Tool 설계

Agent는 Tool로 관찰할 수 있는 것만 보고, Tool로 표현할 수 있는 것만 행동한다.

- Tool 이름과 설명이 모델 관점에서 구별되는가
- 입력 schema가 모호하지 않은가
- 결과가 짧고 구조화되어 있는가
- 오류가 code, stage, retryable 여부와 복구 지침을 제공하는가
- 너무 크거나 너무 잘게 나뉘지 않았는가
- 재호출해도 안전하거나 idempotency key가 있는가
- 현재 권한·설치·환경에서 실제 사용할 수 있는 Tool만 노출되는가
- Tool이 많을 때 필요 시점에 검색·설명·호출할 수 있는가

Tool 설명과 schema 품질만으로도 선택 정확도와 호출 성공률이 달라진다.

- Anthropic: <https://www.anthropic.com/engineering/writing-tools-for-agents>

### 2.3 Agent loop와 상태 전이

모델 호출 횟수보다 호출 사이의 상태 전이가 중요하다.

- Observe → Plan → Act → Observe 흐름
- 계획을 만들고 수정하거나 폐기하는 기준
- Tool 결과를 본 뒤 재계획하는 능력
- 동일 실패 반복 감지
- 완료와 중단 조건
- Turn·Token·시간·비용 budget
- retry, backoff, alternative tool, rollback
- 사용자에게 질문해야 하는 경우와 합리적으로 진행할 경우의 구분

좋은 loop는 모든 행동을 고정 workflow로 강제하지 않는다. 명확한 종료 조건과 안전한 복구 수단을 주면서 모델이 상황에 맞게 행동할 여지를 남긴다.

### 2.4 런타임 생존성과 상태 관리

장기 Agent에서는 성능의 일부가 아니라 성능의 전제다.

- Run 상태 영속화
- append-only event log
- 중단 후 resume와 event replay
- worker ownership과 중복 실행 방지
- timeout과 retry
- streaming parser 안정성
- 네트워크 단절과 Provider 편차 복구
- Tool idempotency와 완료 checkpoint

작업을 90% 올바르게 수행하다 transport 오류로 죽으면 task success는 0이다.

### 2.5 검증과 자기수정

Agent가 완료했다고 말하는 것과 실제 완료는 다르다.

- 코드 작업 후 test·lint·typecheck
- UI 작업 후 실제 브라우저 상태와 console 확인
- DB/API 작업 후 최종 state 검사
- 생성 파일 존재·내용·렌더 검증
- 요구사항 체크리스트 대조
- 실패 시 원인 분류 후 수정

핵심은 자기평가 문장을 길게 쓰게 하는 것이 아니라, 외부 상태를 확인할 검증 Tool과 명확한 success criteria를 제공하는 것이다.

### 2.6 실행 환경

- 정확한 cwd와 workspace
- 필요한 dependency와 CLI
- 인증·권한·네트워크 상태
- 격리된 sandbox 또는 worktree
- 빠르고 정확한 코드·문서 검색
- 재현 가능한 test fixture

환경 관찰이 틀리면 모델은 잘못된 세계에 대해 그럴듯하게 추론한다.

### 2.7 오케스트레이션과 병렬화

멀티 Agent는 자동적인 성능 향상이 아니다.

효과적인 조건은 작업이 독립적이고, context와 수정 영역이 분리되며, 결과 합성 계약이 있을 때다. 반대로 동일 상태를 여러 Agent가 수정하거나 위임·보고 과정에서 정보가 손실되면 단일 Agent보다 나빠질 수 있다.

기본값은 강한 단일 Agent와 독립 Tool의 병렬 실행으로 두고, subagent는 context 격리나 병렬 탐색의 이득이 eval로 확인된 작업에만 적용하는 편이 좋다.

### 2.8 Eval과 관측성

Eval은 한 번의 runtime 추론을 직접 개선하지는 않지만 Harness 개선 속도와 방향을 결정한다.

최소 측정 항목은 다음과 같다.

- task end-state 기준 `pass@1`
- 동일 task 반복 실행의 일관성
- Tool 선택·입력·호출 성공률
- 실패 후 복구 성공률
- 중도 중단률과 중복 side effect 비율
- 평균 model turn, input/output token, 비용, wall time
- context compaction 전후 목표·근거 보존률
- 동일 실패 반복 횟수

최종 답변만 아니라 전체 trajectory를 읽을 수 있어야 한다. Agent 평가는 모델만이 아니라 모델과 Harness의 결합을 측정한다.

- Anthropic: <https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents>
- OpenAI: <https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/>

### 2.9 순수 성능과 체감 성능의 경계

다음은 순수 Agent 성공률에 직접 포함된다.

- Context 구성과 압축
- Tool affordance와 권한
- Loop와 상태 전이
- 오류 복구
- 검증
- 장기 실행 생존성

다음은 주로 체감 성능이나 효율이다.

- Streaming animation
- 타이핑 또는 reveal 속도
- UI 진행 표시
- Prompt cache
- 서버 응답 latency

다만 latency가 timeout이나 사용자 취소를 유발하고, prompt cache 비용 때문에 사용할 수 있는 context나 반복 검증이 줄어든다면 간접적으로 실제 성공률에 영향을 준다.

## 3. 비교 범위와 근거

### 3.1 Lumina

- `apps/server/src/lumina/agent/executor.py`
  - `_conversation_messages`
  - `_run_tool_calls`
  - `_compact_runtime_context`
  - `_retry_provider_request`
  - `_provider_prompt_cache_key`
- `apps/server/src/lumina/context/service.py`
  - `prepare_context`
  - `compact_runtime_messages`
  - `_context_budget`
- `apps/server/src/lumina/runs/service.py`
  - `create_run`
  - `activate_run_skill`
  - `retry_plan_step`
  - Run event와 Queue 처리
- `apps/server/src/lumina/memories/service.py`
  - `select_relevant_memories`
- `apps/server/src/lumina/project_memories/service.py`
  - `select_relevant_project_memories`

### 3.2 Hermes

- `.examples/hermes-agent/agent/conversation_loop.py`
- `.examples/hermes-agent/agent/context_compressor.py`
- `.examples/hermes-agent/agent/turn_retry_state.py`
- `.examples/hermes-agent/agent/retry_utils.py`
- `.examples/hermes-agent/model_tools.py`
- `.examples/hermes-agent/tools/tool_search.py`
- `.examples/hermes-agent/agent/memory_manager.py`
- `.examples/hermes-agent/agent/memory_provider.py`
- `.examples/hermes-agent/tools/delegate_tool.py`
- `.examples/hermes-agent/batch_runner.py`
- `.examples/hermes-agent/run_agent.py`

`.examples/`는 참고 전용으로 읽었으며 Lumina의 import, build, test 또는 package 대상에 포함하지 않았다.

## 4. 종합 비교

| Harness 영역 | Hermes | 현재 Lumina | 판정 |
|---|---|---|---|
| Agent loop | 긴 운영 이력에서 축적된 세분화 recovery branch와 `TurnRetryState` | 단순한 구조, 최근 partial response·context·empty response recovery 강화 | Hermes 우위, 격차 축소 중 |
| Context 압축 | 실제 prompt usage 보정, anti-thrash, Tool pruning, 구조화 요약, cooldown | persistent compaction, Tool pair 보존, payload microcompact, 보수적 summary | Hermes 우위 |
| Tool surface | toolset, `check_fn`, schema sanitization, progressive tool disclosure | 조건부 Builtin Tool과 Run별 MCP Tool 전체 schema | MCP가 많을 때 Hermes 우위 |
| Tool 실행 | Tool registry, approval, dynamic schema, 다양한 환경 | 병렬 Tool 실행, 승인, call ID 결과 재사용, 권한 재검증 | 비슷하며 Lumina의 영속 중복 방지가 강함 |
| Memory recall | pluggable provider, turn별 prefetch, 비동기 sync | 사용자·Project Memory snapshot, deterministic lexical ranking | 감사성은 Lumina, recall 품질은 Hermes 우위 |
| Run durability | Session DB가 있으나 background delegation 일부는 process-local | Backend-owned Run, event replay, worker ownership, Queue | Lumina 우위 |
| Delegation | 격리 context·terminal, batch fan-out, depth/concurrency/summary budget | 독립 Tool 병렬 실행만 있고 subagent 없음 | 복합 탐색에서 Hermes 우위 가능 |
| Prompt cache | conversation 동안 system prompt와 toolset의 byte stability를 강하게 보호 | static digest와 cache key가 있으나 Run별 초기 prompt와 Tool surface가 일찍 달라질 수 있음 | 효율 측면 Hermes 우위 |
| Trajectory·batch | 선택적 trajectory 저장, batch runner, tool 통계, resume | Run event와 DB trace는 강하지만 반복 eval runner·grader 없음 | 운영 trace는 Lumina, 실험 반복성은 Hermes 우위 |
| Artifact 검증 | 범용 terminal/file/browser 중심 | 문서 구조·페이지·렌더 검증을 제품 기능으로 보유 | Lumina 우위 |
| 기업 권한·격리 | 개인 Agent profile 중심 | Organization → Project → Session → Run 격리와 서버 재검증 | Lumina 우위 |

## 5. Hermes 대비 Lumina의 구체적 부족점

### G1. 요청별 실제 usage를 이용한 Context 압력 자기보정 부족

**현재 Lumina**

- `prepare_context`는 추정 token을 계산하고 `run.usage_json["input_tokens"]`와 비교해 큰 값을 사용한다.
- `_store_usage`는 각 model turn의 input token을 Run 누계에 더한다.
- 따라서 누계 input token은 현재 단일 요청의 prompt 크기와 의미가 다르다.
- in-flight loop의 `compact_runtime_messages`는 별도 추정치를 사용하고 Tool pair를 보존하지만, Provider가 방금 보고한 실제 prompt 크기로 estimator ratio를 계속 보정하는 구조는 없다.
- P-GPT는 고정 padding을 적용하고, 관찰된 context overflow에서 lower bound를 조정하는 방어가 있으나 endpoint·model별 추정 오차를 지속 학습하지는 않는다.

**Hermes**

- `ContextCompressor.update_from_response`가 마지막 실제 `prompt_tokens`를 별도 보관한다.
- 추정치가 높더라도 직전 실제 요청이 threshold 아래였으면 불필요한 preflight compression을 잠시 미룬다.
- 압축 후에도 실제 prompt가 threshold를 넘는지 확인해 system prompt + Tool schema라는 비압축 floor를 감지한다.
- 반복 압축이 효과가 없을 때 strike와 cooldown으로 thrashing을 막는다.

**영향**

- 과대 추정: 불필요한 압축으로 근거와 작업 이력이 빨리 손실된다.
- 과소 추정: Provider context 오류와 추가 recovery turn이 발생한다.
- schema floor를 모르면 메시지만 반복해서 줄이고도 threshold를 벗어나지 못할 수 있다.

**판정: P1**

`last_request_input_tokens`, estimator ratio, post-compaction verification을 Run 누계 usage와 분리해야 한다. 적용 전에는 최소 100 Run fault-injection benchmark로 오탐 압축률과 context error율을 측정해야 한다.

### G2. MCP Tool schema의 Progressive Disclosure 부재

**현재 Lumina**

- `_run`은 조건부 Builtin Tool 뒤에 `WORKSPACE_TOOL_SCHEMAS`와 `mcp_runtime.prepare_run`이 반환한 모든 MCP schema를 Provider 요청에 넣는다.
- `_context_budget`은 Tool schema token을 입력 예산에서 빼므로 Tool이 많아질수록 대화에 쓸 수 있는 budget이 직접 줄어든다.
- Builtin Tool 일부는 output mode와 request intent에 따라 조건부 노출되어 불필요한 surface를 줄이고 있다.

**Hermes**

- `get_tool_definitions`가 toolset과 disabled toolset으로 surface를 제한한다.
- registry의 `check_fn`을 통과한 실제 사용 가능 Tool만 모델에 노출한다.
- schema sanitizer가 backend별 JSON schema 호환 문제를 줄인다.
- MCP·Plugin schema가 context window의 설정 비율을 넘으면 `tool_search`, `tool_describe`, `tool_call` 세 bridge 뒤로 미룬다.

**영향**

- Tool 선택 혼동 증가
- 항상 지불하는 schema token 증가
- prompt cache prefix 확대
- 실제 대화·근거에 사용할 context 감소
- 설치됐지만 현재 쓸 수 없는 Tool을 모델이 호출할 가능성

**판정: P1**

Lumina에는 Project·Run 권한을 유지한 `search_tools → describe_tool → call_tool` 계층이 필요하다. 단, core Tool과 사용자가 명시한 `$MCP`는 즉시 노출하고, 많은 비선택 MCP만 threshold 기반으로 defer하는 방식이 적절하다.

### G3. Memory recall이 어휘 중첩 중심

**현재 Lumina**

- 사용자 Memory는 communication preference, identity, role을 항상 우선하고 나머지는 query term overlap으로 선택한다.
- Project Memory는 `project_rule`을 항상 우선하고 나머지는 한글 bigram과 term overlap으로 선택한다.
- 선택 결과를 Run snapshot에 고정하므로 감사와 재현성은 좋다.
- final response 안의 숨은 Memory envelope를 본 작업 모델이 함께 생성한다.

**Hermes**

- `MemoryProvider` ABC를 통해 semantic backend를 교체할 수 있다.
- `prefetch` 결과를 현재 user message에 ephemeral context로 주입하고 영속 conversation 원문은 바꾸지 않는다.
- turn 종료 후 `sync_turn`과 다음 turn을 위한 `queue_prefetch`를 background worker에서 처리한다.
- 외부 memory provider는 하나만 허용해 Tool schema와 conflicting recall을 제한한다.

**영향**

- 동의어·간접 표현·개념적으로 관련된 과거 지식을 놓친다.
- recall과 memory 추출을 본 작업 응답 계약에 섞으면 주 작업의 attention과 output contract가 복잡해진다.
- 반대로 semantic recall을 무제한 도입하면 기업 환경의 재현성·권한·감사성이 약해질 수 있다.

**판정: P1**

Lumina의 immutable Run snapshot은 유지해야 한다. 후보 생성은 lexical + embedding hybrid로 개선하되 최종 주입 대상과 revision을 Run 시작 시 고정해야 한다. 명시적 “기억해”는 local-first를 유지하고, 일반 turn의 후보 추출은 본 답변 stream 밖의 비동기 경로로 분리하는 편이 좋다.

### G4. 본 작업 Prompt에 Control-plane 계약이 많이 섞임

**현재 Lumina**

`_conversation_messages`는 기본 실행 계약 외에도 Run에 따라 다음을 system 영역에 추가한다.

- Output mode 계약
- File intent JSON 계약
- Memory capture envelope 계약
- Skill activation 계약
- Plan efficiency 계약
- Artifact 형식·길이·렌더 계약
- Web research efficiency 계약
- Project·조직·개인 instruction
- Skill과 MCP wrapper instruction

이 계약은 제품 정확성에 필요하지만 같은 모델이 동시에 판단해야 할 목표가 많아진다.

**Hermes**

- core Tool surface와 system prompt의 안정성을 강하게 보호한다.
- capability를 CLI command + Skill, service-gated Tool, Plugin, MCP 순으로 core 밖에 두는 narrow-waist 원칙을 사용한다.
- Memory sync와 prefetch 같은 control-plane 작업을 가능한 한 turn 밖에서 처리한다.

**영향**

- 단순 질문에서도 불필요한 판단 항목이 늘어난다.
- hidden envelope, UI classification, plan, artifact 규칙이 본 작업의 instruction following과 경쟁할 수 있다.
- system prefix가 Run별로 빨리 달라져 conversation prompt cache 효율이 낮아질 수 있다.

**판정: P1**

모든 계약을 제거하면 안 된다. 다음처럼 분리하는 것이 적절하다.

- 안전·권한·완료·검증 불변식: core system에 유지
- 현재 output mode처럼 Run에 필요한 계약: 짧은 turn control block으로 유지
- Memory 후보 추출: post-turn background 경로
- File intent UI control: 본 작업 의미 판단이 꼭 필요한 경우에만 Tool로 노출
- Skill 선택: 사용자의 원칙대로 모델 기반을 유지하되, activation 결과가 instruction을 전달하도록 하고 eager keyword heuristic은 사용하지 않음
- 대형 형식 지침: 선택된 Skill 또는 Artifact Tool 설명으로 지연 로딩

### G5. Recovery taxonomy와 Turn retry state가 Hermes보다 거침

**현재 Lumina**

- 첫 출력 전 retryable Provider 오류는 bounded retry한다.
- `Retry-After`를 반영하고 context overflow는 reactive compaction으로 보낸다.
- 순수 text partial response는 continuation과 dedupe로 복구한다.
- Tool call이 불완전하거나 side effect 여부가 불명확하면 자동 재실행하지 않는 안전 경계가 있다.
- empty response와 일부 gateway schema 차이도 복구한다.

**Hermes**

- `TurnRetryState`가 auth refresh, format repair, context compression, output continuation 등 turn별 일회성 recovery 여부를 분리한다.
- jittered backoff와 일부 endpoint-specific rate guard를 사용한다.
- reasoning budget exhaustion, content filter termination, text truncation, mid-tool-call stream stall을 서로 다른 경로로 처리한다.
- Tool call이 실행되지 않았음이 확인된 경우와 이미 text가 사용자에게 전달된 경우를 구분한다.

**영향**

- 서로 다른 오류가 같은 `provider_request` 또는 stream 실패로 뭉치면 안전하게 복구할 수 있는 범위도 수동 재시도로 남는다.
- 반대로 분류 없이 retry만 늘리면 중복 출력·중복 side effect·비용 증가가 발생한다.

**판정: P1**

Hermes의 거대한 조건문을 복사하지 말고, Lumina의 Provider adapter가 반환하는 `stage`, `code`, `retryable`, `output_started`, `tool_call_started`, `side_effect_checkpoint`를 입력으로 받는 명시적 recovery policy와 Turn retry state를 설계해야 한다.

### G6. Bounded delegation 부재

**현재 Lumina**

- 한 model response에 나온 독립 Tool call을 `asyncio.gather`와 semaphore로 병렬 실행한다.
- 같은 Session의 Run은 하나만 실행한다.
- 별도 subagent context, 결과 summary budget, spawn depth와 parent-child Run 관계는 없다.

**Hermes**

- `delegate_task`가 격리된 context와 terminal session을 가진 child agent를 만든다.
- batch fan-out, concurrency cap, spawn depth, leaf/orchestrator role, timeout을 둔다.
- child summary가 parent context를 넘치게 하지 않도록 남은 headroom 기준으로 자르고 전체 결과는 파일에 보존한다.

**영향**

- 큰 코드베이스 탐색, 여러 독립 자료 조사, 구현과 검증 분리처럼 context isolation이 유리한 작업에서 Lumina 단일 context가 빨리 오염될 수 있다.
- 반대로 모든 작업을 멀티 Agent로 만들면 비용·조정·충돌이 늘어난다.

**판정: P2**

도입한다면 process-local task가 아니라 Lumina의 영속 계층에 맞는 `Parent Run → Child Run`으로 설계해야 한다. child는 Project 권한·Provider·extension revision snapshot을 상속하되 별도 context와 budget을 가져야 한다. 같은 파일을 수정하는 child를 병렬 실행해서는 안 된다.

### G7. 반복 가능한 Agent Eval harness 부재

**현재 Lumina**

- Run event, ToolExecution, usage, plan, compaction과 Artifact 상태가 DB에 남아 production trace는 풍부하다.
- backend test는 실행 계약의 회귀를 잘 막지만 실제 모델의 task completion을 여러 trial로 비교하는 runner와 grader는 없다.

**Hermes**

- 선택적으로 trajectory를 JSONL로 저장한다.
- `batch_runner.py`가 dataset 병렬 실행, resume, Tool 통계와 trajectory 수집을 지원한다.
- `mini_swe_runner.py`처럼 특정 task runner도 있다.
- 다만 범용 end-state grader까지 완성된 것은 아니므로 Hermes 자체도 모든 평가 문제가 해결된 것은 아니다.

**영향**

- prompt, Tool 설명, context 정책을 바꾼 뒤 실제 성공률이 올랐는지 판단하기 어렵다.
- 한 번 성공한 수동 QA를 일반 성능 향상으로 오인할 수 있다.
- 모델 변경과 Harness 변경의 효과가 섞인다.

**판정: P0 측정 기반**

코드 변경보다 먼저 다음 최소 runner가 필요하다.

1. 고정 model/provider/effort와 Run snapshot으로 task bank 실행
2. task당 최소 3 trial
3. DB·파일·Artifact·HTTP state를 확인하는 code grader
4. task completion, 일관성, Tool 오류, recovery, token, 비용, 시간 집계
5. 전체 Run trajectory와 실패 taxonomy export
6. baseline과 후보 Harness의 paired comparison

### G8. Prompt cache 안정성은 구현돼 있지만 conversation 전체 최적화는 부족

**현재 Lumina**

- `_provider_prompt_cache_key`는 user scope, provider, model, 첫 system message와 정렬된 Tool schema digest로 cache key를 만든다.
- Run마다 output mode, 사용 가능한 Artifact/Web Tool, Skill/MCP 선택이 달라질 수 있어 초반 prefix가 쉽게 변한다.
- prompt cache hit와 compaction·latency·task success의 상관관계는 아직 운영 지표로 보이지 않는다.

**Hermes**

- conversation 동안 system prompt byte stability와 Tool set stability를 핵심 불변식으로 둔다.
- Skill command는 system prompt를 재작성하지 않고 user message로 주입하는 경로를 사용한다.
- Tool search가 schema floor를 제한한다.

**판정: P2 효율 최적화**

Prompt cache는 원칙적으로 raw intelligence가 아니라 비용·지연 최적화다. 따라서 P0 성공률 문제보다 먼저 적용하면 안 된다. 다만 긴 대화의 지연과 비용이 줄면 더 많은 검증 turn과 긴 context를 사용할 수 있어 간접적인 성능 이득이 생긴다.

### G9. 범용 verifier/evaluator loop가 없음

Lumina에는 Artifact별 강한 검증이 있고 core 실행 계약도 final 전 최강 증거로 검증하도록 요구한다. 그러나 모든 task에 독립 evaluator를 자동 호출하는 구조는 없다. Hermes도 모든 turn에 별도 critic을 붙이지는 않지만 delegation과 다양한 Tool 환경으로 구현·검증을 분리할 수 있다.

**판정: P2, 선택 적용**

모든 답변에 critic을 추가하면 비용과 latency가 늘고 잘못된 자기수정이 생길 수 있다. 코드 변경, 배포, 고위험 업무, 장문 보고서처럼 end-state 검증 가치가 큰 task에만 verifier policy를 적용하고 eval로 순효과를 확인해야 한다.

## 6. Lumina가 유지해야 할 우위

Hermes를 참고하더라도 다음 Lumina 불변식은 약화하면 안 된다.

### 6.1 영속 Run과 event replay

Hermes의 background delegation 일부는 process-local이다. Lumina는 브라우저나 Backend 연결이 끊겨도 Run이 지속되고 event replay로 복구되어야 한다. 새 delegation이나 background Tool도 이 영속 모델에 맞춰야 한다.

### 6.2 Project·사용자·조직 격리

Hermes의 개인 profile 모델을 그대로 가져오면 Lumina의 조직 권한과 공유 경계를 잃는다. Memory, Tool search, subagent는 항상 Backend에서 scope와 revision을 재검증해야 한다.

### 6.3 Tool side effect 안전성

Hermes의 공격적인 retry branch를 그대로 복사해서는 안 된다. Lumina의 원칙은 다음과 같아야 한다.

- side effect가 실행되지 않았음이 입증된 경우에만 자동 재시도
- 완료 Tool은 call ID와 checkpoint로 결과 재사용
- 불명확한 상태는 자동 재실행하지 않고 사용자에게 재개 가능 상태 제공
- write/send/delete 계열은 idempotency key 또는 명시적 checkpoint 없이는 retry 금지

### 6.4 Run snapshot 재현성

Semantic Memory와 dynamic Tool discovery를 도입해도 실제 Run은 사용한 Memory revision, Tool schema digest, Skill/MCP revision과 Provider 설정을 snapshot으로 남겨야 한다.

### 6.5 모델 기반 Skill 선택

Skill 선택을 eager keyword heuristic으로 되돌리면 안 된다. 사용자의 의도와 Skill 설명을 모델이 판단하고 실제 `activate_skill` event 뒤에 UI가 반응해야 한다. 최적화 대상은 판단을 없애는 것이 아니라 후보 목록과 instruction 전달 비용을 줄이는 것이다.

## 7. 권장 실행 순서

### Phase 0 — 측정 기준선

1. Agent eval task bank와 runner
2. Run trajectory export
3. context estimate, provider prompt usage, Tool schema token, cache hit 계측
4. 429·503·SSE 절단·context overflow·worker restart fault injection

완료 조건:

- 같은 model 설정에서 baseline pass@1과 반복 일관성을 수치로 제시할 수 있음
- 실패가 model, context, Tool, provider, runtime, grader 중 어디에 속하는지 분류 가능

### Phase 1 — Context와 Tool surface

1. 요청별 실제 prompt usage와 누계 usage 분리
2. estimator ratio와 post-compaction effectiveness 기록
3. schema floor와 compression anti-thrash
4. 권한 보존형 progressive Tool disclosure
5. Provider별 schema sanitizer

완료 조건:

- 불필요한 compaction 감소
- context error 감소
- MCP 수가 증가해도 core prompt token이 상한 안에 유지
- Tool 선택 정확도와 task success가 baseline보다 개선

### Phase 2 — Memory와 Control-plane 분리

1. lexical + semantic hybrid recall
2. Run 시작 시 최종 Memory snapshot 고정
3. 일반 Memory 후보 추출의 post-turn 비동기화
4. 대형 Artifact·Skill instruction의 지연 로딩

완료 조건:

- 관련 Memory recall 증가
- 잘못된 Memory 주입과 민감 정보 노출이 증가하지 않음
- 단순 task의 system token과 latency 감소

### Phase 3 — Recovery policy

1. Turn retry state
2. provider/stream/output/tool-call failure taxonomy
3. jitter와 endpoint circuit breaker
4. safe continuation과 side-effect checkpoint 연계

완료 조건:

- transient failure recovery 증가
- 중복 출력과 중복 side effect가 0에 가까움
- 같은 실패의 맹목 반복 감소

### Phase 4 — 선택적 Delegation과 Verification

1. Parent Run → Child Run 모델
2. context·budget·Tool scope 격리
3. child summary headroom 제한과 원문 Artifact 보존
4. 코드·고위험·장문 task에만 verifier policy 적용

완료 조건:

- 독립 복합 task에서 성공률 또는 wall time이 유의하게 개선
- 단순 task의 비용·latency 회귀 없음
- child 충돌과 권한 누출 없음

## 8. 최종 판정

| 목표 | 현재 판정 |
|---|---|
| 장시간 Run 생존성과 재접속 복구 | Lumina 우위 |
| Tool side effect 중복 방지 | Lumina 우위 또는 동급 |
| 기업 권한·Project 격리 | Lumina 우위 |
| Context 압축의 정교함 | Hermes 우위 |
| 대형 Tool catalog 처리 | Hermes 우위 |
| Memory recall 유연성과 의미 검색 | Hermes 우위 |
| Provider 오류 taxonomy와 adaptive recovery | Hermes 우위 |
| 복합 task의 context 격리·delegation | Hermes 우위 가능, eval 필요 |
| 운영 trace | Lumina 우위 |
| 반복 가능한 Agent 실험 runner | Hermes 우위, 양쪽 모두 grader 강화 필요 |

Lumina가 Hermes 수준의 순수 Agent 성능에 접근하기 위해 가장 중요한 것은 Hermes의 기능을 많이 복사하는 것이 아니다. **Lumina의 강한 영속 Run·권한·감사 모델을 유지하면서, 실제 usage 기반 context calibration, progressive Tool disclosure, 의미 기반이되 snapshot 가능한 Memory, 명시적 recovery state, 반복 가능한 eval을 추가하는 것**이다.

우선순위를 한 줄로 줄이면 다음과 같다.

> Eval 기준선 → Context usage calibration → Tool progressive disclosure → Memory/Control-plane 분리 → Recovery taxonomy → 제한적 delegation·verifier

# Deep Analysis Workflow

## 1. 목적

Deep Analysis는 여러 채팅 세션에서 사람이 순서대로 수행하던 작업을 Node와 Edge로 연결해 자동 실행하는 기능입니다. 분석 방법론을 별도로 발명하거나 결론을 감사 장부로 변환하는 시스템이 아닙니다.

핵심 모델은 다음과 같습니다.

- Mission: 한 Workflow를 담는 작업 단위
- Node: 하나의 독립된 Lumina 채팅 세션
- Edge: 앞 Node의 결과를 다음 Node의 입력으로 전달하는 연결
- Run: Node 채팅 세션에서 실행되는 한 번의 Agent Run

## 2. 생성과 편집

새 Mission은 제목과 목적을 바탕으로 한 번의 LLM 호출로 초기 Node·Edge를 자동 설계합니다. 이 호출이 실패하거나 유효한 DAG를 만들지 못하면 규칙 기반 기본 Workflow를 즉시 사용합니다. preset 선택이나 저장 Pattern 적용은 제공하지 않습니다.

사용자는 Canvas에서 다음 항목을 직접 편집합니다.

- Node 제목과 목적
- Node에 실제로 전달할 프롬프트
- Node 위치
- Node 추가·삭제
- Edge 연결·삭제

Workflow는 순환하지 않는 DAG여야 합니다. 같은 Node를 자기 자신과 연결하거나 순환 Edge를 저장할 수 없습니다.

## 3. 실행 계약

실행기는 활성 Workflow를 위상 순서로 처리합니다.

1. 선행 Node가 없거나 모두 완료된 Node를 찾습니다.
2. 해당 Node 전용 채팅 세션이 없으면 생성합니다.
3. Mission 설명, Node 프롬프트, Project 입력 자료와 선행 Node 산출물을 사용자 메시지로 구성합니다.
4. 그 채팅 세션에 일반 Agent Run 하나를 생성합니다.
5. Run의 자연스러운 Markdown 답변을 Node 출력으로 저장합니다.
6. 뒤 Node는 연결된 선행 Node 출력 전체를 입력 문맥으로 받습니다.
7. 실행 가능한 Node가 남지 않으면 Mission을 완료합니다.

Node 재실행은 같은 Node 채팅 세션을 계속 사용하되 새 Run을 만듭니다. Mission을 다른 Project로 이동하거나 삭제할 때는 Node별 채팅 세션도 함께 이동하거나 삭제합니다.

## 4. 출력과 인용

Node 출력은 Agent가 작성한 Markdown을 그대로 보존하고 렌더링합니다. 파일 경로와 별도의 원문 보기 영역을 중복 제공하지 않습니다.

`[Claim:UUID]`, Claim Ledger, Evidence 객체, Open Issue, Quality Gate 같은 내부 표식은 생성하지 않습니다. 출처 표기가 필요한 작업은 Node 프롬프트에서 일반 Markdown 링크나 각주를 요구합니다.

## 5. 비용 원칙

기본 비용 단위는 `초기 Workflow 설계 1회 + 실행된 Node 수 × Node당 Agent Run 비용`입니다. 다음 반복 LLM 호출은 없습니다.

- 실행 중 Workflow 재계획
- Claim·Evidence 추출
- Quality Gate 판정
- 완료 계약 또는 예외 승인 판정

비용 화면은 실제 Node Run 사용량만 집계합니다.

## 6. 화면 계약

Mission 화면은 두 탭만 제공합니다.

- Workflow: Canvas, Node·Edge 편집, Node 상세, 실제 프롬프트와 렌더링된 출력
- 실행 기록: Node 대기·시작·완료·실패 등 실행 이벤트

Node 상세 영역의 세로 경계는 포인터 드래그와 키보드 화살표로 폭을 조절할 수 있으며 마지막 폭을 기억합니다. Canvas의 빈 영역은 드래그해 이동할 수 있습니다.

## 7. 제외한 기능

다음 기능은 현재 Deep Analysis 계약에 포함하지 않습니다.

- preset·저장 Pattern 기반 초기 Workflow 생성
- 실행 중 LLM 기반 Node 추가·삭제·분기 판단
- Mission Charter와 별도 Completion Contract
- Claim Ledger, Evidence Ledger, Open Issue
- Quality Gate와 waiver 결정
- 보고서 Node 강제 또는 정해진 최종 보고서 형식

필요한 검토, 비교, 보고서 작성은 각각 일반 Node의 프롬프트로 표현합니다.

## 8. 데이터 전환

개발 초기 단계이므로 기존 Mission 데이터는 호환 변환하지 않습니다. migration `0055`는 기존 Mission과 Mission 전용 채팅 세션을 삭제하고 Workflow Node에 `conversation_id`를 추가합니다. 새 Mission은 자동 설계된 새 계약으로 다시 생성합니다.

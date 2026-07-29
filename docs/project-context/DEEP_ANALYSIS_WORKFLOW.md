# Deep Analysis Workflow

## 1. 목적

Deep Analysis는 여러 채팅 세션에서 사람이 순서대로 수행하던 작업을 Node와 Edge로 연결해 자동 실행하는 기능입니다. 분석 방법론을 별도로 발명하거나 결론을 감사 장부로 변환하는 시스템이 아닙니다.

핵심 모델은 다음과 같습니다.

- Mission: 한 Workflow를 담는 작업 단위
- Node: 하나의 독립된 Lumina 채팅 세션
- Edge: 앞 Node의 결과를 다음 Node의 입력으로 전달하는 연결
- Run: Node 채팅 세션에서 실행되는 한 번의 Agent Run

## 2. 생성과 편집

`새 분석`을 누르면 LLM 호출을 기다리지 않고 빈 수동 Workflow Mission을 즉시 생성합니다. Canvas에는 MISSION root와 Node 편집 도구를 바로 표시하며, 사용자는 Node를 추가하고 유형·제목·프롬프트를 설정한 뒤 Edge로 연결합니다. AI 설계가 필요할 때만 Workflow 재생성 버튼에서 지시를 입력해 Node·Edge 초안을 만들 수 있으며, 실패하면 현재 수동 Workflow를 보존합니다. preset 선택이나 저장 Pattern 적용은 제공하지 않습니다.

MISSION 설정에는 선택적 연구 시작일·종료일과 웹 출처 정책을 함께 저장합니다. 웹 출처 정책은 전체 웹, 지정 도메인 우선, 지정 도메인만 허용의 세 모드를 제공하고 별도 제외 도메인을 둘 수 있습니다. 지정 도메인만 허용하는 경우 검색 결과와 직접 본문 조회 모두 Backend에서 정책을 강제합니다.

사용자는 Canvas에서 다음 항목을 직접 편집합니다.

- Node 제목과 목적
- Node에 실제로 전달할 프롬프트
- Node 위치
- Node 추가·삭제
- Edge 연결·삭제

Workflow는 순환하지 않는 DAG여야 합니다. 같은 Node를 자기 자신과 연결하거나 순환 Edge를 저장할 수 없습니다.

## 3. 실행 계약

실행기는 활성 Workflow를 위상 순서로 처리하되, 서로 의존하지 않는 준비 완료 Node는 설정된 사용자·서버 동시 실행 한도 중 더 작은 값까지 함께 시작합니다. 이미 실행 중인 Node는 같은 fan-out 한도에 포함하며, 합류 Node는 모든 선행 Node가 완료된 뒤에만 실행합니다.

같은 fan-out 묶음의 Node 프롬프트는 `Mission·고정 자료 version·공통 선행 산출물·연구 정책·추가 지침`을 byte-stable한 공통 앞부분으로 먼저 직렬화하고, Node key·제목·목적·단계별 지시처럼 분기마다 달라지는 값은 그 뒤의 Node 전용 부분에 둡니다. Context manifest의 `prefixHash`는 이 공통 앞부분과 정확한 파일 version·content hash·dependency lineage를 함께 고정합니다. timestamp, Run ID, 진행 상태처럼 실행마다 달라지는 값은 공통 앞부분에 넣지 않습니다.

1. 선행 Node가 없거나 모두 완료된 Node를 모두 찾습니다.
2. 해당 Node 전용 채팅 세션이 없으면 생성합니다.
3. Mission 설명, 사용자가 명시적으로 연결한 Project 입력 자료, 선행 Node 산출물과 Node 전용 프롬프트를 사용자 메시지로 구성합니다. 연결한 자료가 없으면 Project 파일을 자동 포함하지 않습니다.
4. 남은 동시 실행 slot만큼 각 채팅 세션에 일반 Agent Run을 생성합니다.
5. 보고서가 아닌 Node도 사용자가 직접 읽을 수 있는 Markdown 중간보고서를 저장합니다. 확인한 사실·근거·계산·불확실성과 다음 Node가 알아야 할 내용을 담되, 서론·Executive Summary·맺음말 같은 최종 보고서용 문장 광택은 만들지 않습니다. 본문 끝의 `다음 Node 인계`에는 결론·근거·불확실성·참조를 간결하게 남깁니다. Run이 `create_report` 또는 `write_file`로 상세 문서를 만들고 채팅에는 짧은 완료 안내만 남긴 경우에도 상세 문서 원문을 Node의 대표 출력으로 보존합니다.
6. 보고서 Node만 선행 결과의 중복을 제거하고 결론·근거·반대 근거·한계·후속 조치를 갖춘 완성형 보고서를 작성합니다. 최종 산출물 형태는 Mission에서 정하며 Markdown을 기본으로 하고 HTML 추천값 또는 사용자가 직접 입력한 형태를 따릅니다.
7. 뒤 Node는 화면에서 사용자가 확인한 것과 동일한 선행 Node 대표 출력 전체를 입력 문맥으로 받습니다. 둘 이상의 Edge가 합류하면 직접 선행 Node의 대표 출력과 보조 산출물을 먼저 안정 정렬하고 이전 공통 조상 산출물을 별도 구분합니다. 합류 Node는 content hash·출처 기준으로 중복을 제거하되 충돌하는 결론과 각각의 provenance를 보존합니다.
8. 실행 가능한 Node와 실행 중인 Node가 모두 남지 않으면 Mission을 완료합니다.

Node 재실행은 같은 Node 채팅 세션을 계속 사용하되 새 Run을 만듭니다. 사용자는 종료된 Mission의 MISSION Node에서 전체 Workflow를 처음부터 다시 실행할 수 있으며, 이때 모든 Node의 현재 실행을 이력으로 보존하고 기존 산출물은 검토 필요 상태로 전환한 뒤 시작 Node부터 새 Run을 만듭니다. Mission을 다른 Project로 이동하거나 삭제할 때는 Node별 채팅 세션도 함께 이동하거나 삭제합니다.

진행 중, 일시 정지 또는 사용자 확인 대기 Mission에는 추가 지침과 새 Project 자료를 제출할 수 있습니다. 이 변경은 이미 만들어진 현재 Run의 입력을 바꾸지 않고, 제출 이후 새로 시작하는 Node Run의 프롬프트와 자료 snapshot부터 적용합니다. 별도 LLM 재계획이나 Node 추가·삭제는 수행하지 않습니다.

종료된 Mission은 처음 연결한 Project 파일의 고정 version과 현재 version을 비교할 수 있습니다. 변경된 자료가 있고 삭제된 자료가 없을 때만 갱신 실행을 허용하며, 기존 Node Run과 산출물을 이력으로 보존한 뒤 갱신된 자료 snapshot으로 시작 Node부터 다시 실행합니다. 현재 모든 명시 입력 자료가 각 Node 문맥에 들어가므로 변경 자료가 하나라도 있으면 활성 Workflow 전체를 영향 Node로 표시합니다.

## 4. 출력과 인용

중간 Node 출력은 Agent가 작성한 Markdown 중간보고서를 그대로 보존하고 렌더링합니다. `create_report` 또는 `write_file`로 생성한 상세 원문과 짧은 채팅 완료 안내가 함께 있으면 상세 원문을 화면과 Node 간 인계에 사용하는 canonical 출력으로 삼습니다. 최종 보고서 Node는 Mission에서 선택한 형식의 원문과 파일 경로를 보존하며, 별도의 중복 원문 영역은 만들지 않습니다.

각 Node의 작업 프롬프트는 실행 전 Workflow 편집 상태에서 사용자가 확인하고 수정할 수 있습니다. 최종 산출물 형태는 마지막 Node의 속성이 아니라 Mission 실행 설정으로 저장하며, MISSION 상세 패널에서 추천값을 고르거나 직접 입력합니다. HTML을 포함한 입력은 `.html`로 저장하고 그 외 직접 입력한 형태는 작성 지시에 반영하되 원문을 `.md`로 보존합니다. 중간 Node는 형식 선택과 관계없이 사용자가 읽고 다음 Node에도 전달할 수 있는 Markdown 중간보고서를 유지합니다.

사용자가 선택한 `답변 분량`과 `출력 토큰`은 보고서 Node의 최종 산출물에 적용합니다. 중간 Node는 유형에 따라 `1,200~3,500` token 범위의 내부 상한과 `짧게` 또는 `보통` 답변 분량을 사용하되, 사용자가 이보다 작은 출력 목표를 선택하면 더 작은 값을 따릅니다. `채팅` 출력 방식에서는 token 목표를 강제하지 않지만 같은 중간보고서 겸 압축 인계물 프롬프트를 유지합니다.

`[Claim:UUID]`, Claim Ledger, Evidence 객체, Open Issue, Quality Gate 같은 내부 표식은 생성하지 않습니다. 출처 표기가 필요한 작업은 Node 프롬프트에서 일반 Markdown 링크나 각주를 요구합니다.

MISSION 출처·인용 검사는 각 Node Run이 이미 저장한 웹 검색·본문 조회 source와 citation metadata, 명시적으로 연결한 Project 자료를 합쳐 보여 줍니다. 수치·비율·연도가 있으나 같은 문장에 명시적 인용 표식이나 URL이 없는 보고서 문장은 `인용 확인 필요` 후보로만 표시하며, 자동으로 사실 오류나 미지원 Claim으로 단정하지 않습니다. 보고서 비교는 보고서 Node의 최근 두 Run 원문에 대한 line diff이며 별도 LLM 호출을 사용하지 않습니다.

## 5. 비용 원칙

기본 비용 단위는 `실행된 Node 수 × Node당 Agent Run 비용`입니다. 사용자가 Workflow 재생성을 요청한 경우에만 AI 설계 호출 비용이 추가됩니다. 다음 반복 LLM 호출은 없습니다.

- 실행 중 Workflow 재계획
- Claim·Evidence 추출
- Quality Gate 판정
- 완료 계약 또는 예외 승인 판정

비용 화면은 실제 Node Run 사용량만 집계합니다.

## 6. 화면 계약

Mission 화면은 두 탭만 제공합니다.

- Workflow: Canvas, Node·Edge 편집, Node 상세, 실제 프롬프트와 렌더링된 출력
- 실행 기록: Node 대기·시작·완료·실패 등 실행 이벤트

실행 중 추가 지침·자료 입력은 Workflow 화면 안의 접이식 영역에 두고, 출처·인용 검사와 자료 변경 확인·보고서 차이는 MISSION 상세 패널에 둡니다. 별도 세 번째 탭을 만들지 않습니다.

활성 Mission의 상태 갱신은 500ms 반복 조회가 아니라 sequence 기반 SSE를 사용합니다. 브라우저는 마지막 event sequence 이후를 재연결하고 최근 실행 기록을 최대 1,000개로 제한합니다. 연속 event가 들어오면 상세 snapshot 조회를 100ms 단위로 합쳐 처리하며, 탭이 다시 보일 때 즉시 한 번 동기화합니다.

Node 상세 영역의 세로 경계는 포인터 드래그와 키보드 화살표로 폭을 조절할 수 있으며 마지막 폭을 기억합니다. Canvas의 빈 영역은 드래그해 이동할 수 있습니다.

빈 수동 Workflow는 실행할 수 없습니다. Node를 하나 이상 추가하고 편집 Draft를 활성화한 뒤에만 시작 action을 사용할 수 있으며, Frontend와 Backend가 같은 조건을 강제합니다.

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

개발 초기 단계이므로 기존 Mission 데이터는 호환 변환하지 않습니다. migration `0055`는 기존 Mission과 Mission 전용 채팅 세션을 삭제하고 Workflow Node에 `conversation_id`를 추가합니다. 새 Mission은 빈 수동 Workflow에서 시작하며 필요할 때만 AI 재생성을 사용합니다.

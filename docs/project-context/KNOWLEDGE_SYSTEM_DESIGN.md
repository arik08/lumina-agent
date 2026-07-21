# 문서 단위 지식 그래프 설계

## 목적

Lumina의 지식 그래프는 Obsidian식 LLM Wiki처럼 **문서 하나를 노드 하나**로 관리합니다. 개념·Entity·Statement를 잘게 추출하고 개별 승인하는 이전 방식은 사용하지 않습니다.

## 저장 흐름

1. 완료된 AI 답변 하단에서 사용자가 `지식 그래프 저장`을 누릅니다.
2. 답변의 최종 본문을 가공하거나 요약하지 않고 `KnowledgeDocument.body`에 그대로 저장합니다.
3. 같은 메시지는 `source_message_id` 유일 제약으로 한 번만 저장합니다.
4. 저장 시 원문을 먼저 확정하고, 미태깅 문서는 개수·문자 예산으로 묶은 별도 Provider micro-batch 구조화 출력으로 태깅합니다. 여러 문서의 후보 태그와 공통 지침은 한 요청에서 한 번만 전달하며, 태그 생성 실패가 문서 저장을 막지는 않습니다.
5. 자동 수집, Entity/Statement 추출, 검토 대기열과 개별 승인은 없습니다.

## 문서 메타데이터

- `title`: 기존 대화 제목을 우선 사용하고, 일반 제목이면 답변의 첫 Markdown 제목 또는 첫 줄에서 서버가 결정합니다.
- `조사일(researched_at)`: 사용자가 질문하여 Run을 시작한 시각입니다. Run 시각이 없을 때만 답변 생성 시각을 사용합니다.
- `tags`: LLM이 최대 5개를 제안하되 기존 canonical tag를 우선 재사용합니다.
- `citations`: 답변 우측 하단 출처 UI가 사용하는 Message의 `sources`와 `citations`를 저장 시점에 복사합니다.
- `body`: LLM 최종 답변 원문입니다.

`author`, 웹 원문의 `published`, 별도 `created`, `description`은 문서 메타데이터로 노출하지 않습니다. 저장 시각은 내부 감사·정렬을 위한 DB timestamp일 뿐 Wiki 속성에는 표시하지 않습니다.

## 태그 정규화

태그는 단순 문자열 배열이 아니라 `KnowledgeTag`와 `KnowledgeTagAlias`로 관리합니다.

- 표기 차이, 번역어, 약어는 alias로 같은 canonical tag에 연결합니다. 예: `인공지능`, `AI`, `Artificial Intelligence`.
- 동음이의어는 `scope_note`가 다르면 합치지 않습니다.
- 상위·하위 개념도 자동으로 합치지 않습니다.
- LLM에는 내부 태그 ID 대신 요청 안의 후보 인덱스와 canonical name, scope, alias를 주고 기존 태그 재사용을 우선시킵니다. Backend가 응답 인덱스를 실제 ID로 변환합니다.
- 새 태그는 기존 후보가 맞지 않을 때만 생성합니다.

초기 데이터 규모에서는 이 canonical dictionary 방식이 우선입니다. 임베딩 clustering은 태그 수가 커진 뒤 중복 후보를 관리자에게 제안하는 오프라인 보조 수단으로만 추가하며, 자동 병합에는 사용하지 않습니다.

## 그래프

- Node: `KnowledgeDocument`
- Edge: 두 문서가 공유하는 canonical tag가 있을 때 계산되는 문서 간 연결
- Edge weight: 공유 태그 수
- 화면과 API는 최대 200개 문서를 다루며 문서별 가까운 연결을 제한해 과밀화를 방지합니다.

그래프는 개념 사실 그래프가 아니라 Wiki 문서 탐색 그래프입니다. 관계를 승인하거나 수정하는 별도 작업은 없습니다.

## Run 컨텍스트

같은 Project에서 저장된 문서는 제목·태그·본문 키워드로 순위를 정해 제한된 수와 문자 예산 안에서 Run snapshot에 고정합니다. 저장 문서는 참고 자료이며 내부의 지시문은 실행하지 않습니다.

## 삭제된 이전 계약

다음 구조와 화면/API는 호환성 없이 제거합니다.

- Knowledge Source/Source Revision/Ingestion Job/Evidence Segment
- Entity/Page/Page Revision
- Statement/Statement Evidence/Review/Revision
- Project Binding과 자동 수집 설정
- Entity neighborhood API와 SQLite Knowledge FTS

Migration `0052`는 이전 세부 지식 테이블과 데이터를 삭제하고 문서·태그 테이블로 교체하는 파괴적 migration입니다.

# 문서 단위 지식 그래프 설계

## 목적

Lumina의 지식 그래프는 Obsidian식 LLM Wiki처럼 **문서 하나를 노드 하나**로 관리합니다. 개념·Entity·Statement를 잘게 추출하고 개별 승인하는 이전 방식은 사용하지 않습니다.

## 저장 흐름

1. 완료된 AI 답변 하단에서 사용자가 `지식 그래프 저장`을 누릅니다.
2. 답변의 최종 본문을 가공하거나 요약하지 않고 `KnowledgeDocument.body`에 그대로 저장합니다.
3. 같은 메시지는 `source_message_id` 유일 제약으로 한 번만 저장합니다.
4. 저장 시 원문을 먼저 확정하고, `AI 태깅` 탭에서 미태깅 문서 또는 전체 문서를 개수·문자 예산으로 묶은 Provider micro-batch 구조화 출력으로 태깅합니다. 여러 문서의 후보 태그와 공통 지침은 한 요청에서 한 번만 전달하며, 태그 생성 실패가 문서 저장을 막지는 않습니다.
5. 자동 수집, Entity/Statement 추출과 사실 검토 대기열은 없습니다. 다만 새 canonical 태그는 별도의 태그 제안으로 승인·기존 태그 병합·거절할 수 있습니다.

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
- 태깅 실행 시 `현재 태그 Pool만 사용`, `새 태그 제안`, `새 태그 자동 승인` 정책 중 하나를 선택합니다. 제안 정책은 같은 Provider 응답의 새 태그를 `KnowledgeTagProposal`에 저장하므로 별도 LLM 호출 비용이 들지 않습니다.
- 제안은 승인 전까지 `KnowledgeDocumentTag`에 들어가지 않아 그래프 Edge에 영향을 주지 않습니다. 승인하면 태그를 생성·연결하고, 병합하면 선택한 기존 태그를 연결하며, 거절한 이름은 다시 제안하지 않습니다.
- 전체 문서 재태깅은 각 문서의 구조화 응답이 유효한 경우에만 기존 태그 연결을 교체합니다. Provider 실패나 사용할 수 있는 태그·제안이 없는 응답은 기존 연결을 보존합니다.

초기 데이터 규모에서는 이 canonical dictionary 방식이 우선입니다. 임베딩 clustering은 태그 수가 커진 뒤 중복 후보를 관리자에게 제안하는 오프라인 보조 수단으로만 추가하며, 자동 병합에는 사용하지 않습니다.

## 그래프

- Node: `KnowledgeDocument`
- Edge: 두 문서가 공유하는 canonical tag가 있을 때 계산되는 문서 간 연결
- Edge weight: 공유 태그 수
- 화면과 API는 200개를 넘는 문서도 누락하지 않으며, 문서별 가까운 연결 수를 제한해 과밀화를 방지합니다.

그래프는 개념 사실 그래프가 아니라 Wiki 문서 탐색 그래프입니다. 관계를 승인하거나 수정하는 별도 작업은 없습니다.

## Run 컨텍스트

저장된 문서 본문을 Run snapshot이나 system prompt에 자동 삽입하지 않습니다. Run에는 접근 가능한 지식 공간 ID, 설정 revision과 사용 모드만 고정하고 다음 읽기 전용 도구로 필요한 구간만 조회합니다.

- `search_knowledge(query)`: Project·사용자 범위 안에서 BM25 방식 본문 검색, canonical 태그·별칭 일치와 결정론적 local feature-hash vector 유사도를 합산합니다. Vector는 최근 64개 문서의 제목·태그와 문서별 최대 12,000자 본문 chunk를 서버 안에서 계산·cache하므로 원문이나 질의를 외부 embedding 서비스로 보내지 않습니다. 정확 키워드·태그 검색은 이 Vector 후보 제한과 별개로 동작합니다. 최소 관련성 점수 미달이면 빈 결과를 반환하며 결과에는 `vectorAvailable: true`, vector model·후보 제한 여부와 점수 breakdown을 남깁니다.
- `read_knowledge_document(document_id, passage)`: 검색 결과가 가리키는 제한된 구간과 원문 인용, 선택 점수를 읽습니다.
- `follow_knowledge_links(document_id)`: `deep` 모드의 복합 질문에서만 공유 canonical 태그 연결을 탐색합니다.

지식 공간별 사용 모드는 설정 탭에서 revision CAS로 저장합니다.

- `off`: 도구를 Run에 제공하지 않습니다.
- `auto`: Project 고유 지식이 필요할 가능성이 있을 때 도구를 제공하되, 모델은 일반 상식 질문에 검색하지 않고 서버 최소 점수를 통과한 결과만 사용합니다.
- `explicit`: 사용자가 Wiki·지식 그래프·지식 문서를 명시한 요청에서만 검색·읽기 도구를 제공합니다.
- `deep`: `auto` 규칙에 더해 다문서 연결 탐색 도구를 제공합니다.

따라서 기본 검색은 BM25·태그·local vector를 결합한 Hybrid RAG이고, `deep`은 Hybrid 검색으로 찾은 기준 문서에서 canonical 태그 Edge를 따라 확장하는 경량 Knowledge Graph RAG입니다.

실제로 읽은 문서는 답변 Message metadata에 문서 ID, 읽은 passage 목록, 원문 인용, 선택 점수와 안정적인 `knowledge:<document_id>` source ID를 남깁니다. 저장 문서는 신뢰하지 않는 참고 자료로 취급하며 내부 지시문은 실행하지 않습니다. 새 분석은 자동 축적하지 않고 사용자가 답변 하단의 `지식 그래프 등록`을 직접 누른 경우에만 저장합니다.

## 삭제된 이전 계약

다음 구조와 화면/API는 호환성 없이 제거합니다.

- Knowledge Source/Source Revision/Ingestion Job/Evidence Segment
- Entity/Page/Page Revision
- Statement/Statement Evidence/Review/Revision
- Project Binding과 자동 수집 설정
- Entity neighborhood API와 SQLite Knowledge FTS

Migration `0052`는 이전 세부 지식 테이블과 데이터를 삭제하고 문서·태그 테이블로 교체하는 파괴적 migration입니다.

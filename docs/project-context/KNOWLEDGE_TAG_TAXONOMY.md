# 지식 그래프 태그 분류체계와 승인 운영 계약

상태: **Target**
작성일: 2026-07-19

이 문서는 지식 그래프의 사용자 정의 태그, 계층형 분류, 자동 태깅, 신규 태그 승인 흐름을 구체화합니다. 문서가 존재한다는 이유만으로 구현 완료로 간주하지 않으며 현재 source, migration, API, Frontend와 test를 함께 확인해야 합니다.

## 1. 결정 요약

Lumina의 지식 태그는 **관리형 분류체계(controlled taxonomy)와 사용자 제안형 태그(folksonomy)의 혼합 모델**을 사용합니다.

- 사용자는 승인된 기존 태그를 검색하고 즉시 문서에 적용할 수 있습니다.
- 일치하는 태그가 없으면 새 태그를 직접 제안할 수 있습니다.
- LLM도 기존 태그 ID를 우선 선택하고, 맞는 항목이 없을 때만 새 태그 제안을 만듭니다.
- 조직 공유 지식 그래프의 신규 태그는 기본적으로 승인 전까지 `pending` 제안이며 검색·그래프의 canonical 관계에 반영하지 않습니다.
- 개인 비공개 지식 그래프는 정책에 따라 신규 태그를 즉시 활성화할 수 있습니다.
- 태그 이름, 유형, 짧은 정의, 별칭, 상위 개념, 상태와 사용 문서 수를 사람이 편집할 수 있습니다.
- 승인된 태그는 삭제보다 `deprecated` 처리하고 대체 태그를 지정합니다.

핵심은 신규 태그 생성을 막는 것이 아니라, **문서 저장은 즉시 끝내고 용어 사전의 품질만 비동기 검토**하는 것입니다.

## 2. 경쟁사 분석 사용 사례의 올바른 모델

다음 구조는 사용자가 떠올리기 쉽지만 taxonomy의 의미상 사용하지 않습니다.

```text
#경쟁사 분석
├─ #포스코
├─ #아르셀로미탈
└─ #뉴코어
```

`경쟁사 분석`은 연구 목적이고 `포스코`는 대상 기업이므로 더 넓은 개념과 더 좁은 개념의 관계가 아닙니다. 이를 하나의 트리로 만들면 나중에 `공급망 분석`, `기술 분석`, `M&A 분석` 아래에도 같은 회사를 중복 배치해야 하고 기업별 문서 집계도 불안정해집니다.

초기 권장 분류 축은 다음과 같습니다.

```text
연구 목적 (purpose)
└─ 경쟁사 분석

대상 기업 (company)
├─ 포스코홀딩스
│  └─ 포스코
├─ 아르셀로미탈
└─ 뉴코어

산업 (industry)
└─ 철강

주제 (topic)
├─ 원가 경쟁력
├─ 생산능력
├─ 탈탄소
└─ 투자 전략

지역 (region)
├─ 한국
├─ 유럽
└─ 북미
```

예를 들어 포스코의 저탄소 제철 투자를 분석한 문서는 다음처럼 여러 축을 함께 가집니다.

```json
{
  "purpose": ["경쟁사 분석"],
  "company": ["포스코"],
  "industry": ["철강"],
  "topic": ["탈탄소", "투자 전략"]
}
```

`경쟁사 분석`을 선택했을 때 `company` 태그를 우선 노출하고, 포스코·아르셀로미탈·뉴코어 같은 최근 또는 자주 사용한 기업을 위로 올리는 **추천 규칙**을 둡니다. 이 규칙이 사용자가 원하는 "정의된 목록에서 고를 확률을 높이는" 역할을 하며, 잘못된 부모·자식 관계를 만들지 않습니다.

## 3. 태그 개념과 불변 조건

### 3.1 Canonical 태그

Canonical 태그는 다음 필드를 가집니다.

| 필드 | 의미 |
|---|---|
| `id` | 이름 변경과 무관한 불변 ID |
| `namespace` | `purpose`, `company`, `industry`, `topic`, `region` 등의 분류 축 |
| `canonicalName` | 화면에 표시하고 저장하는 대표 이름 |
| `definition` | 사람이 입력하는 짧은 업무 정의 |
| `scopeNote` | 동음이의어 구분에만 사용하는 40자 이내 설명 |
| `aliases` | 영문명, 약어, 과거 사명, 띄어쓰기 변형 등 |
| `status` | `active` 또는 `deprecated` |
| `broaderTagId` | 같은 namespace 안의 주 상위 개념. 없으면 최상위 |
| `replacementTagId` | deprecated 태그의 권장 대체 태그 |
| `stewardUserId` | 용어 품질 책임자. 초기에는 선택 사항 |
| `revision` | 동시 편집과 변경 이력용 revision |

- `#`은 화면 표현일 뿐 이름에 저장하지 않습니다.
- 같은 지식 공간과 namespace 안에서는 정규화 이름이 유일해야 합니다.
- 별칭은 canonical 태그를 찾기 위한 표현이며 별도 태그처럼 문서에 연결하지 않습니다.
- 부모와 자식은 원칙적으로 같은 namespace에만 둡니다.
- 자식 태그를 적용할 때 부모 태그를 문서에 중복 저장하지 않습니다. 부모 필터는 하위 태그를 확장해 조회합니다.
- 초기 UI는 한 개의 주 상위 개념만 편집하게 하되, 저장 구조는 향후 `broader`·`related` 다중 관계를 지원할 수 있어야 합니다.

### 3.2 태그 제안

승인 전 신규 태그는 `KnowledgeTag`가 아니라 별도 `KnowledgeTagProposal`입니다.

| 필드 | 의미 |
|---|---|
| `proposedName` | 제안 이름 |
| `namespace` | 제안된 분류 축 |
| `definition` | 사용자 입력 또는 검토용 짧은 정의 |
| `aliases` | 선택적 별칭 |
| `broaderTagId` | 선택적 상위 태그 |
| `sourceType` | `user`, `llm`, `import` |
| `requestedByUserId` | 직접 제안 사용자. LLM 제안은 문서 소유자 |
| `status` | `pending`, `approved`, `merged`, `rejected` |
| `resolutionTagId` | 승인 또는 기존 태그 병합 결과 |
| `reviewedByUserId`, `reviewedAt`, `reviewNote` | 검토 감사 정보 |

하나의 제안은 여러 문서와 연결할 수 있습니다. 승인 시 canonical 태그를 만들거나 기존 태그에 병합하고, 연결된 문서에 결과 태그를 원자적으로 적용합니다. 거절된 제안은 canonical 그래프에 영향을 주지 않습니다.

## 4. 지식 문서 태깅 흐름

### 4.1 사람이 직접 태깅할 때

1. 문서의 태그 편집을 누르면 namespace별 검색 가능한 picker를 엽니다.
2. 입력어와 canonical 이름·별칭이 일치하는 승인 태그를 먼저 보여줍니다.
3. 연구 목적 등 이미 선택된 태그의 추천 규칙, 최근 사용, 문서 내용 관련도를 이용해 후보 순서를 조정합니다.
4. 사용자는 기존 태그를 즉시 적용하거나 `새 태그 제안`을 선택합니다.
5. 신규 제안에는 최소한 `유형`, `이름`, `짧은 정의`를 입력합니다. 상위 태그와 별칭은 선택 사항입니다.
6. 승인 대기 제안은 문서에 점선 chip으로 보일 수 있지만 canonical 태그 수, 검색 facet과 그래프 연결에는 포함하지 않습니다.

### 4.2 LLM이 자동 태깅할 때

현재처럼 전체 태그를 이름순으로 잘라 prompt에 넣지 않습니다. Backend가 먼저 후보를 좁힙니다.

1. canonical 이름·별칭의 정확/부분 일치
2. 태그 이름·정의와 문서의 lexical 또는 semantic 관련도
3. 이미 선택된 namespace와 추천 규칙
4. 같은 지식 공간의 최근 사용과 문서 사용 수
5. deprecated와 pending 태그 제외

LLM 출력은 기존 태그 ID와 최소 신규 제안만 포함합니다.

```json
{
  "tagIds": ["approved-tag-id"],
  "newTags": [
    {
      "namespace": "company",
      "canonicalName": "새 기업명",
      "broaderTagId": null
    }
  ]
}
```

- 후보가 맞으면 새 문자열을 다시 쓰지 않고 반드시 기존 ID를 반환합니다.
- 새 태그 제안에 긴 요약이나 근거 문장을 생성하지 않습니다.
- 검토 화면의 근거는 별도 LLM 설명보다 원문 제목과 짧은 주변 문맥으로 제공합니다.
- 응답 생성 시 이미 작은 typed metadata를 받을 수 있으면 이를 우선 사용하고, 별도 태깅 호출은 수동 등록·가져오기·metadata 누락 문서의 fallback으로 제한합니다.
- 자동 태깅 실패가 문서 저장 실패가 되어서는 안 됩니다. 문서는 태그 없음 상태로 저장하고 재시도할 수 있습니다.

## 5. 추천 규칙

추천 규칙은 taxonomy 계층과 분리된 `TagRecommendationRule`로 관리합니다.

```text
조건: purpose = 경쟁사 분석
효과: company namespace 가중치 상향
보조 후보: 포스코, 아르셀로미탈, 뉴코어
```

초기 버전에서는 복잡한 점수 편집 UI를 만들지 않고 다음만 지원합니다.

- 기준 태그 한 개
- 우선 추천할 namespace 한 개 이상
- 선택적 고정 추천 태그
- 활성/비활성

고정 추천은 선택을 강제하지 않습니다. 본문에 등장하지 않는 기업을 자동 적용해서는 안 됩니다. 사용 빈도는 동점 정렬에만 약하게 반영해 인기 태그가 모든 문서를 잠식하지 않게 합니다.

## 6. 승인 정책과 권한

지식 공간마다 다음 정책 중 하나를 가집니다.

| 정책 | 기존 태그 사용 | 신규 사용자 태그 | 적합한 범위 |
|---|---|---|---|
| `open` | 즉시 | 즉시 active | 개인 비공개 연구 |
| `reviewed` | 즉시 | proposal 후 승인 | 팀·조직 공유, 기본값 |
| `closed` | 즉시 | 제안만 가능 | 엄격한 공식 분류체계 |

- 개인 비공개 공간의 기본값은 `open`, 조직 공유 공간의 기본값은 `reviewed`입니다.
- 지식 공간 owner는 승인할 수 있고 organization admin은 fallback 승인자입니다.
- 별도 steward가 지정되면 해당 namespace의 1차 승인자로 사용합니다.
- 자기 제안 승인은 `open`에서만 자동 허용합니다. `reviewed`에서는 제안자와 승인자를 분리하는 것을 기본으로 합니다.
- 승인 요청은 행동 가치가 있으므로 알림에 남기되, 단순 태그 적용 성공은 알림을 만들지 않습니다.
- 모든 생성, 이름 변경, 이동, 병합, 비활성화와 승인 결정은 audit event로 기록합니다.

## 7. 화면 계약

현재 `검토` 탭을 **태그 관리** 중심 화면으로 확장합니다.

### 7.1 상단 요약

- `승인 대기 N개`
- `중복 의심 N개`
- `정의 없음 N개`
- 대기가 없을 때만 현재의 조용한 성공 상태를 표시합니다.

### 7.2 태그 사전

- 왼쪽: namespace filter, 검색, 접고 펼칠 수 있는 얕은 tree/list
- 가운데: canonical 태그 행. 이름, 정의, 사용 문서 수, 상태를 표시
- 오른쪽 또는 같은 행 확장: 이름, 정의, 별칭, 상위 태그, 대체 태그를 직접 편집
- `새 태그`는 현재 namespace 문맥을 유지한 인라인 생성 행
- 삭제 대신 같은 버튼의 2단계 확인으로 `사용 중단` 처리

독립 card를 반복하지 않고 divider로 연결된 업무 목록을 사용합니다. 일반 사용자는 tree 전체를 펼치지 않아도 검색과 최근 사용으로 태그를 찾을 수 있어야 합니다.

### 7.3 승인 대기 행

각 행에는 다음을 함께 표시합니다.

- 제안 이름, namespace, 상위 태그
- 제안자 또는 `AI 제안`
- 연결 대기 문서 수와 대표 문서 제목
- 이름·별칭·정의를 편집할 수 있는 인라인 form
- `승인`, `기존 태그에 병합`, `거절`
- 중복 가능성이 높은 기존 태그 1~3개

승인은 proposal을 그대로 복사하는 동작이 아니라 검토자가 canonical 값을 확정하는 동작입니다.

## 8. 검색과 그래프 의미

- 문서 간 직접 edge는 승인된 동일 canonical 태그 공유를 기본으로 유지합니다.
- 부모 태그는 문서에 중복 부착하지 않으며 탐색·filter에서 하위 태그를 포함하는 집계에 사용합니다.
- `산업=철강`처럼 너무 넓은 태그 하나만 공유한다고 모든 문서를 강한 edge로 연결하지 않습니다. 구체적인 leaf 태그와 여러 축의 동시 일치에 더 높은 가중치를 줍니다.
- pending proposal은 검색 facet, 집계, 추천 학습과 그래프 edge에서 제외합니다.
- 태그 병합 후 과거 문서 연결은 새 canonical ID로 이관하고 별칭과 audit 이력은 보존합니다.
- deprecated 태그는 새 적용 후보에서 제외하지만 과거 문서와 대체 태그 정보는 유지합니다.

## 9. 현재 구현과 차이

현재 구현에는 다음 기반이 이미 있습니다.

- `knowledge_tags.namespace`, `canonical_name`, `scope_note`, `status`
- `knowledge_tag_aliases`
- 문서와 태그의 다대다 연결
- 기존 태그 후보 재사용과 LLM 신규 태그 제안
- 공통 canonical 태그 기반 문서 그래프

그러나 다음은 아직 구현되지 않았습니다.

- 사람이 태그·정의·별칭을 생성·수정하는 API와 UI
- 실제 typed namespace 보존. 현재 신규 태그는 `topic`으로 평탄화됨
- 부모·자식 또는 related 관계
- proposal과 승인·병합·거절 상태
- pending 제안을 canonical 그래프에서 격리하는 구조
- 추천 규칙과 관련도 기반 후보 검색
- deprecated·replacement 운영과 taxonomy 변경 이력

따라서 현재 화면의 `승인 대기 지식이 없습니다`는 실제 승인 workflow가 구현되었다는 뜻으로 사용하면 안 됩니다.

## 10. 단계별 구현 범위

### 1단계: 운영 가능한 태그 사전

- typed namespace
- 사용자 태그 CRUD와 짧은 정의·별칭
- 같은 namespace 안의 한 단계 이상 계층
- `open | reviewed | closed` 정책
- proposal 승인·병합·거절
- 문서별 수동 태그 편집
- audit와 Backend 권한 검사

### 2단계: 자동 태깅 품질과 비용

- 후보 검색과 추천 규칙
- LLM typed output
- 답변 metadata 우선, 별도 태깅 호출 fallback
- pending 문서 재처리와 batch review
- duplicate/alias 후보 감지

### 3단계: 확장 운영

- 다중 broader·related 관계
- CSV/SKOS 가져오기·내보내기
- namespace별 steward
- taxonomy revision 비교와 rollback
- 추천 품질·승인 부하 지표

## 11. 완료 기준

- 사용자가 승인된 기존 태그를 검색해 문서에 추가·제거할 수 있습니다.
- 사용자가 태그의 이름, 유형, 정의, 별칭과 상위 태그를 편집할 수 있습니다.
- 조직 공유 공간에서 신규 사용자·LLM 태그가 자동 active 되지 않습니다.
- 승인, 기존 태그 병합, 거절이 문서 연결까지 원자적으로 반영됩니다.
- `경쟁사 분석` 선택 시 company 후보가 우선되지만 회사가 그 하위 개념으로 저장되지 않습니다.
- pending·deprecated 태그가 신규 그래프 edge와 기본 picker 후보에 들어가지 않습니다.
- 같은 이름의 동음이의어를 namespace와 scope note로 구분할 수 있습니다.
- 태그 이동·병합 후에도 과거 문서와 audit 이력이 유실되지 않습니다.
- 실제 격리 브라우저에서 태그 검색, 생성, 승인, 병합, 반응형 배치와 console 오류를 검증합니다.

## 12. 참고한 외부 사례

- [Microsoft SharePoint managed metadata planning](https://learn.microsoft.com/en-us/sharepoint/governance/managed-metadata-planning): 중앙 관리 taxonomy와 사용자가 만드는 enterprise keyword를 함께 운영하고, local/global term set과 생성 정책을 분리합니다.
- [Microsoft SharePoint information architecture guidance](https://learn.microsoft.com/en-us/sharepoint/dev/solution-guidance/portal-information-architecture): taxonomy 관리 주체와 입력 절차를 두고, 지나치게 깊거나 큰 hierarchy를 피하며 삭제보다 deprecate를 권장합니다.
- [Microsoft Purview glossary term management](https://learn.microsoft.com/en-au/azure/purview/how-to-create-manage-glossary-term): Draft·Approved·Expired·Alert 상태, parent, synonym, related term과 승인 workflow를 제공합니다.
- [Atlassian Confluence labels](https://support.atlassian.com/confluence-cloud/docs/use-labels-to-organize-your-content/): 입력 중 기존 label을 제안하고 없으면 새 label을 만드는 저마찰 흐름의 사례입니다. Lumina는 이 흐름에 typed namespace와 조직 승인 계층을 추가합니다.
- [W3C SKOS Primer](https://www.w3.org/TR/skos-primer/): preferred label, alternative label, broader·narrower와 related 관계를 구분합니다. Lumina의 canonical 이름, 별칭, 계층과 비계층 관계의 기준으로 사용합니다.

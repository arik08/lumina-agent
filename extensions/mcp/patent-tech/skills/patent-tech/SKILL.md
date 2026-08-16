---
name: patent-tech
description: KIPRISPlus와 EPO OPS의 특허 서지·패밀리, OpenAlex·Crossref·Semantic Scholar의 논문·연구 메타데이터를 공식 구조화 API로 조회하는 MCP 라우팅입니다.
metadata:
  lumina-source: skill-mcp:patent-tech
---

# 특허·기술·논문 MCP

특허와 연구기술 동향에는 `patent-tech` MCP를 사용합니다.

- 한국 특허·실용신안 키워드 검색과 출원번호별 서지는 `source="kipris"`를 사용합니다.
- 유럽·국제 특허 서지와 패밀리는 `source="epo_ops"`를 사용합니다. 검색어는 EPO OPS CQL이며, 패밀리는 `record_type="family"`입니다.
- 연구 주제·기관·저자·인용 관계는 `source="openalex"`, DOI 등록 메타데이터 확인은 `source="crossref"`, 초록·인용·참고문헌 탐색은 `source="semantic_scholar"`를 사용합니다.
- OpenAlex는 2026년부터 무료 API 키가 필요하므로 `OPENALEX_API_KEY`가 없으면 검색하지 않습니다. Crossref는 키가 없지만 연락용 `CROSSREF_MAILTO` 설정을 권장합니다.
- 동일 기술은 특허와 논문을 분리 검색한 뒤 공개일·출원일·우선일을 구분합니다. 검색 건수만으로 기술우위를 단정하지 않습니다.
- 먼저 `search_catalog` 또는 `search_records`로 ID를 확보하고 `get_record`로 상세 메타데이터를 확인합니다.
- Semantic Scholar는 공식상 키 없는 호출도 허용하지만 공유·기업망 출구 IP에서는 429가 반복되므로 이 환경에서는 `SEMANTIC_SCHOLAR_API_KEY`를 운영 필수로 봅니다.
- PDF·도면·전문을 내려받거나 OCR하지 않습니다. 이 MCP는 구조화된 서지·초록·패밀리 메타데이터만 반환합니다.
- WIPO PATENTSCOPE 웹서비스는 일반 공개 API가 아니라 구독·사용조건·호출제한이 있는 별도 상품이므로 이 MCP에 포함하지 않습니다. 국제 특허는 EPO OPS 패밀리로 대체합니다.
- USPTO ODP는 2026년 계정·키 정책 전환과 구형 Developer Hub 종료가 진행 중이므로 안정 계약이 확인되기 전에는 연결하지 않습니다.

## 트리거 경계

- 수소환원제철, CCUS, 희귀가스, 소재·공정 특허, 연구기관, 논문, DOI, 인용·패밀리 요청에 사용합니다.
- 기업 투자·공시는 `company-disclosure`, 법안·규제는 `legislation-regulation`으로 보냅니다.

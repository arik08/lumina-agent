---
name: legislation-regulation
description: Congress.gov, Federal Register, 유럽의회 Open Data, EUR-Lex CELLAR, UK Parliament Bills, legislation.gov.uk의 법안·입법절차·행정규정·법령을 공식 구조화 데이터로 조회하는 MCP 라우팅입니다.
metadata:
  lumina-source: skill-mcp:legislation-regulation
---

# 해외 법률·의회·규제 MCP

미국·EU·영국의 법안, 입법 진행, 행정규정과 확정 법령에는 `legislation-regulation` MCP를 사용합니다.

- 미국 법안·발의자·위원회·Action·텍스트 버전은 `source="congress"`를 사용합니다. `record_id`는 `119/hr/1` 형식이며, 세부 내역은 `record_type="actions"`, `committees`, `cosponsors`, `subjects`, `summaries`, `text` 중 하나를 사용합니다.
- 미국 행정명령·관세·제재·무역규정·예고는 `source="federal_register"`를 사용합니다.
- EU 입법절차와 단계별 이벤트는 `source="europarl"`을 우선합니다. `process_id`를 얻은 뒤 `record_type="events"`로 진행 이력을 확인합니다.
- CELEX 번호를 이미 알거나 EU 법령 원문·개정·식별자를 확인할 때만 `source="eurlex"`를 사용합니다. 제목 검색은 유럽의회 절차 또는 EUR-Lex 웹 검색으로 CELEX를 먼저 확보합니다.
- 영국 계류 법안·단계·공개 문서는 `source="uk_bills"`, 제·개정 완료 법령과 시행 구조는 `source="uk_legislation"`을 사용합니다.
- 한국 국회·입법예고는 기존 `national-assembly`, 한국 현행 법령·판례는 기존 `korean-law` MCP를 우선합니다. 중복 조회하지 않습니다.
- PDF를 내려받거나 OCR하지 않습니다. `get_record`의 JSON·JSON-LD·Atom·XML을 사용하고, 원문은 `get_document_link`의 공식 HTML 화면으로 안내합니다.
- 키 설정·접속 문제는 `get_source_health`로 확인합니다. Congress.gov만 별도 data.gov API 키가 필요합니다.

## 트리거 경계

- 법안, 의안 진행, 위원회, 표결, 행정명령, 규칙 예고, 관세·제재 규정, CBAM·ETS·세이프가드, 영국 Bills 요청에 사용합니다.
- 기업 공시는 `company-disclosure`, HS 무역 통계는 `trade-market`, 특허는 `patent-tech`로 보냅니다.

---
name: company-disclosure
description: OpenDART, SEC EDGAR, Companies House의 기업 식별·공시·XBRL 재무·주요 제출 내역을 조회하는 MCP 라우팅입니다. 한국·미국·영국 기업의 공식 공시, 경쟁사 재무, 사업보고서, 제출 이력, 법인번호를 찾을 때 사용합니다.
metadata:
  lumina-source: skill-mcp:company-disclosure
---

# 기업공시 MCP

기업·공시·재무 조회에는 `company-disclosure` MCP를 사용합니다.

- 한국 기업은 `source="opendart"`, 미국 상장사는 `source="sec"`, 영국 법인은 `source="companies_house"`를 사용합니다.
- 회사 코드가 없으면 `search_catalog`로 먼저 찾습니다. 회사명보다 종목코드·CIK·법인번호가 있으면 이를 우선합니다.
- 공시 목록은 `search_records`, 회사 개황이나 구조화 재무는 `get_record`를 사용합니다.
- OpenDART 전체 재무제표는 `record_type="financials"`와 사업연도, 보고서 코드, `CFS` 또는 `OFS`를 지정합니다.
- SEC는 회사 연락처·제출 이력에 `record_type="company"`, XBRL facts에 `record_type="companyfacts"`를 사용합니다.
- PDF 원문을 내려받거나 OCR하지 않습니다. 근거 원문이 필요하면 `get_document_link`의 공식 HTML 링크를 제공합니다.
- 인증 오류와 서비스 장애를 구분하려면 `get_source_health`를 사용합니다. 응답이나 보고서에 API 키를 적지 않습니다.
- 결과에는 공식 출처, 식별자, 조회시각, 기준시점, 개정·완전성 정보를 함께 제시합니다.

## 트리거 경계

- 기업공시·사업보고서·재무제표·XBRL·DART·EDGAR·Companies House 요청에 사용합니다.
- 거시경제 시계열은 `macro-finance`, 국가 간 무역은 `trade-market`, 특허는 `patent-tech`로 보냅니다.

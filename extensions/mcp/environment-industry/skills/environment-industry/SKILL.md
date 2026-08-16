---
name: environment-industry
description: Eurostat PRODCOM 산업생산, 미국 EPA ECHO 사업장 환경준수·집행, USDA ERS 농업경영 데이터를 공식 구조화 API로 조회하는 MCP 라우팅입니다. 기존 EIA·KOSIS와 함께 산업·원자재·환경 모니터링에 사용합니다.
metadata:
  lumina-source: skill-mcp:environment-industry
---

# 산업·원자재·환경 MCP

산업생산·농업경영·사업장 환경준수에는 `environment-industry` MCP를 사용합니다.

- EU 제품별 생산·판매·수출입은 `source="eurostat_prodcom"`을 사용합니다. `query_industry`에는 `reporter`, `product`, `time`을 모두 넣어 대용량 전체 조회를 방지합니다.
- 미국 철강·에너지 사업장의 CAA·CWA·RCRA·SDWA 준수, 검사·집행 요약은 `search_facilities`를 사용합니다.
- 미국 농가 재무·소득·부채·생산특화는 `source="usda_ers"`의 ARMS 데이터를 사용합니다. 먼저 `search_catalog`로 변수 ID를 확인한 뒤 연도와 report 또는 variable을 지정합니다.
- 미국 에너지 생산·소비·재고·가격은 새로 중복 구현하지 않고 기존 `eia` MCP를 사용합니다. 한국 산업·물가·생산은 기존 `kosis`, 한국은행 시계열은 기존 `ecos`를 사용합니다.
- IEA 핵심 통계는 상당수가 구독형이고 공개 `api.iea.org` 경로는 공식 공개 API 계약이 아닙니다. IRENA·JODI·USGS·GEM은 주로 대용량 CSV/XLSX/PDF 또는 개별 다운로드라 이 MCP에서 제외합니다.
- EEA·ECHA는 범용 안정 API가 없고 데이터셋별 다운로드·포털 의존성이 커서 자동 라우팅하지 않습니다.
- 구조화 JSON/JSON-stat만 반환하며 PDF·엑셀·OCR 추출을 하지 않습니다.

## 트리거 경계

- 철강·자동차·기계 생산량, PRODCOM, 농가 재무, 미국 사업장 환경준수·위반·검사 요청에 사용합니다.
- HS 수출입은 `trade-market`, 거시 선행지표는 `macro-finance`, 법령 원문은 `legislation-regulation`으로 보냅니다.

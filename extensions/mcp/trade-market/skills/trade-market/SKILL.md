---
name: trade-market
description: 한국 관세청, U.S. Census, WTO, Eurostat COMEXT와 기존 UN Comtrade를 이용해 HS·CN 품목, 국가, 기간, 수출입, 관세·시장접근 데이터를 조회하는 MCP 라우팅입니다. 철강·원료·가스의 국가별 교역과 공급망 비교에 사용합니다.
metadata:
  lumina-source: skill-mcp:trade-market
---

# 무역·시장 MCP

HS·CN 품목과 국가별 수출입 조회에는 `trade-market` MCP를 사용합니다.

- 한국을 보고국으로 한 품목·국가별 통관 통계는 `source="customs_kr"`를 사용합니다. 국가코드는 ISO 영문 2자리이고 조회기간은 한 번에 12개월 이내입니다.
- 미국 수출입은 `source="census"`를 사용합니다. 미국 Census의 숫자형 `CTY_CODE`와 수입·수출 HS 변수가 서로 다름에 주의합니다.
- EU 회원국의 상세 CN/HS 교역은 `source="eurostat_comext"`와 `DS-045409`를 사용합니다. 대용량 전체 추출을 하지 말고 reporter·partner·product·period를 모두 제한합니다.
- WTO 지표·관세·시장접근은 `source="wto"`를 사용하고, 먼저 `search_catalog`로 지표 코드를 확인합니다.
- 전 세계 여러 보고국 비교는 기존 `comtrade` MCP의 `latest_common_annual_trade_data`를 우선합니다. 서로 다른 국가의 최신 연도를 섞지 않습니다.
- 연결과 키 문제는 `get_source_health`로 구분합니다. 빈 데이터는 장애로 단정하지 않고 기간·품목분류·국가코드를 재확인합니다.
- 결과에는 보고국, 상대국, 품목분류와 버전, 흐름, 기간, 단위, 출처, 완전성을 명시합니다.

## 트리거 경계

- 수출입·HS코드·CN코드·관세·무역수지·교역상대국·공급망 요청에 사용합니다.
- 거시금융 시계열은 `macro-finance`, 기업 공시는 `company-disclosure`, 에너지 가격은 기존 `eia` 또는 `energy-commodities`로 보냅니다.

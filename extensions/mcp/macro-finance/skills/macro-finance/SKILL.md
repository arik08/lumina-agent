---
name: macro-finance
description: FRED, ECB, BIS, NY Fed, OECD, 일본 e-Stat과 기존 ECOS·KOSIS의 금리·물가·환율·고용·산업생산·유동성·신용 시계열을 조회하는 MCP 라우팅입니다. 철강 수요 선행지표와 국가별 금융여건 비교에 사용합니다.
metadata:
  lumina-source: skill-mcp:macro-finance
---

# 거시·금융 MCP

거시경제·금융시장 시계열에는 `macro-finance` MCP를 사용합니다.

- 미국 정책금리·국채금리·CPI·PPI·고용·산업생산은 `source="fred"`를 사용합니다.
- 유로 환율·통화량·은행대출·ECB 지표는 `source="ecb"`, 국제신용·글로벌 유동성·부채 비교는 `source="bis"`를 사용합니다.
- SOFR·TGCR·BGCR·RRP·OBFR는 `source="nyfed"`를 사용합니다.
- 국가 간 선행지수·금융시장·산업지표는 `source="oecd"`, 일본 정부통계는 `source="estat_jp"`를 사용합니다.
- 한국 환율·금리·통화지표는 기존 `ecos`, 국내 통계표는 기존 `kosis` MCP를 우선합니다.
- 먼저 `search_catalog`로 시리즈·데이터셋을 찾고 `query_series`에 공식 ID를 전달합니다. SDMX 소스는 dataset과 차원 순서를 임의로 추측하지 않습니다.
- 결과 비교 전 주기, 단위, 계절조정 여부, 기준연도와 개정시점을 확인합니다. ECB만으로 철강 수요를 직접 단정하지 않습니다.
- 인증 또는 연결 문제는 `get_source_health`로 구분합니다.

## 트리거 경계

- 금리·물가·환율·통화·고용·산업생산·경기선행·유동성·신용 요청에 사용합니다.
- HS 품목 수출입은 `trade-market`, 기업 재무는 `company-disclosure`, 에너지 현물 가격은 기존 `eia`로 보냅니다.

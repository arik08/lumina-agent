---
name: ecos
description: 원화 환율·국내 금리·통화·한국 경제지표의 최신 수치나 추이를 확인하고 환율·금리 영향을 분석할 때 한국은행 ECOS를 조회합니다. 국내 인구·산업 통계표는 kosis, 해외 거시지표는 macro-finance를 사용합니다.
metadata:
  lumina-source: skill-mcp:ecos
---

# 한국은행 ECOS MCP

`ecos` MCP로 한국은행 경제통계를 조회합니다.

- 환율은 `get_exchange_rate`, 주요 지표는 `get_key_statistics`를 우선 사용합니다.
- 일반 통계는 `list_stat_tables`로 통계표 코드를 찾고 `list_stat_items`로 항목 코드를 확인한 뒤 `get_statistic_data`를 호출합니다.
- 연결이나 API 키 문제가 의심되면 `check_connection`을 사용합니다.
- 결과에는 통계표·항목 코드, 기간, 주기, 단위와 ECOS 출처를 명시합니다.

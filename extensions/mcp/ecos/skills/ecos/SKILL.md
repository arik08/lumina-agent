---
name: ecos
description: 한국은행 ECOS의 환율·경제통계 시계열을 조회하는 MCP 라우팅입니다.
metadata:
  lumina-source: skill-mcp:ecos
---

# 한국은행 ECOS MCP

`ecos` MCP로 한국은행 경제통계를 조회합니다.

- 환율은 `get_exchange_rate`, 주요 지표는 `get_key_statistics`를 우선 사용합니다.
- 일반 통계는 `list_stat_tables`로 통계표 코드를 찾고 `list_stat_items`로 항목 코드를 확인한 뒤 `get_statistic_data`를 호출합니다.
- 연결이나 API 키 문제가 의심되면 `check_connection`을 사용합니다.
- 결과에는 통계표·항목 코드, 기간, 주기, 단위와 ECOS 출처를 명시합니다.

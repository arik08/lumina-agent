---
name: ecos
description: 한국은행 ECOS의 환율, 주요 경제지표와 통계 시계열을 조회할 때 사용하는 MCP 라우팅 지침입니다.
metadata:
  lumina-source: skill-mcp:ecos
---

# 한국은행 ECOS MCP

환율, 금리, 물가, 통화와 한국은행 경제통계는 `ecos` MCP를 사용합니다.

- 대표 환율은 `get_exchange_rate`, 주요 지표 탐색은 `get_key_statistics`를 우선합니다.
- 통계표와 항목 코드를 모르면 `list_stat_tables`, `list_stat_items`로 확인한 뒤 `get_statistic_data`를 호출합니다.
- 답변에는 통계 코드, 주기, 조회 기간과 단위를 표시합니다.
- 오류가 나면 `check_connection`으로 API 연결과 조회 조건 오류를 구분합니다.

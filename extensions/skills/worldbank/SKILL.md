---
name: worldbank
description: World Bank의 국가별 개발지표와 국제 비교 시계열을 조회할 때 사용하는 MCP 라우팅 지침입니다.
source: skill-mcp:worldbank
---

# World Bank MCP

GDP, 인구, 개발·빈곤·교육 등 World Bank 국가 지표는 `worldbank` MCP를 사용합니다.

- 국가 코드를 모르면 `search_countries` 또는 `list_countries`, 지표 코드를 모르면 `search_indicators`를 먼저 사용합니다.
- 정의와 출처는 `get_indicator_metadata`, 실제 시계열은 `fetch_indicator_data`로 조회합니다.
- 국가, 지표 코드, 단위, 관측 연도와 결측 여부를 답변에 포함합니다.
- 오류가 나면 `check_connection`으로 연결 문제와 조회 조건을 구분합니다.

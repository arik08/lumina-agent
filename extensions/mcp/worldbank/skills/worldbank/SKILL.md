---
name: worldbank
description: World Bank 국가·경제지표 메타데이터와 시계열을 조회하는 MCP 라우팅입니다.
metadata:
  lumina-source: skill-mcp:worldbank
---

# World Bank MCP

`worldbank` MCP로 국가별 개발·경제지표를 조회합니다.

- 국가 코드는 `search_countries`, 지표 코드는 `search_indicators`로 찾습니다.
- 지표 정의와 출처는 `get_indicator_metadata`로 확인한 뒤 `fetch_indicator_data`로 시계열을 조회합니다.
- 여러 국가는 세미콜론으로 구분하고, 범위가 넓으면 기간과 국가를 먼저 좁힙니다.
- 연결 오류는 `check_connection`으로 확인합니다.
- 답변에 국가 코드, 지표 ID, 기간, 단위·출처 메타데이터를 함께 밝힙니다.

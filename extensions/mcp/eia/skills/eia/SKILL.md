---
name: eia
description: 미국 EIA의 원유·가스·석유제품 가격 시계열을 조회하는 MCP 라우팅입니다.
metadata:
  lumina-source: skill-mcp:eia
---

# U.S. EIA MCP

`eia` MCP로 미국 에너지 통계를 조회합니다.

- WTI, Brent, Henry Hub, 휘발유, 경유는 `list_price_series`로 별칭을 확인한 뒤 `get_energy_price`를 사용합니다.
- 사용자가 EIA series ID를 지정하면 `get_series`를 사용합니다.
- 연결 또는 API 키 오류는 `check_connection`으로 구분합니다.
- 답변에 series ID 또는 별칭, 조회 기간, 단위와 EIA 출처를 밝힙니다.

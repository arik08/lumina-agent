---
name: eia
description: 미국 EIA의 원유·천연가스 등 에너지 가격과 시계열을 조회할 때 사용하는 MCP 라우팅 지침입니다.
source: skill-mcp:eia
---

# U.S. EIA MCP

WTI, Brent, Henry Hub와 미국 에너지 통계는 `eia` MCP를 사용합니다.

- 알려진 대표 가격은 `list_price_series`로 alias를 확인하고 `get_energy_price`를 사용합니다.
- 사용자가 EIA series id를 지정하면 `get_series`로 조회합니다.
- 기간, 빈도, 단위와 series id를 결과에 남깁니다.
- 빈 결과와 연결 실패를 혼동하지 말고 필요하면 `check_connection`을 호출합니다.

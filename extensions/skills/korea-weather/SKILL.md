---
name: korea-weather
description: 대한민국 현재 날씨, 단기·중기 예보, 기상특보와 영향예보를 조회할 때 사용하는 기상청 MCP 라우팅 지침입니다.
metadata:
  lumina-source: skill-mcp:korea-weather
---

# 대한민국 날씨 MCP

국내 현재 관측, 초단기·단기·중기 예보와 기상특보에는 `korea-weather` MCP를 사용합니다.

- 위치명이 주어지면 먼저 `lookup_forecast_zone` 또는 `lookup_warning_zone`으로 좌표·구역코드를 확인합니다.
- 현재 관측은 `get_nowcast_observation`, 시간대별 예보는 `get_nowcast_forecast` 또는 `get_short_term_forecast`를 사용합니다.
- 중기 전망은 `get_mid_term_forecast`와 `get_mid_term_temperature`, 특보는 `get_active_warnings`, 폭염·한파는 `get_impact_forecast`를 사용합니다.
- 발표 시각, 대상 지역과 예보 유효기간을 답변에 명확히 표시합니다.

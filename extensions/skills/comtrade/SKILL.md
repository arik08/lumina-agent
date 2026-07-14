---
name: comtrade
description: 국가·품목·기간별 수출입과 교역 상대국 데이터를 UN Comtrade에서 조회할 때 사용하는 MCP 라우팅 지침입니다.
source: skill-mcp:comtrade
---

# UN Comtrade MCP

국가 간 무역, 수출입 금액·물량, HS 품목과 교역 상대국 분석에는 `comtrade` MCP를 사용합니다.

- reporter 코드를 모르면 `search_reporters` 또는 `list_reporters`로 먼저 확인합니다.
- API key가 없으면 `preview_trade_data`, 승인된 key가 있으면 `get_trade_data`를 사용합니다.
- 결과에는 조회 연도, reporter, partner, flow, 품목 분류와 데이터 제한 여부를 함께 밝힙니다.
- 연결 문제를 데이터 부재로 해석하지 말고 필요하면 `check_connection`으로 분리 진단합니다.

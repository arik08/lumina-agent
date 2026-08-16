---
name: comtrade
description: UN Comtrade 국가별 수출입·품목·교역 상대국 데이터를 조회하는 MCP 라우팅입니다.
metadata:
  lumina-source: skill-mcp:comtrade
---

# UN Comtrade MCP

`comtrade` MCP로 국제 상품무역 데이터를 조회합니다.

- 국가 코드를 모르면 `search_reporters`로 먼저 찾습니다.
- API 키가 없어도 되는 소량 확인은 `preview_trade_data`, 정식 조회는 `get_trade_data`를 사용합니다.
- 여러 국가의 연간 값을 비교하거나 사용자가 "최근 1년", "최근 연도"라고 요청하면 `latest_common_annual_trade_data`를 우선 사용합니다. 가장 최근 달력연도를 고정하지 말고 모든 reporter에 데이터가 있는 `selectedPeriod`를 공통 기준으로 사용합니다.
- 사용자가 명시적으로 "최근 12개월"을 요청한 경우에만 `freq_code="M"`과 완료된 12개 월을 사용합니다. `queryDiagnostics`의 국가별 기간 범위가 다르면 서로 다른 기간을 섞어 비교하지 않습니다.
- 전체 교역은 `cmd_code="TOTAL"`, 수출은 `flow_code="X"`, 수입은 `flow_code="M"`을 기준으로 사용하되 사용자 조건을 우선합니다.
- 연결 오류가 의심되면 `check_connection`을 호출합니다.
- 빈 `data`는 해당 조건의 데이터 부재일 뿐 연결 실패를 뜻하지 않습니다. 복수 reporter 조회에서 `missingReporterCodes`나 `incompleteReporterCodes`가 있으면 국가별 조건과 공통 가용 기간을 다시 확인하고, 전체 국가가 0건이라고 단정하지 않습니다.
- 답변에 reporter, period, 품목·flow·partner 조건과 UN Comtrade 출처를 함께 밝힙니다.

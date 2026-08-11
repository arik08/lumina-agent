---
name: kosis
description: KOSIS 국가통계포털의 통계표, 국가통계 시계열과 메타데이터를 조회할 때 사용하는 MCP 라우팅 지침입니다.
metadata:
  lumina-source: skill-mcp:kosis
---

# KOSIS MCP

대한민국 국가승인통계와 KOSIS 통계표 조회에는 `kosis` MCP를 사용합니다.

- 통계표를 모르면 `search_statistics` 또는 `list_statistics`로 `org_id`와 `tbl_id`를 찾습니다.
- 실제 값은 `get_stat_data`, 항목·단위 확인은 `get_table_meta`, 통계 설명은 `explain_statistics`를 사용합니다.
- 결과에는 통계표명, 기관, 항목, 단위, 주기와 조회 기간을 표시합니다.
- 연결 실패가 의심되면 `check_connection`으로 분리 확인합니다.

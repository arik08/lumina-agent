---
name: kosis
description: KOSIS 국가통계포털의 통계표·수치·메타데이터를 조회하는 MCP 라우팅입니다.
metadata:
  lumina-source: skill-mcp:kosis
---

# KOSIS MCP

`kosis` MCP로 국가통계포털 데이터를 조회합니다.

- 주제 탐색은 `list_statistics`, 키워드 검색은 `search_statistics`를 사용합니다.
- `org_id`와 `tbl_id`를 확인한 뒤 `get_table_meta`로 항목·단위를 파악하고 `get_stat_data`로 수치를 조회합니다.
- 통계 정의나 조사 방법이 필요하면 `explain_statistics`를 사용합니다.
- 연결 문제는 `check_connection`으로 확인합니다.
- 답변에 기관·통계표 ID, 항목, 기간, 단위와 KOSIS 출처를 명시합니다.

---
name: kosis
description: 국내 인구·고용·물가·산업생산·지역별 통계의 수치·추이·비교 근거가 필요할 때 KOSIS 통계표와 메타데이터를 조회합니다. 원화 환율·금리·통화 지표는 ecos를 우선합니다.
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

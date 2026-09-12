---
name: development-finance
description: 아시아 국가의 성장·인구·사회·인프라 여건 비교에 ADB KIDB 공식 지표를 조회합니다. 전 세계 개발·부채 지표는 worldbank로 연결합니다. 개별 개발사업 투자·고객사·환경심사 문서 추출은 지원하지 않습니다.
metadata:
  lumina-source: skill-mcp:development-finance
---

# 국제개발금융 MCP

국제개발금융기관의 국가·산업·인프라 지표에는 `development-finance` MCP를 사용합니다.

- ADB의 아시아 국가·지역 지표는 `source="adb_kidb"`를 사용합니다. 먼저 `search_catalog`에 dataflow를 넣어 공식 indicator 코드를 확인하고, `query_series`에서 지표·경제권 코드를 최대 20개씩 조회합니다.
- World Bank 개발·부채·인프라 지표는 이미 설치된 기존 `worldbank` MCP를 사용합니다. 새 서버에서 중복 호출하지 않습니다.
- ADB KIDB는 분당 20회 제한이 있으므로 데이터플로·국가·기간을 묶어 조회하고 불필요한 반복 호출을 피합니다.
- ADB KIDB v5의 국민계정은 `DF_NA`, 인구 지표는 `DF_PPSI`를 사용합니다. 구형 `EO_NA`·`PPL_POP` 입력은 새 코드로 변환되며 조회에는 시작·종료 연도를 지정합니다.
- IFC·MIGA·AIIB·EBRD·IDB 프로젝트 포털은 안정적으로 문서화된 프로젝트 레코드 API가 없고, 상세자료가 HTML/PDF/XLSX와 포털 내부 호출에 의존합니다. 자동화하면 화면 변경·문서 OCR·누락 검증 문제가 커지므로 연결하지 않습니다.
- AfDB Open Data는 통계 포털과 프로젝트 문서가 분리되어 있고 안정된 범용 프로젝트 API 계약을 확인하기 어려워 제외합니다.
- 프로젝트 이름이나 PDF 검색 결과를 구조화된 프로젝트 파이프라인으로 오인하지 않습니다. 필요하면 공식 포털 링크를 사람이 확인하는 별도 조사로 처리합니다.

## 트리거 경계

- 아시아 개발지표, ADB SDMX, 국가별 인프라·에너지·거시 비교에 사용합니다.
- 실제 프로젝트 고객사·투자·E&S 문서 자동 추출 요청은 이 MCP가 지원하지 않는다고 명확히 답합니다.

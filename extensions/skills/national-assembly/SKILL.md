---
name: national-assembly
description: 열린국회정보 OpenAPI와 국민참여입법센터 API를 함께 사용하는 대한민국 국회 MCP 라우팅 스킬입니다.
source: skill-mcp:national-assembly
---

# 대한민국 국회 MCP

이 스킬은 `national-assembly` MCP 서버를 통해 대한민국 국회 관련 공개 데이터를 조회할 때 사용합니다.

## 데이터 소스

- 열린국회정보 OpenAPI: 국회의원, 의안, 일정, 회의록, 위원회, 표결, 청원, 국회 연구자료 등을 조회합니다.
- 국민참여입법센터: 입법현황, 입법계획, 입법예고, 행정예고, 법령해석례, 의견제시사례를 조회합니다.

## 사용 지침

- 사용자가 국회의원, 의안, 국회 회의, 표결, 위원회, 청원, 입법예고, 행정예고, 법령해석례, 의견제시사례를 물으면 이 MCP를 우선 사용합니다.
- 먼저 `discover_apis` 또는 도메인 통합 도구로 적절한 API와 파라미터를 확인한 뒤 조회합니다.
- 특정 API 코드를 알고 있거나 도구가 포괄하지 않는 데이터는 `query_assembly`로 직접 호출합니다.
- 국민참여입법센터 데이터는 `assembly_org`의 `type=lawmaking` 흐름을 사용합니다.
- 답변에는 사용한 데이터 소스와 조회 조건을 짧게 밝혀 사용자가 근거를 확인할 수 있게 합니다.

## 입법예고 필수 조회 경로

입법예고는 핵심 업무 경로입니다. 사용자가 "입법예고", "예고된 법안", "정부입법예고", "입법예고된 법안"을 물으면 아래 순서로 조회합니다.

1. 국민참여입법센터 입법예고를 우선 조회합니다.
   - 도구: `assembly_org`
   - 필수 파라미터: `type="lawmaking"`, `category="legislation"`, `diff="0"`
   - `diff="0"`은 진행중 입법예고, `diff="1"`은 종료된 입법예고입니다.
   - 법률만 좁힐 때는 `ls_cls_cd="AA0101"`을 함께 사용합니다.
2. 사용자가 종료된 예고까지 원하면 같은 도구를 `diff="1"`로 한 번 더 호출합니다.
3. 국회 열린국회정보의 진행중 입법예고도 함께 확인해야 하면 `query_assembly(api_code="nknalejkafmvgzmpt")`를 보조로 사용합니다.
4. 특정 법령명 키워드가 있으면 국민참여입법센터 API의 `lsNm` 검색이 필요합니다. MCP 도구 분기에서 `keyword`가 입법계획으로 해석될 수 있으므로, 결과가 입법계획처럼 보이면 `query_assembly` 또는 upstream CLI/직접 API 경로로 입법예고를 재조회했다고 사용자에게 밝혀야 합니다.

## 설정

- 열린국회정보 키: `ASSEMBLY_API_KEY`
- 국민참여입법센터 정보공개 서비스 신청 ID: `LAWMKING_OC`
- 기본 프로필: `MCP_PROFILE=full`

초기 실행 시 upstream `hollobit/assembly-api-mcp` 저장소를 `.myharness/mcp-cache/assembly-api-mcp`에 내려받아 빌드합니다. 이미 별도 위치에 빌드해 둔 경우 `NATIONAL_ASSEMBLY_MCP_DIR`로 해당 경로를 지정할 수 있습니다.

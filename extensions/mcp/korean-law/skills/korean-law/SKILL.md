---
name: korean-law
description: 대한민국 법령, 판례, 행정규칙, 자치법규와 법률 쟁점을 조사할 때 사용하는 법제처 기반 MCP 라우팅 지침입니다.
metadata:
  lumina-source: skill-mcp:korean-law
---

# 대한민국 법률 MCP

법령·판례·행정규칙·자치법규·조약·해석례 조사는 `korean-law` MCP를 사용합니다.

- 단순 탐색은 `search_law` 또는 `search_decisions`, 원문 확인은 `get_law_text` 또는 `get_decision_text`를 사용합니다.
- 복합 쟁점은 목적에 맞는 `chain_*` 도구를 우선하고, 필요한 추가 도구는 `discover_tools` 후 `execute_tool`로 호출합니다.
- 결론 전에 `verify_citations`로 조문·사건 인용을 확인합니다.
- 법률 정보는 일반 안내임을 분명히 하고, 기준일·법령명·조문·사건번호를 가능한 범위에서 제시합니다.

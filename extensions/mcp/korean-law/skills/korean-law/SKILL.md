---
name: korean-law
description: 한국 업무의 법적 근거·의무·처분기준·시행일·관련 판례를 확인할 때 법제처 법령·판례·행정규칙·자치법규·조약·법령해석례를 조회합니다. 계류 법안·입법예고는 national-assembly를 사용합니다.
metadata:
  lumina-source: skill-mcp:korean-law
---

# 대한민국 법령 MCP

`korean-law` MCP로 대한민국 법령 관련 공개 데이터를 조회합니다.

`installer.bat` 실행 시 필요한 Node.js 패키지를 설치하고 호환성 패치를 적용합니다.
일반/개발 웹 실행기는 이 MCP의 패키지를 설치하지 않습니다. 의존성이 없거나 잠금 파일이 변경되면 Installer를 다시 실행하세요.
CLI에서 직접 실행할 때는 저장소 루트에서 `python extensions/mcp/korean-law/runtime/bootstrap.py --prepare`를 먼저 실행하세요.
설치에는 Node.js/npm과 네트워크 연결이 필요하며, 준비 후에는 별도 설치 없이 MCP를 시작합니다.

- 질문의 대상이 법령, 판례, 행정규칙, 자치법규, 조약, 법령해석례 중 무엇인지 먼저 구분하고 해당 MCP 도구를 선택합니다.
- 현행 여부, 시행일, 사건번호, 기관, 검색어처럼 사용자가 준 범위를 그대로 유지합니다.
- 이름이 비슷한 결과는 공포번호·시행일·사건번호 등 식별자로 재확인합니다.
- 복합 조사에는 `legal_research`를 사용하고 의도에 맞는 `task`를 지정합니다: 법체계=`law_system`, 처분 근거=`action_basis`, 종합 수집=`full_research`. 과징금·과태료·영업정지 기준은 `task="action_basis", scenario="penalty"`로 호출합니다.
- 판례·결정례를 직접 검색할 때 `search_decisions`의 `domain`을 반드시 지정합니다. 일반 판례는 `precedent`, 법령해석례는 `interpretation`, 개인정보보호위원회 결정은 `pipc`입니다. 여러 종류가 필요하면 각각 호출하거나 `legal_research(task="full_research")`로 종합합니다.
- 법령명을 아는 경우 `search_law`의 정확 일치 결과를 우선하고 식별자를 넘겨 `get_law_text`를 호출합니다. 관련도 낮은 첫 결과를 임의의 기본 법령으로 채택하지 않습니다.
- 법률적 결론을 추정하지 말고 조회된 원문·메타데이터와 해석을 구분합니다.
- 답변에 사용한 데이터 종류, 식별자, 기준일과 법제처 출처를 밝힙니다.

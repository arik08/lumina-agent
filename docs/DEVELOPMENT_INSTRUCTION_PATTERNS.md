# 루미나 개발 지시 패턴 분석

## 1. 문서 목적

이 문서는 루미나 개발 과정에서 반복적으로 나타난 사용자 지시를 분석해, 개별 요청 뒤에 있는 공통 판단 기준을 정리합니다. 새로운 제품 요구사항을 만드는 문서가 아니라 앞으로의 구현·검토·보고가 사용자의 의도와 더 빠르게 정렬되도록 돕는 작업 지침입니다.

이 문서는 다음 원칙으로 사용합니다.

- 루트 [`AGENTS.md`](../AGENTS.md), [`LUMINA_DESIGN.md`](LUMINA_DESIGN.md), 기능별 `docs/project-context/` 계약을 대체하지 않습니다.
- GUI·디자인 패턴은 [`PRODUCT.md`](../PRODUCT.md)와 [`DESIGN.md`](../DESIGN.md)의 제품 언어를 기준으로 해석합니다.
- 충돌 시 루트 `AGENTS.md`에 정의된 문서 우선순위를 따릅니다.
- 누적된 지시에서 반복성이 높은 패턴을 정리한 것이므로, 가장 최근의 명시적 요청이 언제나 우선합니다.
- 과거 사례의 구체적인 구현 위치나 수치는 현재 source와 runtime에서 다시 확인합니다.

## 2. 핵심 결론

루미나 관련 지시는 대체로 다음 한 문장으로 요약할 수 있습니다.

> 요청한 범위 안에서 가장 작은 올바른 변경을 하고, 문서나 코드의 존재가 아니라 실제 데이터·계약·화면에서 의도한 결과가 정확히 나타나는지 증명합니다.

여기에는 네 가지 일관된 가치가 있습니다.

1. **정확성:** 표현, 위치, 크기, 동작과 데이터 범위를 요청 그대로 맞춥니다.
2. **실재성:** 보이는 흉내보다 실제 상태 전이, 저장, 권한과 runtime 동작을 구현합니다.
3. **절제:** 요청하지 않은 재설계, 설명 문구, 상태와 추상화를 덧붙이지 않습니다.
4. **검증 가능성:** 완료 판단을 source 추정이 아니라 test, live contract, 실제 화면과 산출물로 뒷받침합니다.

## 3. 반복되는 지시 패턴

### 3.1 요청 범위를 좁고 정확하게 유지합니다

작은 UI 수정, 한 개의 라벨, 특정 클릭 영역, 순서 변경이나 되돌리기 요청은 주변 영역의 개선 기회가 아니라 독립적인 수용 기준으로 취급합니다.

- 정확한 문자열이나 수치가 제시되면 그대로 사용합니다.
- 한 요소의 크기·색상·순서 요청을 전체 화면의 스타일 변경으로 확대하지 않습니다.
- 최신 지시가 이전 해석을 좁히면 최신 범위만 남깁니다.
- 되돌리기도 전체 파일 복원이 아니라 해당 변경만 제거합니다.
- 작업 중 발견한 별도 문제는 임의로 함께 고치지 않고 분리해 보고합니다.

이 패턴의 목적은 단순히 diff를 작게 만드는 것이 아닙니다. 사용자가 지정한 원인과 결과의 관계를 흐리지 않고, 다른 진행 중인 변경을 보존하는 데 있습니다.

### 3.2 “보이게 만들기”보다 “실제로 동작하게 만들기”를 요구합니다

버튼, 탭, 설정, 설치 상태, Queue와 알림처럼 상태를 다루는 기능은 시각적 반응만 추가해서는 완료되지 않습니다.

- 설정 메뉴는 단순 스크롤 이동이 아니라 실제 표시 상태를 바꾸는 control이어야 합니다.
- 설치 해제는 disabled 표시에 그치지 않고 실제 설치 상태와 다음 action을 되돌려야 합니다.
- Queue·Steering 같은 실행 상태는 backend의 실제 상태와 연결되어야 합니다.
- 저장이 필요한 선택값은 화면 local state가 아니라 정해진 서버 scope와 복원 계약을 가져야 합니다.
- 숨긴 action은 단지 CSS로 감추는 것이 아니라 권한과 backend 검증이 함께 일치해야 합니다.

즉, 사용자 지시에서 “된다”, “작동한다”, “없앤다”는 말은 대개 실제 상태와 생명주기까지 포함합니다.

### 3.3 source보다 실제 runtime을 먼저 신뢰합니다

코드가 맞아 보이거나 health endpoint가 정상이어도 사용자가 보는 프로세스가 오래된 schema나 bundle을 제공할 수 있습니다. 따라서 runtime 문제는 실행 중인 계약부터 확인합니다.

- API 문제는 served OpenAPI, 실제 response, listening process와 log를 확인합니다.
- 저장·기억·설정 문제는 실제 DB row, migration 상태와 extractor/write path를 확인합니다.
- UI 문제는 사용자가 보는 URL과 실제 제공 bundle의 DOM·computed style을 확인합니다.
- launcher 문제는 wrapper가 아니라 canonical launcher와 그 process tree를 추적합니다.
- repository file과 runtime catalog가 함께 존재하면 양쪽을 모두 확인합니다.

이 패턴은 “수정한 source”와 “현재 사용자가 경험하는 시스템”이 다를 수 있다는 전제를 둡니다.

### 3.4 화면에서 보이는 수용 기준을 정밀하게 다룹니다

UI 지시는 기능적 성공만큼 위치, 간격, hit target, 전환 순서와 시각적 잡음을 중요하게 봅니다.

- “옆과 같게”는 source token을 추정하는 것이 아니라 인접 요소의 live computed value를 맞추는 뜻입니다.
- “즉시 닫기”는 내부 state가 나중에 정리되는지가 아니라 이전 화면이 잠깐 비치지 않는지가 기준입니다.
- 동일 action을 수행하는 인접 영역은 하나의 연속된 hover·click target으로 만드는 편을 선호합니다.
- 클릭 가능한 요소의 hover와 keyboard focus는 부가 장식이 아니라 interaction 계약입니다.
- 요청한 위치를 비슷한 주변 영역으로 대체하지 않습니다.
- Light만 흐리다는 요청에는 Dark theme까지 바꾸지 않습니다.

### 3.5 정보 밀도는 높이되 불필요한 소음은 줄입니다

루미나 UI는 많은 실행 정보를 다루지만, 모든 상태와 설명을 항상 노출하는 방향을 선호하지 않습니다.

- 접힌 요약에는 전체 상세 대신 합계·경과 시간처럼 판단에 필요한 값만 보여줍니다.
- 필요 없다고 지정한 출처·상태 문구는 다른 설명으로 바꾸지 않고 제거합니다.
- 단순 채팅 완료처럼 사용자가 이미 보고 있는 사건은 알림을 만들지 않되 실패, 승인, 예약 실행, Tool·Artifact 결과처럼 행동 가치가 있는 신호는 유지합니다.
- loading, cursor와 animation은 실제 진행을 전달해야 하며 연출을 위해 응답을 늦추거나 깜빡임을 추가하지 않습니다.
- 사용자가 이미 본 성공 content는 재검증 중에도 유지하고, 조용히 최신 상태로 교체합니다.

핵심은 정보를 적게 보여주는 것이 아니라, 다음 판단이나 행동에 가치가 있는 정보만 남기는 것입니다.

### 3.6 기존 제품 언어와 공용 primitive를 우선합니다

국소 요청을 해결할 때도 화면별 예외 규칙보다 기존 token, component와 interaction pattern을 먼저 사용합니다.

- 새 button·menu·tooltip 동작을 화면마다 복제하지 않습니다.
- 공용 component로 해결할 수 없으면 caller-specific hook이나 semantic variant를 추가합니다.
- 기존 outside-click, inline confirmation, portal, selection과 focus pattern을 재사용합니다.
- 사용자에게 보이는 한국어 명칭이 확정되면 tab, empty state, status와 error 등 관련 접점을 같은 표현으로 맞춥니다.
- 제품의 절제된 시각 언어를 유지하고 작은 요청을 장식적 redesign으로 확대하지 않습니다.

### 3.7 권한·격리·재현성을 UI 편의보다 앞에 둡니다

루미나의 상태는 사용자, 조직, Project, Session과 Run 경계 안에서 해석됩니다. Frontend 편의만으로 이 경계를 완화하지 않습니다.

- Frontend가 보낸 ID, 경로, scope와 extension 이름을 backend에서 다시 검증합니다.
- 사용할 수 없는 action은 UI에서 노출하지 않고 API도 동일한 권한을 강제합니다.
- 다른 사용자·Project·QA runtime의 데이터가 섞이지 않도록 격리합니다.
- Run이 사용하는 파일, 지침, Provider와 Skill·MCP는 정확한 version·revision·digest로 고정합니다.
- 새 Provider model이나 extension은 발견만으로 자동 활성화하지 않습니다.
- 동시성 문제는 화면 revision 표시가 아니라 DB의 원자적 compare-and-swap으로 해결합니다.
- TLS, Secret과 인증 문제를 임시 우회로 정상처럼 보이게 하지 않습니다.

### 3.8 문서의 의도와 현재 구현 상태를 분리합니다

설계 문서는 목표 계약이고 source·migration·test는 현재 구현 증거입니다. 둘 중 하나만으로 완료를 주장하지 않습니다.

- 상태 검토에서는 `Implemented`, `Target`, 부분 구현과 환경 미검증을 구분합니다.
- README는 짧은 진입점으로 유지하고 상세 계약은 `LUMINA_DESIGN.md`와 기능별 문서에 둡니다.
- 흩어진 문서를 합칠 때는 복사 묶음이 아니라 중복을 병합하고 충돌을 해소한 synthesis를 만듭니다.
- 새 개념은 단독 메모로 고립시키지 않고 기존 기준 문서의 관련 section과 연결합니다.
- 긴 설계 문서는 관련 heading과 keyword를 먼저 찾아 국소적으로 읽고, 구조 전체가 바뀔 때만 전체 정합성을 점검합니다.
- 외부 제품·문서 조사는 현재 루미나의 계약과 비교해 중복되지 않는 교훈만 반영합니다.

### 3.9 검증은 변경 위험과 사용자에게 보이는 결과에 비례합니다

완료 보고에는 “무엇을 실행했는가”보다 “무엇이 확인되었는가”가 중요합니다.

- Backend 변경은 관련 test와 필요 시 migration·DB 동작을 확인합니다.
- Frontend 변경은 target test, typecheck와 build를 확인합니다.
- 실제 UI 변경은 격리된 browser에서 화면, 반응형 배치, interaction과 console 오류를 확인합니다.
- UI 개선 결과를 보고할 때는 변경된 영역의 screenshot을 포함합니다.
- export·문서·workbook 같은 산출물은 생성 성공뿐 아니라 내용, 구조, filename과 안전성까지 검사합니다.
- 조건부 dependency가 없어 test가 skip되면 해당 환경까지 검증했다고 표현하지 않습니다.
- 검증 도구 자체가 실패하면 제품 실패와 구분하고, 보이는 결과가 중요할 때는 깨끗한 격리 환경에서 다시 확인합니다.

### 3.10 사용자 환경과 다른 작업을 보존합니다

검증과 정리 과정도 제품 변경만큼 범위가 명확해야 합니다.

- 사용자가 실행한 runtime, port, browser tab과 context를 재사용하거나 종료하지 않습니다.
- 자신이 시작한 격리 process와 browser context만 정리합니다.
- 이름 기반으로 모든 Chrome·Python·Node process를 종료하지 않습니다.
- dirty worktree의 기존 변경은 사용자 작업으로 보고 보존합니다.
- stage와 commit 전에 diff, runtime data, cache와 Secret 포함 여부를 확인합니다.
- push는 명시적 요청이 있을 때만 수행합니다.

## 4. GUI 관련 요청 패턴 상세 분석

GUI 요청은 단순히 “예쁘게 바꿔 달라”는 형태보다, 사용자가 실제로 보고 조작하는 특정 지점을 기준으로 매우 구체적인 경향을 보입니다. 구현자는 요청을 CSS 변경으로 축소하지 말고 **표시 값, 배치, interaction, 상태 전이, backend 연결과 실제 화면 검증**의 묶음으로 해석해야 합니다.

### 4.1 GUI 요청을 해석하는 기본 관점

GUI 요청에서 자주 쓰이는 표현은 다음과 같은 수용 기준을 내포합니다.

| 사용자 표현 | 기본 해석 | 피해야 할 해석 |
|---|---|---|
| “이 버튼이 작동하게” | 클릭 후 실제 state와 표시 content가 바뀌어야 함 | 같은 위치로 scroll하거나 hover만 추가 |
| “여기와 같게” | 인접 기준 요소의 live computed size·weight·color·spacing과 일치 | source의 비슷한 token을 추정해 적용 |
| “여기로 옮겨” | 지정한 visual hierarchy와 anchor 안에 배치 | 근처의 비슷한 footer·sidebar 영역에 배치 |
| “바로/즉시 닫히게” | 다음 frame에서 이전 content가 비치지 않아야 함 | navigation 완료 후 뒤늦게 state 정리 |
| “얇게/작게” | 불필요한 text·tooltip·padding까지 제거한 최소 표현 | height만 줄이고 기존 장식을 유지 |
| “글씨가 작다” | 해당 요소의 가독성을 국소적으로 개선 | 전체 app typography scale 변경 |
| “Light에서 흐리다” | Light selector만 조정하고 Dark는 보존 | 공용 token을 바꿔 두 theme 모두 변경 |
| “이 문구는 필요 없다” | 해당 visible copy를 제거 | 비슷한 설명이나 status 문구로 대체 |
| “설치로 돌아가야 한다” | uninstall 후 실제 lifecycle과 action label이 초기 상태로 복귀 | enable/disable toggle 상태로 해석 |
| “깜빡이지 않게” | 마지막 성공 content를 유지한 채 새 결과로 교체 | loading 동안 목록·count를 비움 |
| “실제 답변까지 테스트” | Provider→Tool→LLM final answer 전체 경로 확인 | readiness나 schema 호출만 확인 |
| “스크린샷처럼” | 표시된 위치·크기·정렬 자체가 수용 기준 | 기능만 같으면 배치 차이는 허용 |

### 4.2 한 요소 단위의 국소 수정이 기본입니다

GUI 요청은 지정된 element를 중심으로 처리합니다. 한 row label, 한 icon, 한 button border나 한 pixel delta가 대상이면 해당 element와 그 상태 selector만 바꾸는 것이 기본입니다.

- 먼저 DOM hierarchy와 실제 적용 selector를 확인합니다.
- 더 넓은 shared selector가 값을 덮어쓰는지 computed style로 확인합니다.
- 국소 hook이 없다면 component 전체를 복제하지 않고 `className`, `menuClassName`, semantic variant 같은 작은 확장점을 만듭니다.
- 요청하지 않은 copy, padding, layout, color와 주변 component는 그대로 둡니다.
- 동일 element의 desktop·narrow breakpoint 값이 따로 있으면 두 상태를 각각 확인합니다.
- 변경 과정에서 발견한 죽은 selector는 이번 변경과 직접 연결될 때만 정리합니다.

국소 수정의 성공 기준은 “diff가 작다”가 아니라 “요청한 하나의 차이만 화면에서 달라졌다”입니다.

### 4.3 글꼴·크기·가독성 요청은 인접 기준과 정확한 수치를 따릅니다

글자가 작거나 흐리다는 지시는 추상적인 typography 개선 요청이 아닐 때가 많습니다. 사용자는 대개 비교 대상이나 정확한 증분을 수용 기준으로 제시합니다.

- 정확한 `px` 값이나 증분이 있으면 반올림하거나 design scale의 근사값으로 바꾸지 않습니다.
- “제목과 같게”, “왼쪽 metadata와 같게”라면 양쪽의 실제 `font-size`, `font-weight`, `line-height`를 측정합니다.
- 공간 제약이 명확하지 않은 우측 pane·상세 pane에서는 지나치게 작은 label scale보다 읽을 수 있는 body scale을 선호합니다.
- 한 control의 글꼴 변경을 shared `SelectMenu`, 전체 table이나 `.feature-view`로 확대하지 않습니다.
- ellipsis, row height와 vertical alignment가 깨지지 않는지 함께 확인합니다.
- Light의 contrast 문제와 font-size 문제를 구분하고, 필요한 selector만 조정합니다.

### 4.4 위치·순서·정렬 요청은 visual hierarchy를 기준으로 합니다

사용자가 특정 요소의 위치를 지정할 때는 DOM상 가까운 곳보다 화면에서 인식되는 소속과 순서가 중요합니다.

- screenshot이나 설명에서 가리킨 container를 anchor로 삼습니다.
- “모델 선택기 왼쪽”, “제목 오른쪽”, “history 영역 안”처럼 상대 위치가 명시되면 sibling 순서와 grouping을 그대로 맞춥니다.
- 같은 row에 있어도 divider, gap이나 별도 wrapper로 시각적으로 분리되면 잘못된 배치일 수 있습니다.
- 두 요소의 bottom edge, baseline, icon center와 text center가 어긋나지 않는지 확인합니다.
- desktop에서 맞더라도 narrow layout에서 순서가 역전되거나 다른 줄로 잘못 떨어지지 않는지 확인합니다.
- 배치를 바꿀 때 keyboard focus 순서와 screen reader reading order도 시각 순서와 일치시킵니다.

### 4.5 클릭 영역·hover·focus는 하나의 interaction 계약입니다

클릭 가능한 요소는 보이는 영역, hover가 반응하는 영역과 실제 hit target이 일치해야 합니다.

- 같은 action을 수행하는 인접 summary는 하나의 wrapper로 묶어 연속된 click target으로 만듭니다.
- 사용자가 특정 text·icon·row 영역을 클릭 대상으로 지목하면 nearby button으로 대신하지 않습니다.
- hover feedback은 선택 사항이 아니라 클릭 가능성을 알리는 기본 수용 기준입니다.
- hover만 넓고 실제 button은 좁거나, 반대로 click은 되지만 hover가 일부에만 보이는 상태를 피합니다.
- `cursor`, hover background·text·border, `aria-expanded`, keyboard activation과 focus ring을 함께 확인합니다.
- icon-only action은 accessible name과 충분한 hit area를 유지합니다.
- portal menu·tooltip은 clipping과 z-index뿐 아니라 trigger와의 alignment를 확인합니다.

### 4.6 control은 실제 상태 전이를 표현해야 합니다

GUI control은 backend 또는 명확한 frontend state machine과 연결되어야 합니다. label과 color만 바꾸는 방식은 실제 기능을 대신하지 못합니다.

- tab·sidebar control은 선택된 section과 표시 content를 실제로 바꿉니다.
- install action은 `Install → Installed → inline delete confirmation → Install`의 실제 lifecycle과 일치해야 합니다.
- save control은 persisted scope, loading, success, conflict와 error 상태를 같은 자리에서 표현합니다.
- Queue·Steering·Run 상태는 현재 backend snapshot과 event replay 결과를 반영합니다.
- loading 중 geometry가 움직이지 않도록 width, height, icon slot과 padding을 고정합니다.
- invalid 또는 권한 없는 상태에서는 실패할 action을 노출한 뒤 오류를 보여주는 대신, 가능한 action만 제공합니다.
- optimistic UI를 사용하더라도 backend 실패 시 복원할 이전 상태와 inline error가 있어야 합니다.

### 4.7 전환 중 빈 화면·깜빡임·이전 content 노출을 결함으로 봅니다

사용자는 최종 상태뿐 아니라 상태가 바뀌는 짧은 순간도 제품 경험으로 판단합니다.

- filter·tag 전환 시 마지막 성공 목록과 count를 유지하고 새 response가 도착하면 교체합니다.
- panel close는 history rewind나 비동기 navigation 전에 화면에서 먼저 숨깁니다.
- session·artifact 이동 중 이전 content가 잠깐 노출되지 않도록 state 정리 순서를 제어합니다.
- loading을 표시하기 위해 이미 유효한 content 전체를 skeleton이나 빈 state로 바꾸지 않습니다.
- 첫 방문처럼 cache가 전혀 없을 때만 전체 loading state를 사용합니다.
- 화면이 갱신될 때 scroll 위치와 사용자의 현재 reading context를 불필요하게 흔들지 않습니다.
- animation은 opacity·color 같은 제한된 property로 사용하고 layout shift를 만드는 scale·geometry animation은 피합니다.

### 4.8 정보는 사용 맥락에 맞는 위치와 양으로 보여줍니다

동일한 정보도 언제, 어디에 표시하는지에 따라 유용성이 달라집니다.

- 첫 답변 usage에는 현재 답변 값을 중심으로 보여주고, 비교 가치가 생기는 이후 turn에서 session 누계를 제공합니다.
- grouped Tool Calling row에는 펼치지 않아도 합계 duration을 알 수 있게 합니다.
- streaming 중의 Queue·Steering은 관련 control인 model selector 가까이에 둡니다.
- 단위·통화가 table column 전체에 공통이면 header에 한 번 표시하고 각 cell은 값에 집중합니다.
- collapsed panel은 다음 행동에 필요한 최소 signal만 남기고 불필요한 tooltip·설명·중복 label을 제거합니다.
- 사용자가 제거를 요청한 source·provider·status copy는 기능에 필수적이지 않다면 visible UI에서 완전히 뺍니다.
- 정보가 많다는 이유로 모든 값을 chip이나 card로 만들지 않고 기존 hierarchy 안에서 밀도를 조절합니다.

### 4.9 알림과 진행 표시는 행동 가치가 있을 때만 강조합니다

알림·badge·spinner·streaming cursor는 시선을 요구하기 때문에 단순 장식보다 엄격한 기준을 적용합니다.

- 단순 채팅 완료처럼 현재 화면에서 이미 알 수 있는 사건은 notification noise로 봅니다.
- 실패, 승인 요청, 예약 실행, Tool 사용과 Artifact 생성처럼 후속 확인 가치가 있는 완료는 유지합니다.
- badge는 bell icon과 겹치지 않도록 실제 header geometry에서 확인합니다.
- streaming text는 provider output에 가깝게 보여주고 연출용 typing delay를 만들지 않습니다.
- 작은 고정 buffer는 허용할 수 있지만 응답 길이에 비례해 느려지는 pacing은 피합니다.
- blinking cursor·icon이 거슬린다는 요청에는 streaming 자체를 늦추지 않고 시각 효과만 제거합니다.
- progress는 실제 처리 단계와 연결하고 terminal 이전에 완료처럼 보이지 않게 합니다.

### 4.10 삭제·닫기·취소는 현재 맥락 안에서 처리합니다

destructive action이나 dismiss action은 사용자의 시선을 별도 popup으로 빼앗지 않고 현재 대상과 결과의 관계를 유지합니다.

- 삭제는 `window.confirm`이나 modal보다 같은 button의 inline 2단계 확인을 사용합니다.
- 확인 상태에서는 대상 이름이나 action 의미가 모호하지 않아야 합니다.
- 선택 row, search, edit 대상, Project 또는 화면이 바뀌면 armed state를 해제합니다.
- 삭제 실패는 같은 위치의 inline error로 보여주고 대상이 사라진 것처럼 처리하지 않습니다.
- outside-click으로 panel을 닫을 때 내부 click, text selection과 scroll interaction을 방해하지 않습니다.
- close와 browser history가 연결되어 있으면 화면을 먼저 닫고 history를 정리해 이전 content flash를 막습니다.
- 사용자가 마지막 UI 변경의 원복을 요청하면 관련 selector·markup만 되돌리고 다른 작업은 보존합니다.

### 4.11 Light·Dark theme과 시각 강조는 독립적으로 검증합니다

한 theme의 문제를 고칠 때 다른 theme의 정상 상태를 보존하는 경향이 강합니다.

- “Dark는 괜찮고 Light가 흐리다”면 Light 전용 contrast만 조정합니다.
- accent가 강하다는 지시에는 진한 fill보다 transparent background와 낮은 대비의 theme-aware border를 우선 검토합니다.
- 주변 icon과 color를 맞출 때 default뿐 아니라 hover·focus·selected·disabled 상태도 보존합니다.
- semantic token을 우선하고 Light·Dark hex를 component selector에 직접 중복하지 않습니다.
- background를 인접 work surface와 맞출 때 shared shell 전체가 아니라 요청된 body·pane 범위만 변경합니다.
- 색상만으로 selected, danger, success와 disabled 상태를 구분하지 않습니다.

### 4.12 문구·라벨은 확정된 표현을 모든 visible touchpoint에 일관되게 적용합니다

사용자가 정확한 한국어 명칭을 선택하거나 특정 문구 삭제를 지시하면 표현 자체가 제품 계약이 됩니다.

- 선택한 표기를 임의로 다듬거나 동의어로 바꾸지 않습니다.
- tab, title, empty state, status, tooltip과 관련 error에서 같은 개념은 같은 용어를 사용합니다.
- 삭제 요청을 받은 문구를 다른 위치로 옮기거나 더 긴 설명으로 대체하지 않습니다.
- label 변경만 필요한 경우 backend model·database 이름까지 불필요하게 rename하지 않습니다.
- 좁은 공간에서도 임의 축약보다 layout이나 tooltip 필요성을 먼저 검토합니다.
- 영문 실행 상태와 한국어 제품 명칭이 혼재할 때 현재 화면의 기존 convention을 따릅니다.

### 4.13 권한에 따라 보이지 않아야 할 GUI를 구분합니다

권한이 없는 사용자가 실패할 action을 먼저 본 뒤 오류를 경험하게 하지 않습니다.

- Marketplace의 View·Install·관리 action은 실제 access와 role에 맞춰 노출합니다.
- 관리자 전용 definition 관리와 일반 사용자의 설치·사용 흐름을 같은 화면 안에서도 명확히 role-gate합니다.
- 숨김 처리는 보안 자체가 아니므로 backend authorization을 반드시 유지합니다.
- 권한 변경 후 stale UI가 이전 action을 계속 보여주지 않도록 server state를 다시 반영합니다.
- 관리자와 일반 사용자 각각의 실제 화면을 별도로 검증합니다.
- empty state가 “항목 없음”인지 “권한 없음”인지 혼동되지 않게 합니다.

### 4.14 반응형·접근성은 국소 GUI 변경에도 유지합니다

요청이 desktop screenshot 한 장에서 시작되어도 기존 반응형과 접근성 계약을 깨뜨리지 않는 것이 기본입니다.

- 요청 영역의 desktop와 narrow breakpoint를 모두 확인합니다.
- text 확대 후 overflow, wrapping, ellipsis와 control overlap을 검사합니다.
- 시각 순서와 tab order, DOM reading order가 일치하는지 확인합니다.
- hover가 없는 touch 환경에서도 action을 발견하고 실행할 수 있어야 합니다.
- focus indicator를 hover 스타일과 함께 제거하지 않습니다.
- `aria-label`, `aria-expanded`, `role="status"`, `role="alert"`를 실제 의미에 맞게 유지합니다.
- `prefers-reduced-motion` 환경에서도 정보와 조작 가능성이 유지되어야 합니다.

### 4.15 GUI 검증은 실제 화면을 기준으로 단계적으로 수행합니다

GUI 변경의 기본 검증 순서는 다음과 같습니다.

1. 요청 문구·screenshot에서 target element, 기준 element와 보존 범위를 정합니다.
2. runtime component와 적용 CSS를 찾고, design reference 파일을 실제 app source로 오인하지 않습니다.
3. 기존 공용 primitive, token과 interaction precedent를 확인합니다.
4. 최소 범위로 markup·state·style을 수정합니다.
5. target unit test를 실행하고 typecheck와 build를 확인합니다.
6. 사용자의 runtime과 분리된 Frontend·Backend port와 browser context를 시작합니다.
7. 실제 URL에서 DOM, visible text와 computed style을 확인합니다.
8. default, hover, focus, open·closed, loading·success·error와 권한 상태 중 변경에 관련된 상태를 조작합니다.
9. desktop와 narrow viewport, Light와 Dark 중 영향을 받는 조합을 확인합니다.
10. console error, request failure, layout shift와 stale bundle 여부를 확인합니다.
11. 변경 영역이 잘 보이는 screenshot을 저장소 밖에 보관해 결과 보고에 첨부합니다.
12. 자신이 시작한 process tree와 browser context만 정리합니다.

source-level test가 통과했지만 browser를 열지 못했다면 “UI 검증 완료”가 아니라 “source·test 검증 완료, 실제 화면 미확인”으로 보고합니다.

### 4.16 GUI 완료 보고에 포함할 증거

GUI 작업의 최종 보고는 다음 내용을 짧게라도 구분합니다.

- **변경 결과:** 어느 화면의 무엇이 어떻게 달라졌는지
- **동작 검증:** click, state transition, 저장·복원 또는 role별 표시가 실제로 어떻게 확인되었는지
- **시각 검증:** viewport, theme와 computed value 중 무엇을 확인했는지
- **회귀 검증:** 실행한 target test, typecheck와 build
- **screenshot:** 개선된 영역을 직접 보여주는 이미지
- **미검증 범위:** browser timeout, 외부 dependency 부재 등으로 확인하지 못한 상태
- **환경 보호:** 격리 port·DB·browser를 사용했고 사용자 runtime을 건드리지 않았는지

### 4.17 반복적으로 드러난 디자인 취향

루미나에서 선호하는 디자인은 화려한 AI 제품이나 장식 중심 dashboard보다, 오래 사용해도 피로가 적은 **조용한 업무용 control system**에 가깝습니다. 시선을 끄는 것보다 정보의 위치와 현재 상태를 빠르게 이해하는 것이 우선입니다.

| 디자인 축 | 선호 경향 | 피하는 방향 |
|---|---|---|
| 전체 인상 | 명료하고 절제된 업무 화면 | 장식이 업무보다 앞서는 AI showcase |
| 화면 밀도 | compact하지만 읽을 수 있는 밀도 | 거대한 제목·과도한 여백 또는 지나치게 작은 글자 |
| 구조 | 연결된 row, divider와 tonal layer | 모든 항목을 둥근 card로 중첩 |
| 표면 | flat한 surface와 얇은 1px line | 떠 있지 않은 section의 강한 shadow |
| 강조색 | cobalt 한 가지를 선택·주 action에 제한 | 여러 accent, 넓은 cobalt 면과 포화된 highlight |
| 색상 역할 | neutral 중심, semantic state에만 색 사용 | 의미 없는 색 변화와 장식용 gradient |
| 모서리 | 작고 일관된 radius, layer별 차등 | 화면마다 다른 과도한 roundness |
| typography | 작은 scale 안에서 weight·contrast로 hierarchy | display font, 과한 대문자·letter spacing과 장식 서체 |
| motion | 상태 이해에 필요한 짧고 조용한 전환 | blinking, theatrical typing과 layout animation |
| feedback | control과 content 자리의 inline feedback | 일반 동작마다 뜨는 toast·modal |
| interaction | 직접 조작, 넓고 명확한 hit target | 숨은 gesture와 작은 icon에만 의존 |
| theme | 같은 semantic system의 Light·Dark 표현 | theme마다 별도 component 규칙 |

#### 업무가 장식보다 먼저 보여야 합니다

- 화면을 열었을 때 현재 선택, 실행 상태, 결과와 다음 action이 먼저 읽혀야 합니다.
- hero banner, gradient title, glassmorphism과 장식용 illustration을 기본 해법으로 사용하지 않습니다.
- 중요한 영역을 강조할 때 크기를 무조건 키우기보다 위치, weight, contrast와 여백을 조정합니다.
- AI 제품처럼 보이기 위한 blinking, glow, rainbow gradient와 과장된 animation을 추가하지 않습니다.
- brand는 wordmark와 제한된 cobalt accent로 유지하고 작업 content를 압도하지 않습니다.

#### compact하되 가독성을 희생하지 않습니다

- 기본 화면은 많은 업무 정보를 한눈에 비교할 수 있도록 비교적 촘촘하게 구성합니다.
- compact는 text를 작게 만드는 뜻보다 불필요한 card padding·반복 label·빈 공간을 줄이는 뜻입니다.
- pane에 충분한 공간이 있으면 metadata scale을 본문에 사용하지 않고 읽기 쉬운 body scale을 적용합니다.
- headline, title, body와 label의 차이는 큰 크기 점프보다 weight와 color hierarchy로 만듭니다.
- 긴 content는 읽기 폭을 제한하되 table, tree와 timeline은 비교 가능성을 위해 필요한 가로 공간을 사용합니다.

#### flat surface와 얇은 구조선을 선호합니다

- canvas, work surface와 quiet surface의 미세한 tone 차이로 계층을 만듭니다.
- 일반 section, form group과 list row에는 shadow를 사용하지 않습니다.
- shadow는 menu, tooltip, popover와 dialog처럼 실제 DOM 흐름 위에 뜨는 layer에만 낮게 사용합니다.
- 업무 목록은 divider로 연결된 row를 기본으로 하고 모든 row를 독립 card로 포장하지 않습니다.
- border는 낮은 대비의 1px line을 사용하며 colored side stripe와 border 중첩을 피합니다.
- body 배경을 맞추라는 요청은 shell 전체 redesign보다 해당 work surface를 인접 surface와 이어 보이게 만드는 방향입니다.

#### cobalt는 희소한 operational accent입니다

- cobalt는 primary action, 현재 selection, focus와 중요한 link에 사용합니다.
- 한 화면에서 cobalt 면적이 커져 장식 배경처럼 보이지 않게 합니다.
- 선택되지 않은 secondary action과 일반 icon은 neutral ink·muted 계열을 사용합니다.
- accent가 강하다는 피드백에는 cobalt fill을 더 연하게 만드는 것보다 transparent background와 subtle border를 우선합니다.
- success, warning과 danger를 cobalt로 대체하지 않고 각각의 semantic color를 사용합니다.
- Dark theme의 primary action은 밝은 cobalt 단색 면보다 cobalt wash와 text의 조용한 대비를 선호합니다.

#### 모서리와 geometry는 작고 일관되어야 합니다

- 일반 button·input은 비교적 작은 radius와 고정된 control height를 사용합니다.
- select trigger, option과 floating menu는 layer 역할에 맞는 공용 radius를 사용합니다.
- pill은 status·selected chip처럼 의미가 있는 경우에 제한합니다.
- state가 `default`, `loading`, `installed`, `delete confirmation`으로 바뀌어도 control width·height·padding과 icon slot이 움직이지 않게 합니다.
- 같은 종류의 button, input, menu와 row가 화면마다 다른 geometry를 갖지 않게 합니다.

#### typography는 안정적인 한국어 업무 화면을 지향합니다

- Pretendard·Noto Sans KR·Segoe UI 계열의 읽기 쉬운 sans-serif를 기본으로 합니다.
- headline도 과도하게 키우지 않고 좁은 scale 안에서 weight를 높여 hierarchy를 만듭니다.
- metadata를 10px 이하로 지나치게 줄이지 않습니다.
- 숫자, 비용, token과 duration은 비교하기 쉽게 자릿수 구분과 column alignment를 적용합니다.
- 한국어와 영문·숫자가 같은 row에 있을 때 baseline과 line-height의 안정성을 확인합니다.
- 사용자가 지정한 정확한 한글 label과 띄어쓰기를 시각 디자인의 일부로 취급합니다.

#### interaction feedback은 한 단계만 명확하게 변합니다

- hover는 quiet surface 또는 한 단계 진한 text·border 정도로 절제합니다.
- selected state는 cobalt wash, text와 필요 시 check icon을 함께 사용합니다.
- focus는 명확한 2px 계열 indicator를 유지하되 강한 glow나 흰 aura를 만들지 않습니다.
- disabled는 geometry를 유지하고 opacity·muted color로 표현하며 value를 읽을 수 있어야 합니다.
- loading은 같은 자리의 icon 또는 spinner로 표현하고 label·button 폭의 흔들림을 막습니다.
- 위험 action도 기본 상태부터 진한 빨간 fill로 과장하지 않고 danger text·border를 단계적으로 사용합니다.

#### routine feedback은 inline, 예외만 overlay로 처리합니다

- 저장, 생성, 이동, 복사, 다운로드, 읽음과 삭제처럼 사용자가 방금 실행한 일반 action은 갱신된 화면과 button 상태로 결과를 보여줍니다.
- 성공할 때마다 우측 하단 toast를 띄우지 않습니다.
- 실패, 연결 끊김과 재시도 필요 상태는 해당 control 또는 content 가까이에 inline으로 표시합니다.
- 일부 실패가 섞인 일괄 처리, 대상 소실과 다시 보기 어려운 중요한 결과에만 별도 toast를 고려합니다.
- warning·error는 연한 danger surface, 1px danger border와 명확한 text를 사용하고 진한 빨간 단색 면을 피합니다.

#### “마지막으로 본 정상 화면”을 안정감의 기준으로 삼습니다

- 이미 방문한 목록·상세 화면은 마지막 성공 content를 즉시 보여주고 background에서 재검증합니다.
- filter나 Project 범위가 다르면 cache를 분리해 다른 맥락의 content를 보여주지 않습니다.
- 최신 response를 기다리는 동안 count, row와 scroll position이 불필요하게 요동하지 않게 합니다.
- 재검증이 실패해도 마지막 정상 content는 유지하고 오류만 inline으로 알립니다.
- skeleton과 full-page loading은 실제로 표시할 이전 content가 없는 최초 진입에 제한합니다.

### 4.18 디자인 선택 시 우선순위

동일한 기능을 여러 방식으로 표현할 수 있을 때는 다음 순서로 선택합니다.

1. 사용자가 지목한 정확한 위치·크기·문구와 화면 기준
2. 현재 action, state, permission과 결과가 가장 빨리 이해되는 표현
3. `DESIGN.md`의 기존 semantic token과 공용 primitive
4. 주변 component와의 geometry·typography·surface 일관성
5. Light·Dark, desktop·narrow와 keyboard 사용에서의 안정성
6. 적은 장식, 적은 motion과 낮은 notification noise
7. 최소 DOM·CSS 변경으로 기존 동작을 보존하는 구현

새로운 디자인이 더 세련돼 보이더라도 위 우선순위를 깨뜨린다면 루미나의 기본 취향과 맞지 않습니다.

## 5. 지시문에서 반복되는 구조

사용자의 지시는 보통 다음 다섯 요소 중 여러 개를 조합합니다.

| 요소 | 의미 | 구현자가 확인할 질문 |
|---|---|---|
| 대상 | 바꿀 화면·기능·데이터 | 정확히 어느 component, API, row 또는 문구인가? |
| 기대 결과 | 눈에 보이거나 저장되는 최종 상태 | 사용자는 무엇을 보면 완료라고 판단하는가? |
| 금지 대안 | 허용하지 않는 해석·UI·우회 | popup, scroll-only, 별도 sheet, 추가 문구처럼 피해야 할 것은 무엇인가? |
| 범위 경계 | 유지해야 하는 주변 동작 | theme, hover, 다른 알림, 관련 없는 파일 중 무엇을 그대로 둬야 하는가? |
| 증거 | 완료를 입증하는 방법 | test, live API, DB, browser, computed value, screenshot 중 무엇이 필요한가? |

이를 실무형 문장으로 바꾸면 다음과 같습니다.

> **[대상]**을 **[정확한 기대 결과]**가 되도록 바꾸되, **[금지 대안]**은 사용하지 않고 **[보존 범위]**는 유지하며, **[실제 증거]**로 확인합니다.

요청이 짧더라도 구현 전 이 구조를 내부적으로 복원하면 과도한 해석과 미완료 보고를 줄일 수 있습니다.

## 6. 모호할 때 적용할 우선순위

1. 가장 최근에 사용자가 명시한 범위와 정확한 표현을 우선합니다.
2. 실제 사용자 경험과 저장된 backend 상태가 일치하는 해석을 선택합니다.
3. 기존 공용 component와 제품 계약을 보존하는 가장 작은 변경을 선택합니다.
4. 보안·권한·격리·재현성 불변 조건을 UI 편의보다 우선합니다.
5. source 추정보다 live contract, DB와 browser evidence를 우선합니다.
6. 문서와 구현이 충돌하면 차이와 영향을 알리고 임의로 둘을 같다고 가정하지 않습니다.
7. 요청 범위를 바꾸는 선택이 필요하면 추측으로 확대하지 않고 사용자에게 확인합니다.

## 7. 작업 유형별 기본 완료 조건

### 7.1 좁은 UI 수정

- 요청한 요소와 인접 기준의 live computed style을 확인합니다.
- 변경을 해당 component·selector에 한정합니다.
- hover, focus, click target과 반응형 상태를 확인합니다.
- target test, typecheck, build와 격리 browser 검증을 수행합니다.
- 개선 영역 screenshot을 남깁니다.

### 7.2 기능·설정·상태 수정

- 실제 저장 source와 scope를 확인합니다.
- API schema, permission, revision과 invalid fallback을 확인합니다.
- UI state와 backend state가 같은 생명주기를 표현하는지 검증합니다.
- stale runtime 가능성을 served contract와 process에서 배제합니다.

### 7.3 버그 진단과 수정

- 재현 화면이나 오류 문자열을 정확히 확보합니다.
- 실제 DB row, log, route, schema와 실행 경로를 먼저 확인합니다.
- 증상만 가리는 UI workaround 대신 원인 계층을 수정합니다.
- 회귀 test와 실제 재현 경로 양쪽에서 해결을 확인합니다.

### 7.4 문서·설계 작업

- 현재 기준 문서와 관련 section을 먼저 찾습니다.
- 요구사항, 현재 구현과 후속 Target을 구분합니다.
- 중복 내용을 복사하지 않고 기존 계약에 통합합니다.
- 링크, heading 구조, 용어와 Markdown 형식을 검사합니다.
- 문서 작업을 구현 완료 증거로 표현하지 않습니다.

### 7.5 산출물·내보내기 작업

- 사용 목적에 맞는 전달 경로를 선택합니다.
- 사용자가 분석할 단위에 맞춰 sheet, row와 column 구조를 설계합니다.
- 실제 생성 파일을 다시 열어 내용과 구조를 검사합니다.
- filename, browser download와 server canonical storage의 경계를 명확히 합니다.

## 8. 반복적으로 피해야 하는 실패 패턴

- 클릭 event만 붙이고 실제 state는 바꾸지 않는 구현
- 수정한 source만 보고 사용자가 보는 runtime도 갱신되었다고 가정하는 판단
- 정확한 UI 요청을 주변 화면 redesign으로 확대하는 변경
- 요청한 문구를 유사어, 설명 문구나 새로운 상태로 대체하는 처리
- 문서에 적혀 있다는 이유로 기능을 구현 완료로 분류하는 보고
- health check만 통과하면 최신 API contract라고 판단하는 진단
- repository file만 정리하고 DB·catalog·runtime row를 남기는 cleanup
- UI test만 통과하고 실제 browser 화면을 확인하지 않는 완료 선언
- 검증 도구의 timeout을 제품 실패 또는 성공으로 오해하는 보고
- 사용자의 process, port, browser와 dirty worktree를 정리 대상으로 취급하는 작업
- 작은 되돌리기 요청에 파일 전체 복원이나 관련 없는 변경 제거를 사용하는 방식
- 외부 사례를 현재 루미나 설계와 대조하지 않고 기능 목록으로 추가하는 문서화

## 9. 최종 자체 점검 질문

작업을 끝내기 전에 다음 질문에 모두 답할 수 있어야 합니다.

1. 요청한 정확한 대상과 최신 범위를 지켰습니까?
2. 비슷해 보이는 결과가 아니라 실제 상태와 동작을 바꿨습니까?
3. 기존 공용 component, 제품 언어와 권한 경계를 보존했습니까?
4. source와 사용자가 보는 runtime이 같다는 것을 확인했습니까?
5. 사용자에게 보이는 값·위치·문구·순서를 실제 화면에서 확인했습니까?
6. 관련 test, typecheck, build, DB·API·browser 검증 중 필요한 항목을 수행했습니까?
7. 검증하지 못했거나 skip된 범위를 완료로 과장하지 않았습니까?
8. 다른 작업, Secret, runtime data와 사용자 환경을 건드리지 않았습니까?
9. 문서 변경이라면 현재 구현과 목표 계약을 구분했습니까?
10. 최종 보고만 읽어도 변경 결과와 검증 증거를 알 수 있습니까?

---
name: Lumina Agent
description: 절제된 밀도와 명확한 상태 표현으로 업무 흐름을 지키는 사내 Agent UI
colors:
  canvas: "oklch(98.5% 0.002 255)"
  chat-canvas: "#ffffff"
  menu-surface: "oklch(97.2% 0.002 255)"
  surface: "#ffffff"
  surface-soft: "#f5f6f7"
  surface-selected: "#edf2fb"
  line: "#e0e3e7"
  line-strong: "#d4d8de"
  ink: "#20242c"
  muted: "#6c737e"
  faint: "#9ba2ad"
  cobalt: "#3f66c9"
  cobalt-hover: "#3158b8"
  cobalt-pale: "#edf2fb"
  success: "#2f9765"
  warning: "#b8771f"
  danger: "#c34f51"
  dark-canvas: "#17191d"
  dark-menu-surface: "#121417"
  dark-surface: "#1d2025"
  dark-surface-soft: "#20242a"
  dark-surface-selected: "#26334e"
  dark-line: "#2b3038"
  dark-line-strong: "#3a404a"
  dark-ink: "#edf0f4"
  dark-muted: "#9fa7b2"
  dark-faint: "#737c88"
  dark-cobalt: "#7e9ce5"
  dark-cobalt-hover: "#6f91df"
  dark-cobalt-pale: "#26334d"
typography:
  headline:
    fontFamily: "Pretendard Variable, Pretendard, Noto Sans KR, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Pretendard Variable, Pretendard, Noto Sans KR, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 650
    lineHeight: 1.4
    letterSpacing: "normal"
  body:
    fontFamily: "Pretendard Variable, Pretendard, Noto Sans KR, Segoe UI, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "Pretendard Variable, Pretendard, Noto Sans KR, Segoe UI, sans-serif"
    fontSize: "11.5px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
rounded:
  xs: "3px"
  sm: "4px"
  control: "5px"
  option: "6px"
  field: "7px"
  select: "8px"
  menu: "10px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  xxl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.cobalt}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 9px"
    height: "30px"
  button-primary-dark:
    backgroundColor: "{colors.dark-cobalt-pale}"
    textColor: "{colors.dark-cobalt}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 9px"
    height: "30px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 9px"
    height: "30px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 9px"
    height: "32px"
  select-trigger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.select}"
    padding: "0 9px"
    height: "32px"
  select-menu:
    backgroundColor: "{colors.menu-surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.menu}"
    padding: "4px"
  chip-selected:
    backgroundColor: "{colors.cobalt-pale}"
    textColor: "{colors.cobalt}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 8px"
    height: "25px"
---

# Design System: Lumina Agent

## Overview

**Creative North Star: "조용한 컨트롤 데스크"**

Lumina는 사용자가 여러 Project와 장시간 Agent Run을 오가면서도 현재 상태와 다음 행동을 즉시 이해하는 업무 도구입니다. 화면은 장식보다 정보 밀도와 조작 예측 가능성을 우선하며, 얇은 구분선과 톤 차이로 구조를 만들고 코발트 색은 선택, 주 동작, 진행 상태에만 제한적으로 사용합니다.

Light와 Dark는 별도 디자인이 아니라 같은 semantic token의 두 표현입니다. 같은 역할의 버튼, 입력, List of Value, 목록 행은 화면마다 다시 만들지 않습니다. 공용 토큰과 공용 컴포넌트를 먼저 사용하고, 새 시각 값이 정말 필요할 때만 의미가 드러나는 token을 추가합니다.

**Key Characteristics:**

- 절제된 단일 accent와 차갑게 tint된 neutral
- 촘촘하지만 읽기 순서가 분명한 업무 밀도
- 얇은 border와 tonal layering을 중심으로 한 평평한 표면
- 권한, 선택, 실행 상태를 숨기지 않는 일관된 상태 표현
- Light와 Dark에서 같은 의미와 같은 component geometry 유지

**The Shared Primitive Rule.** 같은 의미와 크기의 UI는 반드시 같은 primitive와 semantic variant를 사용합니다. 화면 selector에 button, input, menu 스타일을 다시 선언하는 것은 금지합니다.

**The Token Before Value Rule.** 반복되는 color, radius, spacing, height, shadow, motion 값은 CSS custom property가 먼저입니다. 컴포넌트에 숫자나 색을 직접 추가하지 않습니다.

## Colors

Lumina의 palette는 cobalt 한 가지 accent와 차갑게 tint된 neutral surface로 구성됩니다. 색은 장식이 아니라 선택, 상태, 위험과 정보 계층을 전달합니다.

### Primary

- **Operational Cobalt:** 주 동작, 현재 선택, focus border, 링크와 active indicator에만 사용합니다.
- **Cobalt Wash:** Dark primary action, 선택된 row, 선택된 option과 조용한 status badge의 배경입니다.

### Secondary

- **Success Green:** 저장 완료와 성공 상태에만 사용합니다.
- **Warning Amber:** 주의가 필요하지만 아직 실패하지 않은 상태에만 사용합니다.
- **Danger Red:** 삭제, 거부, 실패와 되돌리기 어려운 동작에만 사용합니다.

### Neutral

- **Cool Canvas:** 앱의 최하위 배경입니다. content surface와 같은 색으로 합치지 않습니다.
- **Work Surface:** input, toolbar, editor와 content pane의 기본 표면입니다.
- **Quiet Surface:** hover, secondary section, inactive selection과 목록 보조 배경입니다.
- **Structural Line:** border와 divider에 사용합니다. box를 장식하기 위한 선으로 사용하지 않습니다.
- **Operational Ink:** 제목과 본문에 사용합니다. muted와 faint는 보조 설명, placeholder, 비활성 정보 순서로만 낮춥니다.

**The One Accent Rule.** 한 화면에서 cobalt는 전체 면적의 10% 이하를 유지합니다. 선택과 주 동작이 아닌 장식용 cobalt 면은 금지합니다.

**The Semantic Theme Rule.** component selector에 Light 또는 Dark 전용 hex를 직접 넣지 않습니다. semantic token을 theme root에서 교체합니다.

## Typography

**Display Font:** 사용하지 않음
**Body Font:** Pretendard Variable, Pretendard, Noto Sans KR, Segoe UI, sans-serif
**Label/Mono Font:** UI와 동일한 family를 사용하며, code surface도 제품의 전역 UI font 정책을 따릅니다.

**Character:** 한글과 영문이 섞인 사내 업무 화면에서 안정적인 폭과 명확한 숫자 판독을 우선합니다. 별도의 장식 서체 없이 scale, weight, color만으로 계층을 만듭니다.

### Hierarchy

- **Headline** (700, 14px, 1.3): feature header와 주요 panel 제목입니다.
- **Title** (650, 13px, 1.4): section 제목, row identity와 card heading입니다.
- **Body** (400, 12.5px, 1.55): 설명, form value와 dense content입니다. 긴 설명은 65에서 75ch 안으로 제한합니다.
- **Label** (500, 11.5px, 1.4): field label, button, metadata와 compact control입니다. 10px 이하는 보조 metadata 외에는 금지합니다.

**The Weight Before Decoration Rule.** hierarchy는 font size와 weight로 해결합니다. gradient text, 과한 letter spacing, 장식용 대문자화는 금지합니다.

## Elevation

Lumina는 flat by default입니다. 일반 section과 row는 surface tone과 1px border로 분리하며 shadow를 사용하지 않습니다. Shadow는 DOM 흐름 위에 실제로 떠 있는 menu, tooltip, dialog와 popover에만 허용합니다.

### Shadow Vocabulary

- **Overlay:** dropdown, List of Value와 popover에 사용하는 넓고 낮은 2단 shadow입니다. Dark theme에서는 반드시 검정 계열 shadow token을 사용하며 밝은 ink에서 shadow를 계산하지 않습니다.
- **Tooltip:** 작은 설명 layer 전용의 짧은 ambient shadow입니다.

**The Dark Shadow Rule.** Dark theme shadow를 text token에서 만들지 않습니다. 흰 아우라가 생기면 색이 아니라 shadow source가 잘못된 것입니다.

**The Flat By Default Rule.** 문서 흐름 안의 card, list row와 form group에 shadow를 추가하지 않습니다. 떠 있지 않은 것은 띄우지 않습니다.

## Components

### Buttons

- **Shape:** 기본 control은 작은 곡률(5px), icon-only navigation은 중간 곡률(7px에서 9px), pill은 999px입니다.
- **Primary:** cobalt background를 쓰며 Dark theme에서는 cobalt wash와 cobalt text로 조용하게 반전합니다. 같은 주 동작은 어느 화면에서도 같은 semantic variant를 사용합니다.
- **Hover / Focus:** hover는 cobalt-hover 또는 surface-soft로 한 단계만 이동합니다. keyboard focus는 2px cobalt 계열 indicator를 유지하되 밝은 흰 아우라로 보이면 안 됩니다.
- **Secondary / Ghost / Tertiary:** secondary는 surface와 line border, ghost는 transparent와 hover surface만 사용합니다. 삭제는 danger text를 쓰며 별도 과장된 red fill을 만들지 않습니다.
- **Disabled / Loading:** disabled는 geometry를 유지하고 opacity만 낮춥니다. loading은 같은 자리에서 icon을 spinner로 교체하며 label과 width를 유지합니다.

### Chips

- **Style:** status와 selected chip은 cobalt wash, cobalt text, 1px semantic border와 pill radius를 사용합니다.
- **State:** 색만으로 의미를 전달하지 않고 label 또는 icon을 함께 둡니다. 단순 metadata를 모두 chip으로 만들지 않습니다.

### Cards / Containers

- **Corner Style:** 독립 panel은 7px, floating menu는 10px입니다. list row는 기본적으로 radius 없이 divider로 연결합니다.
- **Background:** canvas, surface, surface-soft의 3단 tonal layer 안에서만 조합합니다.
- **Shadow Strategy:** 흐름 안의 container는 shadow 금지, floating layer만 Elevation 규칙을 따릅니다.
- **Border:** 1px line을 사용합니다. colored side stripe와 중첩 card border는 금지합니다.
- **Internal Padding:** compact 8px, standard 12px에서 16px, large content 20px에서 24px scale을 사용합니다.

### Inputs / Fields

- **Style:** 기본 높이는 32px, border는 line, radius는 5px, background는 surface입니다. compact control은 29px입니다.
- **Focus:** cobalt border로 상태를 표시합니다. glow는 form hierarchy를 덮지 않는 낮은 opacity일 때만 허용합니다.
- **Error / Disabled:** error는 danger border와 같은 위치의 안내 문구를 함께 표시합니다. disabled는 opacity를 낮추되 value를 읽을 수 있어야 합니다.

### Navigation

- **Style:** selected item은 cobalt wash와 cobalt text 또는 ink를 사용합니다. icon과 label은 같은 row에 정렬하고 hover는 quiet surface 한 단계만 사용합니다.
- **Responsive:** sidebar와 split pane은 breakpoint에서 구조적으로 접습니다. 글자 크기를 유동적으로 축소해 공간을 확보하지 않습니다.

### List of Value

- **Shape:** trigger는 8px, floating menu는 10px, option은 6px radius입니다. 각진 native popup처럼 보이는 구현은 금지합니다.
- **Behavior:** 공용 SelectMenu primitive를 사용하고 native select는 OS chrome이 제품 UI와 충돌하지 않는 예외 화면에서만 허용합니다.
- **State:** selected option은 cobalt wash와 check icon, hover와 keyboard focus는 quiet surface를 사용합니다. trigger open state는 cobalt border를 유지하되 box shadow와 흰 aura를 만들지 않습니다.
- **Alignment:** menu는 trigger width 이상이며 viewport edge에서 위쪽 또는 반대쪽으로 전환합니다.

### Lists

- **Style:** 업무 목록은 divider 기반의 연결된 row를 기본으로 합니다. 모든 row를 rounded card로 포장하지 않습니다.
- **Identity:** leading icon 또는 avatar, primary label, secondary metadata, trailing action 순서를 유지합니다.
- **Interaction:** row 전체 선택과 row action을 구분하며 hover, selected, disabled 상태가 서로 다른 semantic token을 사용합니다.

### Tooltips and Scrollbars

- **Tooltip:** 모든 tooltip은 body portal의 공용 layer를 사용합니다. browser title과 clipping container 내부 pseudo-element는 금지합니다.
- **Scrollbar:** 모든 사용자 노출 scroll surface는 공용 thin scrollbar를 사용합니다. Track은 투명하게 유지하고 thumb는 accent 색이 아닌 `ink` 기반의 중성 회색으로 계산합니다. 기본 상태는 11% 강도로 은은하게 보이며, 스크롤 조작 중에는 30%로 선명해지고 마지막 조작 650ms 후 520ms 동안 서서히 흐려집니다. Light와 Dark, Artifact Library, 채팅, Marketplace, 파일 Workspace, 예약 작업, 설정, popover와 선택 메뉴에 같은 token과 idle-fade 동작을 적용하며 화면별 색상 예외를 만들지 않습니다.

## Do's and Don'ts

### Do:

- **Do** 먼저 기존 공용 primitive와 semantic variant를 찾고, 없을 때만 새 component API를 추가합니다.
- **Do** radius, control height, spacing, shadow와 motion을 CSS custom property로 정의한 뒤 사용합니다.
- **Do** 주 버튼은 하나의 공용 primary action style로 관리하고 Light와 Dark 변형은 theme token으로 해결합니다.
- **Do** List of Value는 8px trigger, 10px menu, 6px option의 공용 rounded geometry를 사용합니다.
- **Do** DOM과 computed style로 Light, Dark, open, hover, keyboard focus, disabled와 loading 상태를 확인합니다.
- **Do** 권한, 공유 범위와 실행 상태를 label, icon, color 중 둘 이상으로 명확히 표시합니다.

### Don't:

- **Don't** 장식이 업무보다 앞서는 대시보드를 만들지 않습니다.
- **Don't** 서로 다른 컴포넌트 규칙이 섞인 화면을 만들지 않습니다.
- **Don't** 브라우저 기본 컨트롤이 제품 UI와 어색하게 충돌하게 두지 않습니다.
- **Don't** 과도한 카드 중첩을 만들지 않습니다.
- **Don't** 의미 없는 모션과 색상을 추가하지 않습니다.
- **Don't** 중요한 실행·권한 상태를 모호하게 감추지 않습니다.
- **Don't** 같은 버튼, input, menu, list row의 geometry와 state를 화면 selector마다 하드코딩하지 않습니다.
- **Don't** Dark theme shadow를 밝은 text 또는 ink token으로 계산해 흰 아우라를 만들지 않습니다.
- **Don't** gradient text, decorative glassmorphism, colored side stripe와 layout property animation을 사용하지 않습니다.

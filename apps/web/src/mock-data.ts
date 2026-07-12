export type ToolCallStatus = "complete" | "running" | "waiting" | "warning";

export type ToolCall = {
  id: string;
  label: string;
  tool: string;
  duration: string;
  status: ToolCallStatus;
  request: string[];
  result: string[];
};

export type ToolGroup = {
  id: string;
  label: string;
  summary: string;
  status: ToolCallStatus;
  calls: ToolCall[];
};

export const sessions = [
  { id: "inspection", title: "2분기 설비 점검 보고서", status: "running", time: "방금" },
  { id: "energy", title: "에너지 비용 절감 방안 검토", status: "complete", time: "1시간" },
  { id: "bottleneck", title: "생산 라인 병목 분석", status: "complete", time: "어제" },
  { id: "failure", title: "고장 유형 분석 리포트", status: "waiting", time: "어제" },
  { id: "forecast", title: "예지 정비 모델 성능 평가", status: "complete", time: "2일" },
  { id: "safety", title: "안전 점검 체크리스트 자동화", status: "complete", time: "3일" },
  { id: "parts", title: "부품 교체 주기 최적화", status: "complete", time: "4일" },
];

export const progressSteps = [
  { id: "context", label: "자료와 요구사항 확인", status: "complete" as const },
  { id: "analysis", label: "점검 자료 분석", status: "complete" as const },
  { id: "draft", label: "보고서 구조와 화면 제작", status: "running" as const },
  { id: "review", label: "결과 검토 및 전달", status: "waiting" as const },
];

export const toolGroups: ToolGroup[] = [
  {
    id: "read-materials",
    label: "첨부 자료를 읽고 정리했습니다",
    summary: "도구 4회 · 18초 · 완료",
    status: "complete",
    calls: [
      {
        id: "read-gwangyang",
        label: "설비점검_광양.md 읽기",
        tool: "read_file",
        duration: "2.1초",
        status: "complete",
        request: ["파일  설비점검_광양.md", "인코딩  UTF-8"],
        result: ["126.4KB · 4,321자 확인", "반복 정지 이력 12건 추출"],
      },
      {
        id: "read-pohang",
        label: "설비점검_포항.md 읽기",
        tool: "read_file",
        duration: "1.8초",
        status: "complete",
        request: ["파일  설비점검_포항.md", "인코딩  UTF-8"],
        result: ["98.7KB · 3,806자 확인", "조치 완료 기준 5개 추출"],
      },
      {
        id: "read-actions",
        label: "조치현황.xlsx 분석",
        tool: "read_spreadsheet",
        duration: "4.2초",
        status: "complete",
        request: ["파일  조치현황.xlsx", "시트  2분기", "범위  전체 데이터"],
        result: ["3,842행 · 12개 열 확인", "반복 이슈 7건 · 담당자 누락 3건", "결과가 Artifact 미리보기에 연결되었습니다."],
      },
      {
        id: "read-notes",
        label: "회의메모.md 읽기",
        tool: "read_file",
        duration: "1.4초",
        status: "complete",
        request: ["파일  회의메모.md", "최근 회의 6건"],
        result: ["결정사항 9건 확인", "후속 Action Item 14건 추출"],
      },
    ],
  },
  {
    id: "build-report",
    label: "보고서 초안을 만들고 검증하고 있습니다",
    summary: "도구 2/3 · 31초 · 실행 중",
    status: "running",
    calls: [
      {
        id: "write-report",
        label: "report.html 초안 작성",
        tool: "write_file",
        duration: "12.7초",
        status: "complete",
        request: ["파일  artifacts/report.html", "형식  단일 HTML"],
        result: ["HTML, CSS, 표와 요약 차트를 생성했습니다.", "파일 크기  84.2KB"],
      },
      {
        id: "render-report",
        label: "보고서 화면 렌더링",
        tool: "browser_preview",
        duration: "18.3초",
        status: "running",
        request: ["대상  artifacts/report.html", "뷰포트  1440 × 900"],
        result: ["미리보기를 준비하고 있습니다."],
      },
      {
        id: "visual-review",
        label: "레이아웃과 내용 최종 확인",
        tool: "visual_review",
        duration: "대기",
        status: "waiting",
        request: ["검토 항목  표 잘림, 문구, 대비"],
        result: ["이전 도구가 끝나면 시작합니다."],
      },
    ],
  },
];

export const artifactHtml = `<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <title>2분기 설비 점검 종합 보고서</title>
    <style>
      body { font-family: system-ui; color: #20242c; margin: 48px; }
      header { border-bottom: 2px solid #3f66c9; padding-bottom: 24px; }
      table { width: 100%; border-collapse: collapse; margin-top: 24px; }
      th, td { border-bottom: 1px solid #dfe3e8; padding: 12px; text-align: left; }
      th { color: #646c78; font-size: 13px; }
    </style>
  </head>
  <body>
    <header>
      <p>설비기술팀 · 2026년 2분기</p>
      <h1>설비 점검 종합 보고서</h1>
      <p>반복 이슈와 후속 조치 현황을 기준으로 4개 자료를 통합했습니다.</p>
    </header>
    <main>
      <h2>핵심 요약</h2>
      <ul>
        <li>반복 이슈 7건 중 3건은 담당자 지정이 필요합니다.</li>
        <li>압연 라인의 윤활 계통 점검을 우선 권고합니다.</li>
      </ul>
    </main>
  </body>
</html>`;

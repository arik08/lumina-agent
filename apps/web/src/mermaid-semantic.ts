export type MermaidNodeTone = "neutral" | "input" | "decision" | "execution" | "success" | "danger";

const semanticTonePatterns: Array<[Exclude<MermaidNodeTone, "neutral">, RegExp]> = [
  ["danger", /(?:실패|오류|경고|위험|중단|거부|failure|error|warning|risk|reject(?:ed|ion)?|abort(?:ed)?)/i],
  ["success", /(?:완료|성공|종료|최종 결과|산출물|completed?|success|finished?|final result|deliverable|output)/i],
  ["decision", /(?:의사결정|논의|심의|승인|결정|이사회|경영진|\bceo\b|decision|approval|approve|governance|board review)/i],
  ["execution", /(?:실행|수행|시행|운영|배포|적용|구현|execute|execution|implement|deploy|operate|operation)/i],
  ["input", /(?:외부 입력|시장 변화|요청 접수|데이터 수집|정보 수집|input|request|intake|market change|data collection|trigger)/i],
];

export function inferMermaidNodeTone(label: string, isDecisionShape = false): MermaidNodeTone {
  const normalizedLabel = label.normalize("NFKC").replace(/\s+/g, " ").trim();
  for (const [tone, pattern] of semanticTonePatterns) {
    if (pattern.test(normalizedLabel)) return tone;
  }
  return isDecisionShape ? "decision" : "neutral";
}

export function userFacingSystemText(text: string) {
  const searchLabel = text.replace(/duckduckgo(?:_html)?/gi, "검색");
  if (searchLabel.startsWith("Provider가 빈 응답을 반환해")) {
    return "답변을 계속 준비하고 있습니다.";
  }
  if (searchLabel.startsWith("Provider가 내용 없는 응답을 반복해")) {
    return "답변을 준비하지 못했습니다.";
  }
  return searchLabel;
}

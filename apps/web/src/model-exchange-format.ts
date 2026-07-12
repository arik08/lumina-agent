export function formatModelExchangeValue(value: unknown) {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "(내용 없음)";

  const formatted = JSON.stringify(value, null, 2);
  if (!formatted) return "(내용 없음)";

  const lines = formatted.split("\n");
  if (lines.length < 3 || !["{", "["].includes(lines[0])) return formatted;

  const closingDelimiter = lines.at(-1);
  if (closingDelimiter !== "}" && closingDelimiter !== "]") return formatted;

  const firstContentLine = lines[1].trimStart();
  const lastContentLine = lines.at(-2);
  if (lastContentLine === undefined) return formatted;

  if (lines.length === 3) {
    return `${lines[0]} ${firstContentLine} ${closingDelimiter}`;
  }

  return [
    `${lines[0]} ${firstContentLine}`,
    ...lines.slice(2, -2),
    `${lastContentLine} ${closingDelimiter}`,
  ].join("\n");
}

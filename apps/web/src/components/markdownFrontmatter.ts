const markdownFrontmatterPattern = /^(\uFEFF?---[ \t]*)(\r?\n)([\s\S]*?)(\r?\n)(---[ \t]*)(?=\r?\n|$)/;

export function splitMarkdownFrontmatter(value: string) {
  const match = value.match(markdownFrontmatterPattern);
  if (!match) return null;

  const [, opening, openingBreak, yaml, closingBreak, closing] = match;
  return {
    opening,
    openingBreak,
    yaml,
    closingBreak,
    closing,
    body: value.slice(match[0].length),
  };
}

export function markdownBodyAfterFrontmatter(value: string) {
  return value.replace(/^(?:[ \t]*\r?\n)+/, "");
}

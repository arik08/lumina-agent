import { splitMarkdownFrontmatter } from "./markdownFrontmatter";

export type SyntaxHighlighter = typeof import("highlight.js/lib/common")["default"];

export function renderHighlightedHtml(hljs: SyntaxHighlighter, value: string, language: string) {
  if (language === "markdown") {
    const frontmatter = splitMarkdownFrontmatter(value);
    if (frontmatter) {
      const { opening, openingBreak, yaml, closingBreak, closing, body: markdown } = frontmatter;
      return `<span class="hljs-meta">${opening}</span>${openingBreak}${hljs.highlight(yaml, { language: "yaml", ignoreIllegals: true }).value}${closingBreak}<span class="hljs-meta">${closing}</span>${hljs.highlight(markdown, { language: "markdown", ignoreIllegals: true }).value}`;
    }
  }
  return hljs.getLanguage(language)
    ? hljs.highlight(value, { language, ignoreIllegals: true }).value
    : hljs.highlight(value, { language: "plaintext" }).value;
}

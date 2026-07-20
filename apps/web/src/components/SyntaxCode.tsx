import { useEffect, useRef, useState, type ChangeEvent, type CSSProperties, type UIEvent } from "react";
import { splitMarkdownFrontmatter } from "./markdownFrontmatter";

type Highlighter = typeof import("highlight.js/lib/common")["default"];

let highlighterPromise: Promise<Highlighter> | null = null;

function loadHighlighter() {
  highlighterPromise ??= import("highlight.js/lib/common").then((module) => module.default);
  return highlighterPromise;
}

const aliases: Record<string, string> = {
  cjs: "javascript", htm: "xml", html: "xml", js: "javascript", jsx: "javascript", md: "markdown", mjs: "javascript",
  py: "python", sh: "bash", shell: "bash", text: "plaintext", ts: "typescript", tsx: "typescript", yml: "yaml",
};

export function codeLanguage(fileName?: string | null, mimeType?: string | null, language?: string | null) {
  const requested = language?.toLowerCase();
  if (requested) return aliases[requested] ?? requested;
  const extension = fileName?.split(/[?#]/, 1)[0].split(".").at(-1)?.toLowerCase();
  if (extension) return aliases[extension] ?? extension;
  if (mimeType?.includes("json")) return "json";
  if (mimeType?.includes("html") || mimeType?.includes("xml")) return "xml";
  if (mimeType?.includes("markdown")) return "markdown";
  if (mimeType?.includes("javascript")) return "javascript";
  if (mimeType?.includes("typescript")) return "typescript";
  return "plaintext";
}

function highlightedHtml(hljs: Highlighter, value: string, language: string) {
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

function useHighlightedHtml(value: string, language: string) {
  const [result, setResult] = useState<{
    value: string;
    language: string;
    html: string;
  } | null>(null);
  useEffect(() => {
    let active = true;
    void loadHighlighter().then((hljs) => {
      if (active) {
        setResult({ value, language, html: highlightedHtml(hljs, value, language) });
      }
    });
    return () => {
      active = false;
    };
  }, [language, value]);
  return result?.value === value && result.language === language
    ? result.html
    : null;
}

export function SyntaxCode({ value, fileName, mimeType, language, className = "" }: {
  value: string;
  fileName?: string | null;
  mimeType?: string | null;
  language?: string | null;
  className?: string;
}) {
  const resolvedLanguage = codeLanguage(fileName, mimeType, language);
  const html = useHighlightedHtml(value, resolvedLanguage);
  return (
    <pre className={`syntax-code ${className}`.trim()}>
      {html === null
        ? <code className={`hljs language-${resolvedLanguage}`}>{value}</code>
        : <code className={`hljs language-${resolvedLanguage}`} dangerouslySetInnerHTML={{ __html: html }} />}
    </pre>
  );
}

export function SyntaxCodeContent({ value, language, className = "" }: { value: string; language?: string | null; className?: string }) {
  const resolvedLanguage = codeLanguage(null, null, language);
  const html = useHighlightedHtml(value, resolvedLanguage);
  return html === null
    ? <code className={`hljs language-${resolvedLanguage} ${className}`.trim()}>{value}</code>
    : <code className={`hljs language-${resolvedLanguage} ${className}`.trim()} dangerouslySetInnerHTML={{ __html: html }} />;
}

export function SyntaxTextarea({ value, onChange, fileName, mimeType, language, className = "", ariaLabel, disabled = false }: {
  value: string;
  onChange: (event: ChangeEvent<HTMLTextAreaElement>) => void;
  fileName?: string | null;
  mimeType?: string | null;
  language?: string | null;
  className?: string;
  ariaLabel: string;
  disabled?: boolean;
}) {
  const highlightRef = useRef<HTMLPreElement>(null);
  const resolvedLanguage = codeLanguage(fileName, mimeType, language);
  const highlightValue = `${value}\n`;
  const html = useHighlightedHtml(highlightValue, resolvedLanguage);
  const syncScroll = (event: UIEvent<HTMLTextAreaElement>) => {
    if (!highlightRef.current) return;
    highlightRef.current.scrollTop = event.currentTarget.scrollTop;
    highlightRef.current.scrollLeft = event.currentTarget.scrollLeft;
  };
  return (
    <div className={`syntax-editor ${className}`.trim()}>
      <pre ref={highlightRef} aria-hidden="true">
        {html === null
          ? <code className={`hljs language-${resolvedLanguage}`}>{highlightValue}</code>
          : <code className={`hljs language-${resolvedLanguage}`} dangerouslySetInnerHTML={{ __html: html }} />}
      </pre>
      <textarea aria-label={ariaLabel} disabled={disabled} spellCheck={false} value={value} onChange={onChange} onScroll={syncScroll} />
    </div>
  );
}

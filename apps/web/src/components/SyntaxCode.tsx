import hljs from "highlight.js/lib/common";
import { useMemo, useRef, type ChangeEvent, type CSSProperties, type UIEvent } from "react";

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

function highlightedHtml(value: string, language: string) {
  return hljs.getLanguage(language)
    ? hljs.highlight(value, { language, ignoreIllegals: true }).value
    : hljs.highlight(value, { language: "plaintext" }).value;
}

export function SyntaxCode({ value, fileName, mimeType, language, className = "" }: {
  value: string;
  fileName?: string | null;
  mimeType?: string | null;
  language?: string | null;
  className?: string;
}) {
  const resolvedLanguage = codeLanguage(fileName, mimeType, language);
  const html = useMemo(() => highlightedHtml(value, resolvedLanguage), [resolvedLanguage, value]);
  return <pre className={`syntax-code ${className}`.trim()}><code className={`hljs language-${resolvedLanguage}`} dangerouslySetInnerHTML={{ __html: html }} /></pre>;
}

export function SyntaxCodeContent({ value, language, className = "" }: { value: string; language?: string | null; className?: string }) {
  const resolvedLanguage = codeLanguage(null, null, language);
  const html = useMemo(() => highlightedHtml(value, resolvedLanguage), [resolvedLanguage, value]);
  return <code className={`hljs language-${resolvedLanguage} ${className}`.trim()} dangerouslySetInnerHTML={{ __html: html }} />;
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
  const html = useMemo(() => highlightedHtml(`${value}\n`, resolvedLanguage), [resolvedLanguage, value]);
  const syncScroll = (event: UIEvent<HTMLTextAreaElement>) => {
    if (!highlightRef.current) return;
    highlightRef.current.scrollTop = event.currentTarget.scrollTop;
    highlightRef.current.scrollLeft = event.currentTarget.scrollLeft;
  };
  return (
    <div className={`syntax-editor ${className}`.trim()}>
      <pre ref={highlightRef} aria-hidden="true"><code className={`hljs language-${resolvedLanguage}`} dangerouslySetInnerHTML={{ __html: html }} /></pre>
      <textarea aria-label={ariaLabel} disabled={disabled} spellCheck={false} value={value} onChange={onChange} onScroll={syncScroll} />
    </div>
  );
}

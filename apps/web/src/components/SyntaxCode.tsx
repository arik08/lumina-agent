import { useDeferredValue, useEffect, useRef, useState, type ChangeEvent, type CSSProperties, type UIEvent } from "react";
import { requestSyntaxHighlight } from "./syntax-highlight-client";
import { useNearViewport } from "../use-near-viewport";

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

function useHighlightedHtml(value: string, language: string, enabled = true) {
  const [result, setResult] = useState<{
    value: string;
    language: string;
    html: string;
  } | null>(null);
  const mountedRef = useRef(true);
  const runningRef = useRef(false);
  const queuedRef = useRef<{ value: string; language: string } | null>(null);
  const latestRef = useRef({ value, language });
  const pumpRef = useRef<() => void>(() => undefined);
  latestRef.current = { value, language };
  pumpRef.current = () => {
    if (runningRef.current || !queuedRef.current) return;
    const job = queuedRef.current;
    queuedRef.current = null;
    runningRef.current = true;
    void requestSyntaxHighlight(job.value, job.language)
      .then((html) => {
        if (
          mountedRef.current
          && latestRef.current.value === job.value
          && latestRef.current.language === job.language
        ) setResult({ ...job, html });
      })
      .catch(() => undefined)
      .finally(() => {
        runningRef.current = false;
        pumpRef.current();
      });
  };
  useEffect(() => {
    if (!enabled) {
      queuedRef.current = null;
      return;
    }
    queuedRef.current = { value, language };
    pumpRef.current();
  }, [enabled, language, value]);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      queuedRef.current = null;
    };
  }, []);
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
  const containerRef = useRef<HTMLPreElement>(null);
  const nearViewport = useNearViewport(containerRef);
  const resolvedLanguage = codeLanguage(fileName, mimeType, language);
  const html = useHighlightedHtml(value, resolvedLanguage, nearViewport);
  return (
    <pre ref={containerRef} className={`syntax-code ${className}`.trim()}>
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
  const displayValue = `${value}\n`;
  const highlightValue = useDeferredValue(displayValue);
  const html = useHighlightedHtml(highlightValue, resolvedLanguage);
  const visibleHtml = highlightValue === displayValue ? html : null;
  const syncScroll = (event: UIEvent<HTMLTextAreaElement>) => {
    if (!highlightRef.current) return;
    highlightRef.current.scrollTop = event.currentTarget.scrollTop;
    highlightRef.current.scrollLeft = event.currentTarget.scrollLeft;
  };
  return (
    <div className={`syntax-editor ${className}`.trim()}>
      <pre ref={highlightRef} aria-hidden="true">
        {visibleHtml === null
          ? <code className={`hljs language-${resolvedLanguage}`}>{displayValue}</code>
          : <code className={`hljs language-${resolvedLanguage}`} dangerouslySetInnerHTML={{ __html: visibleHtml }} />}
      </pre>
      <textarea aria-label={ariaLabel} disabled={disabled} spellCheck={false} value={value} onChange={onChange} onScroll={syncScroll} />
    </div>
  );
}

export function IsolatedSyntaxTextarea({
  value,
  onValueChange,
  ...props
}: Omit<Parameters<typeof SyntaxTextarea>[0], "onChange"> & {
  onValueChange: (value: string) => void;
}) {
  const [localValue, setLocalValue] = useState(value);
  useEffect(() => setLocalValue(value), [value]);
  return (
    <SyntaxTextarea
      {...props}
      value={localValue}
      onChange={(event) => {
        const next = event.currentTarget.value;
        setLocalValue(next);
        onValueChange(next);
      }}
    />
  );
}

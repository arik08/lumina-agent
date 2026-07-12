import { LoaderCircle, MessageCircle, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { ConversationSearchResult } from "../api-types";

interface ConversationSearchDialogProps {
  projectId: string | null;
  projectName: string | null;
  onClose: () => void;
  onSelect: (conversation: ConversationSearchResult) => void;
}

const BODY_RESULT_PAGE_SIZE = 5;

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : "대화를 검색하지 못했습니다.";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

export function ConversationSearchDialog({ projectId, projectName, onClose, onSelect }: ConversationSearchDialogProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ConversationSearchResult[]>([]);
  const [tokens, setTokens] = useState<string[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [visibleBodyCount, setVisibleBodyCount] = useState(BODY_RESULT_PAGE_SIZE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleResults = results.filter((result) => tokens.every((token) => result.title.toLocaleLowerCase().includes(token)));
  const bodyResults = results.filter((result) => !tokens.every((token) => result.title.toLocaleLowerCase().includes(token)));
  const visibleBodyResults = bodyResults.slice(0, visibleBodyCount);
  const visibleResults = [...titleResults, ...visibleBodyResults];

  useEffect(() => {
    const normalized = query.trim();
    if (!normalized) {
      setResults([]);
      setTokens([]);
      setLoading(false);
      setError(null);
      setVisibleBodyCount(BODY_RESULT_PAGE_SIZE);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      api.conversations.searchContent(normalized, projectId ?? undefined, controller.signal)
        .then((response) => {
          setResults(response.items);
          setTokens(response.queryTokens);
          setActiveIndex(0);
          setVisibleBodyCount(BODY_RESULT_PAGE_SIZE);
        })
        .catch((caught) => {
          if (!controller.signal.aborted) setError(errorMessage(caught));
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 170);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [projectId, query]);

  return (
    <div className="conversation-search-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="conversation-search-dialog" role="dialog" aria-modal="true" aria-labelledby="conversation-search-title">
        <header><div><Search size={16} /><strong id="conversation-search-title">대화 검색</strong><small>{projectName ?? "현재 Project"}</small></div><div className="conversation-search-header-actions"><kbd>Ctrl + Shift + F</kbd><button type="button" aria-label="검색 닫기" onClick={onClose}><X size={16} /></button></div></header>
        <label className="conversation-search-input"><Search size={15} /><input autoFocus value={query} placeholder="세션 제목과 대화 내용 검색" role="combobox" aria-expanded={visibleResults.length > 0} aria-controls="conversation-search-results" aria-activedescendant={visibleResults[activeIndex] ? `conversation-search-result-${activeIndex}` : undefined} onChange={(event) => setQuery(event.currentTarget.value)} onKeyDown={(event) => {
          if (event.key === "Escape") { event.preventDefault(); onClose(); }
          if (event.key === "ArrowDown" && visibleResults.length > 0) { event.preventDefault(); setActiveIndex((index) => (index + 1) % visibleResults.length); }
          if (event.key === "ArrowUp" && visibleResults.length > 0) { event.preventDefault(); setActiveIndex((index) => (index - 1 + visibleResults.length) % visibleResults.length); }
          if (event.key === "Enter" && visibleResults[activeIndex]) { event.preventDefault(); onSelect(visibleResults[activeIndex]); }
        }} /></label>
        <div className="conversation-search-summary">{tokens.length > 0 ? <span>{tokens.map((token) => `“${token}”`).join(" + ")} · {results.length}건</span> : <span>공백으로 나눈 모든 단어를 제목과 본문에서 찾습니다.</span>}{loading && <LoaderCircle className="is-running" size={14} />}</div>
        {error && <div className="feature-error" role="alert">{error}</div>}
        <div className="conversation-search-results" id="conversation-search-results" role="listbox" aria-label="대화 검색 결과">
          {!query.trim() ? <p>검색어를 입력해 주세요.</p> : !loading && !error && results.length === 0 ? <p>일치하는 대화가 없습니다.</p> : null}
          {query.trim() && results.length > 0 && titleResults.length > 0 && <div className="conversation-search-group-label">제목 일치 <span>{titleResults.length}</span></div>}
          {query.trim() && titleResults.map((result, index) => (
            <button className={index === activeIndex ? "is-active" : ""} id={`conversation-search-result-${index}`} type="button" role="option" aria-selected={index === activeIndex} key={result.id} onMouseEnter={() => setActiveIndex(index)} onClick={() => onSelect(result)}><MessageCircle size={15} /><span><strong>{result.title}</strong><small>제목에서 일치</small></span><time>{formatDate(result.updatedAt)}</time></button>
          ))}
          {query.trim() && bodyResults.length > 0 && <div className="conversation-search-group-label">본문 일치 <span>{bodyResults.length}</span></div>}
          {query.trim() && visibleBodyResults.map((result, bodyIndex) => {
            const index = titleResults.length + bodyIndex;
            return <button className={index === activeIndex ? "is-active" : ""} id={`conversation-search-result-${index}`} type="button" role="option" aria-selected={index === activeIndex} key={result.id} onMouseEnter={() => setActiveIndex(index)} onClick={() => onSelect(result)}><MessageCircle size={15} /><span><strong>{result.title}</strong><small>{result.matches[0]?.snippet || "본문에서 일치"}</small></span><time>{formatDate(result.updatedAt)}</time></button>;
          })}
          {visibleBodyCount < bodyResults.length && <div className="conversation-search-more"><button type="button" onClick={() => setVisibleBodyCount((count) => count + BODY_RESULT_PAGE_SIZE)}>본문 결과 더 보기 · {bodyResults.length - visibleBodyCount}개 남음</button></div>}
        </div>
      </section>
    </div>
  );
}

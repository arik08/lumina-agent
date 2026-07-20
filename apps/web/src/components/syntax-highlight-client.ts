import { renderHighlightedHtml, type SyntaxHighlighter } from "./syntax-highlight-render";

interface HighlightResponse {
  id: number;
  html?: string;
  error?: string;
}

let worker: Worker | null = null;
let workerFailed = false;
let requestSequence = 0;
let highlighterPromise: Promise<SyntaxHighlighter> | null = null;
const pending = new Map<number, { resolve: (html: string) => void; reject: (error: Error) => void }>();
const cache = new Map<string, string>();
const cacheLimit = 12;

function rememberHighlight(key: string, html: string) {
  if (key.length > 250_000) return;
  cache.delete(key);
  cache.set(key, html);
  while (cache.size > cacheLimit) {
    const oldestKey = cache.keys().next().value;
    if (typeof oldestKey !== "string") break;
    cache.delete(oldestKey);
  }
}

function rejectPending(error: Error) {
  pending.forEach(({ reject }) => reject(error));
  pending.clear();
}

function getWorker() {
  if (worker || workerFailed || typeof Worker === "undefined") return worker;
  try {
    worker = new Worker(new URL("./syntax-highlight.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (event: MessageEvent<HighlightResponse>) => {
      const request = pending.get(event.data.id);
      if (!request) return;
      pending.delete(event.data.id);
      if (typeof event.data.html === "string") request.resolve(event.data.html);
      else request.reject(new Error(event.data.error || "highlight_failed"));
    };
    worker.onerror = () => {
      worker?.terminate();
      worker = null;
      workerFailed = true;
      rejectPending(new Error("highlight_worker_failed"));
    };
  } catch {
    workerFailed = true;
  }
  return worker;
}

async function highlightOnMainThread(value: string, language: string) {
  highlighterPromise ??= import("highlight.js/lib/common").then((module) => module.default);
  return renderHighlightedHtml(await highlighterPromise, value, language);
}

export async function requestSyntaxHighlight(value: string, language: string) {
  const cacheKey = `${language}\u0000${value}`;
  const cached = cache.get(cacheKey);
  if (cached !== undefined) {
    cache.delete(cacheKey);
    cache.set(cacheKey, cached);
    return cached;
  }
  const activeWorker = getWorker();
  const html = activeWorker
    ? await new Promise<string>((resolve, reject) => {
        const id = ++requestSequence;
        pending.set(id, { resolve, reject });
        activeWorker.postMessage({ id, value, language });
      }).catch(() => highlightOnMainThread(value, language))
    : await highlightOnMainThread(value, language);
  rememberHighlight(cacheKey, html);
  return html;
}

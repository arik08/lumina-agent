/// <reference lib="webworker" />

import hljs from "highlight.js/lib/common";
import { renderHighlightedHtml } from "./syntax-highlight-render";

interface HighlightRequest {
  id: number;
  value: string;
  language: string;
}

self.onmessage = (event: MessageEvent<HighlightRequest>) => {
  const { id, value, language } = event.data;
  try {
    self.postMessage({ id, html: renderHighlightedHtml(hljs, value, language) });
  } catch (error) {
    self.postMessage({ id, error: error instanceof Error ? error.message : "highlight_failed" });
  }
};

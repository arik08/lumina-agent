import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("source evidence distinguishes cited, reviewed, and search-only material", async () => {
  const [app, streamingMarkdown, apiTypes, stylesheet] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/streaming-markdown.ts"),
    read("../src/api-types.ts"),
    read("../src/styles.css"),
  ]);

  assert.match(apiTypes, /status: "cited" \| "resolved" \| "reference_only"/);
  assert.match(apiTypes, /researchVerification\?: "verified" \| "unverified" \| "not_required" \| "disabled"/);
  assert.match(app, /citation\.status === "cited" \|\| citation\.status === "resolved"/);
  assert.match(app, /reviewed: source\.evidenceKind === "fetched_content"/);
  assert.match(app, /const leftRank = left\.cited \? 0 : left\.reviewed \? 1 : 2/);
  assert.match(app, /if \(left\.cited && left\.citationOrder !== right\.citationOrder\)/);
  assert.match(app, /return left\.citationOrder - right\.citationOrder/);
  assert.match(app, /return left\.sourceOrder - right\.sourceOrder/);
  assert.doesNotMatch(app, /normalizeCitationPositions/);
  assert.match(app, /useStreamingMarkdownParts\(text, streaming\)/);
  assert.match(streamingMarkdown, /if \(!streaming\) \{[\s\S]*stableBlocks: \[text\], liveTail: "", pendingKind: null/);
  assert.match(app, /"본문 확인" : "검색 참고"/);
  assert.match(app, /function searchPurposeLabel\(purpose\?: string\)/);
  assert.match(app, /researchVerification === "unverified"/);
  assert.match(app, /최신성 또는 중요도가 높은 정보에 필요한 웹 본문을 확인하지 못했습니다/);
  assert.match(app, /sourceCountLabels = \[/);
  assert.match(app, /sourceCountLabels\.length > 0/);
  assert.match(app, /citedSourceCount > 0 && <span className="answer-source-count is-cited"> · 인용 \{citedSourceCount\}<\/span>/);
  assert.match(app, /reviewedSourceCount > 0 && <span className="answer-source-count is-reviewed"> · 본문 확인 \{reviewedSourceCount\}<\/span>/);
  assert.match(app, /referenceSourceCount > 0 && <span className="answer-source-count is-reference-only"> · 검색 참고 \{referenceSourceCount\}<\/span>/);
  assert.match(app, /aria-label=\{`검색 및 참고 출처, \$\{sourceCountLabels\.join\(", "\)\}`\}/);
  assert.match(stylesheet, /\.is-reviewed[^}]*background:[^}]*var\(--success\)/s);
  assert.match(stylesheet, /\.is-reference-only[^}]*background: var\(--surface-soft\)/s);
  assert.match(stylesheet, /\.inline-citation \{[^}]*font-size: 1em;[^}]*vertical-align: baseline;/s);
  assert.match(stylesheet, /\.final-answer-meta \{[^}]*container-type: inline-size;/s);
  assert.match(app, /sourcesOpen && createPortal\(\(/);
  assert.match(app, /document\.querySelector\("\.app-shell"\) \?\? document\.body/);
  assert.match(stylesheet, /\.answer-sources-layer \{ display: contents; \}/);
  assert.match(stylesheet, /\.research-verification-warning \{[^}]*var\(--danger-border\)/s);
  assert.match(stylesheet, /@container \(max-width: 820px\)[^{]*\{[^}]*\.answer-completed-time \{ display: none; \}/s);
  assert.match(stylesheet, /@container \(max-width: 690px\)[^{]*\{[^}]*\.answer-source-count\.is-reference-only \{ display: none; \}/s);
  assert.match(stylesheet, /@container \(max-width: 610px\)[^{]*\{[^}]*\.answer-source-count\.is-reviewed \{ display: none; \}/s);
  assert.match(stylesheet, /@container \(max-width: 530px\)[^{]*\{[^}]*\.answer-source-count\.is-cited \{ display: none; \}/s);
  assert.match(stylesheet, /@container \(max-width: 460px\)[^{]*\{[^}]*\.answer-sources \{ display: none; \}/s);
  assert.match(stylesheet, /\.answer-sources-popover \{[^}]*overflow-x: hidden;[^}]*white-space: normal;/s);
  assert.match(stylesheet, /\.source-queries span \{[^}]*min-width: 0;[^}]*max-width: 100%;[^}]*overflow-wrap: anywhere;[^}]*white-space: normal;/s);
  assert.match(app, /LLM 전달 \{sourceContent\.llmTextChars\.toLocaleString\(\)\}자/);
  assert.match(app, /추출 본문 \{sourceContent\.totalChars\.toLocaleString\(\)\}자/);
  assert.match(app, /onScroll=\{handleSourcesScroll\}/);
  assert.match(app, /getSourceContent\(conversationId, runId, sourceContent\.sourceId, sourceContent\.nextOffset\)/);
  assert.match(stylesheet, /\.source-detail-stats \{[^}]*display: flex;[^}]*flex-wrap: wrap;/s);
});

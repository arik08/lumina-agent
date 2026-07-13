import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("source evidence distinguishes cited, reviewed, and search-only material", async () => {
  const [app, apiTypes, stylesheet] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/api-types.ts"),
    read("../src/styles.css"),
  ]);

  assert.match(apiTypes, /status: "cited" \| "resolved" \| "reference_only"/);
  assert.match(app, /citation\.status === "cited" \|\| citation\.status === "resolved"/);
  assert.match(app, /reviewed: source\.evidenceKind === "fetched_content"/);
  assert.match(app, /function normalizeCitationPositions\(text: string, targets: CitationTarget\[\]\)/);
  assert.match(app, /before === "\*\*" \|\| before === "__"/);
  assert.match(app, /streaming \? text : normalizeCitationPositions\(text, targets\)/);
  assert.match(app, /"본문 확인" : "검색 참고"/);
  assert.match(app, /answer-source-count is-reviewed"> · 본문 확인 \{reviewedSourceCount\}/);
  assert.match(app, /answer-source-count is-reference-only"> · 검색 참고 \{referenceSourceCount\}/);
  assert.match(app, /aria-label=\{`검색 및 참고 출처, 인용 \$\{citedSourceCount\}, 본문 확인 \$\{reviewedSourceCount\}, 검색 참고 \$\{referenceSourceCount\}`\}/);
  assert.match(stylesheet, /\.is-reviewed[^}]*background:[^}]*var\(--success\)/s);
  assert.match(stylesheet, /\.is-reference-only[^}]*background: var\(--surface-soft\)/s);
  assert.match(stylesheet, /\.inline-citation \{[^}]*font-size: 1em;[^}]*vertical-align: baseline;/s);
  assert.match(stylesheet, /\.final-answer-meta \{[^}]*container-type: inline-size;/s);
  assert.match(stylesheet, /@container \(max-width: 820px\)[^{]*\{[^}]*\.answer-completed-time \{ display: none; \}/s);
  assert.match(stylesheet, /@container \(max-width: 690px\)[^{]*\{[^}]*\.answer-source-count\.is-reference-only \{ display: none; \}/s);
  assert.match(stylesheet, /@container \(max-width: 610px\)[^{]*\{[^}]*\.answer-source-count\.is-reviewed \{ display: none; \}/s);
  assert.match(stylesheet, /@container \(max-width: 530px\)[^{]*\{[^}]*\.answer-source-count\.is-cited \{ display: none; \}/s);
  assert.match(stylesheet, /@container \(max-width: 460px\)[^{]*\{[^}]*\.answer-sources \{ display: none; \}/s);
});

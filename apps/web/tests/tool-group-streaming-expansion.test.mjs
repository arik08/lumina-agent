import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("the latest tool group remains expanded while the assistant writes its response", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /keepLatestToolGroupOpen=\{status === "model_streaming"\}/);
  assert.match(app, /const latestToolGroupSummaryId = activityGroups\.reduce/);
  assert.match(app, /if \(keepLatestToolGroupOpen && latestToolGroupSummaryId\) autoOpenSummaryIds\.add\(latestToolGroupSummaryId\)/);
  assert.match(app, /if \(!autoOpenSummaryIds\.has\(id\)\) next\.delete\(id\)/);
});

test("expanded tool groups only receive accent colors while hovered", async () => {
  const styles = await read("../src/styles.css");

  assert.match(styles, /\.progress-group-toggle:hover \{ background: var\(--cobalt-pale\); \}/);
  assert.match(styles, /\.progress-group-toggle:focus-visible \{ outline-color: var\(--line-strong\); \}/);
  assert.match(styles, /\.progress-group-toggle:hover:focus-visible \{ outline-color: color-mix\(in srgb, var\(--cobalt\) 58%, transparent\); \}/);
  assert.match(styles, /\.progress-group-toggle:hover \.tool-call-group-summary \{ color: var\(--ink\); \}/);
  assert.doesNotMatch(styles, /\.progress-group-toggle\[aria-expanded="true"\][^{]*\{[^}]*?(?:background|color)\s*:/s);
});

test("tool group metadata reserves the same scrollbar gutter as its tool rows", async () => {
  const styles = await read("../src/styles.css");

  assert.match(styles, /\.tool-call-group-summary \{[^}]*overflow-y: auto;[^}]*scrollbar-gutter: stable;[^}]*scrollbar-width: thin;/s);
  assert.match(styles, /\.tool-call-group-summary \{[^}]*grid-template-columns: 17px minmax\(0, 1fr\) 46px 16px;[^}]*gap: 5px;/s);
  assert.match(styles, /\.progress-tools \{[^}]*max-height: 470px;[^}]*overflow-y: auto;[^}]*scrollbar-gutter: stable;[^}]*scrollbar-width: thin;/s);
  for (const selector of [
    ".model-exchange",
    ".model-exchange-heading strong",
    ".model-exchange-heading span",
    ".model-exchange h4",
    ".model-exchange-item > strong",
    ".model-exchange-item pre",
    ".model-exchange p",
    ".model-exchange > small",
  ]) {
    assert.match(styles, new RegExp(`${selector.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")} \\{[^}]*font-size: 12px;`, "s"));
  }
});

test("single-tool stage durations use the same duration and chevron columns as tool rows", async () => {
  const styles = await read("../src/styles.css");

  assert.match(styles, /\.progress-summary-text \{[^}]*grid-template-columns: minmax\(0, 1fr\) 46px 16px;[^}]*gap: 5px;[^}]*padding-right: 6px;[^}]*scrollbar-gutter: stable;[^}]*scrollbar-width: thin;/s);
});

test("every running tool spinner follows its label while duration and chevron stay rightmost", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");
  const styles = await read("../src/styles.css");

  assert.match(app, /<span className="tool-call-label-with-status">\s*<span className="tool-call-label">\{execution\.label \|\| execution\.toolName\}<\/span>\s*\{running \? \(\s*<LoaderCircle/s);
  assert.match(app, /<span className="tool-call-label-with-status model-processing-label">\s*<span className="tool-call-label">AI 내부 추론<\/span>\s*\{running\s*\? <LoaderCircle/s);
  assert.match(styles, /\.tool-call-trigger \{[^}]*grid-template-columns: 17px minmax\(90px, \.65fr\) minmax\(0, 1\.35fr\) auto 46px 16px;/s);
  assert.match(styles, /\.model-processing-row \{[^}]*grid-template-columns: 17px minmax\(90px, \.65fr\) minmax\(0, 1\.35fr\) auto 46px 16px;/s);
  assert.match(styles, /\.tool-call-label-with-status \{[^}]*display: inline-flex;[^}]*gap: 5px;/s);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*\.tool-call-trigger \{[^}]*grid-template-columns: 17px minmax\(0, 1fr\) 16px;/s);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*\.model-processing-row \{[^}]*grid-template-columns: 17px minmax\(0, 1fr\) 16px;/s);
  assert.match(app, /isOpen \? <ChevronDown size=\{15\}/);
});

test("frequent tool icons stay neutral while important tools keep semantic colors", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");
  const styles = await read("../src/styles.css");

  for (const className of ["is-web-search", "is-web-fetch", "is-file-browse", "is-read-file", "is-write-file", "is-model-processing"]) {
    assert.match(app, new RegExp(`tool-kind-icon ${className}`));
  }
  assert.match(styles, /\.tool-kind-icon:is\(\.is-web-search, \.is-web-fetch, \.is-file-browse, \.is-read-file, \.is-write-file, \.is-model-processing\) \{ --tool-icon-color: var\(--tool-common\); \}/);
  for (const className of ["is-report", "is-image"]) {
    assert.match(app, new RegExp(`tool-kind-icon ${className}`));
    assert.match(styles, new RegExp(`\\.tool-kind-icon\\.${className} \\{ --tool-icon-color: var\\(--tool-`));
  }
  assert.match(styles, /\.skill-activity > svg \{ color: var\(--cobalt\); \}/);
  assert.match(styles, /\.skill-activity-kind \{ color: var\(--cobalt\);/);
  assert.match(styles, /--tool-common: var\(--faint\);/);
  assert.match(styles, /\.skill-activity strong \{[^}]*color: var\(--cobalt\);/s);
  assert.match(styles, /\.theme-dark \.tool-kind-icon \{ color: var\(--tool-icon-color, var\(--tool-common\)\); \}/);
  assert.match(styles, /\.tool-call-group-summary > svg:first-child \{ color: var\(--tool-icon-color, var\(--tool-common\)\); \}/);
});

test("LLM summaries stay prominent while an open tool row uses a quiet neutral surface", async () => {
  const styles = await read("../src/styles.css");

  assert.match(styles, /--tool-row-selected-surface: color-mix\(in srgb, var\(--ink\) 3%, var\(--chat-canvas\)\);/);
  assert.match(styles, /--tool-row-selected-surface: color-mix\(in srgb, var\(--ink\) 5%, var\(--chat-canvas\)\);\s*--tool-common: var\(--faint\);/);
  assert.match(styles, /\.progress-summary-text \{[^}]*color: inherit;[^}]*font-size: 14px;[^}]*font-weight: 500;/s);
  assert.match(styles, /\.tool-call-trigger \{[^}]*color: var\(--muted\);/s);
  assert.match(styles, /\.tool-call\.is-open > \.tool-call-trigger \{ background: var\(--tool-row-selected-surface\); color: var\(--ink\); \}/);
  assert.doesNotMatch(styles, /\.tool-call\.is-open > \.tool-call-trigger \{[^}]*background: var\(--cobalt-pale\);/s);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("rendered code blocks expose an inline copy action with local feedback", async () => {
  const [turn, styles] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(turn, /function MarkdownCodeBlock/);
  assert.match(turn, /await copyText\(source\)/);
  assert.match(turn, /"복사됨"[\s\S]*"복사 실패"[\s\S]*"복사"/);
  assert.match(turn, /pre: MarkdownCodeBlock/);
  assert.match(turn, /language === "mermaid"[\s\S]*language === "lumina-chart"/);
  assert.match(styles, /\.markdown-code-copy\s*\{[^}]*position:\s*absolute;[^}]*top:\s*7px;[^}]*right:\s*8px;/s);
  assert.match(styles, /\.markdown-code-copy:focus-visible/);
});

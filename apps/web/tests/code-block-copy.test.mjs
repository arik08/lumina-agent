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
  assert.match(turn, /copyState === "copied" \? "복사됨" : copyState === "error" \? "복사 실패" : "코드 복사"/);
  assert.match(turn, /const markdownPreComponent:[\s\S]*<MarkdownCodeBlock>\{children\}<\/MarkdownCodeBlock>/);
  assert.match(turn, /const interactive = language === "mermaid" \|\| language === "mmd" \|\| language === "lumina-chart"/);
  assert.match(turn, /className="visually-hidden" role="status" aria-live="polite"/);
  assert.match(styles, /\.markdown-code-copy\s*\{[^}]*position:\s*absolute;[^}]*top:\s*6px;[^}]*right:\s*6px;/s);
  assert.match(styles, /\.markdown-code-copy\.is-copied/);
  assert.match(styles, /\.markdown-code-copy\.is-error/);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnPath = new URL("../src/components/ConversationTurn.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("saved Knowledge action keeps its original icon and uses a plain success color", async () => {
  const [turn, styles] = await Promise.all([
    readFile(turnPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(turn, /knowledgeSaving \? "is-saving" : knowledgeSaved \? "is-saved"/);
  assert.match(turn, /aria-label="지식 그래프 등록" data-tooltip="지식 그래프 등록"/);
  assert.match(turn, /knowledgeSaving \? <LoaderCircle[^:]+: <BookPlus size=\{16\} \/>/);
  assert.doesNotMatch(turn, /knowledgeSaved \? <Check/);
  assert.match(styles, /\.knowledge-save-control\.is-saving:hover \{ background: transparent; color: var\(--success\); opacity: 1; \}/);
  assert.match(styles, /\.knowledge-save-control\.is-saving > \.is-running \{ color: var\(--success\); \}/);
  assert.match(styles, /\.knowledge-save-control\.is-saved:hover \{ background: transparent; color: var\(--success\); opacity: 1; \}/);
});

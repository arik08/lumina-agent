import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [turn, types, styles] = await Promise.all([
  readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/api-types.ts", import.meta.url), "utf8"),
  readFile(new URL("../src/styles.css", import.meta.url), "utf8"),
]);

test("completed answers expose used memory in a collapsed citation panel", () => {
  assert.match(types, /memoryCitations\?: MemoryCitation\[\]/);
  assert.match(turn, /finalMessage\?\.metadata\?\.memoryCitations \?\? \[\]/);
  assert.match(turn, /<MemoryCitations citations=\{memoryCitations\} \/>/);
  assert.match(turn, /aria-expanded=\{open\}/);
  assert.match(turn, /활용한 메모리 \{citations\.length\}개/);
  assert.match(styles, /\.memory-citations \{[^}]*border-top: 1px solid var\(--line\)/s);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\).*\.memory-citations-trigger/s);
});

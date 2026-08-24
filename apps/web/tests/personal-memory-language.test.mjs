import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const memoryViewPath = new URL("../src/components/MemoryView.tsx", import.meta.url);

test("personal Memory shows and edits one Korean memory sentence", async () => {
  const memoryView = await readFile(memoryViewPath, "utf8");

  assert.match(memoryView, /<p>\{memory\.displayText\}<\/p>/);
  assert.doesNotMatch(memoryView, /memory-fact">\{memory\.normalizedFact\}/);
  assert.match(memoryView, /<span>기억할 내용<\/span>/);
  assert.match(memoryView, /fact: draft\.displayText\.trim\(\),\s*displayText: draft\.displayText\.trim\(\),/s);
});

test("Memory navigation does not expose the Project Memory panel", async () => {
  const memoryView = await readFile(memoryViewPath, "utf8");

  assert.doesNotMatch(memoryView, />Project Memory<\/button>/);
  assert.doesNotMatch(memoryView, /tab === "project"/);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("file listing normalizes legacy array responses before rendering", async () => {
  const api = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
  const start = api.indexOf("export async function listProjectFiles(");
  const end = api.indexOf("export async function getProjectFile(", start);
  const implementation = api.slice(start, end);

  assert.ok(start >= 0 && end > start);
  assert.match(implementation, /ProjectFilePage\s*\|\s*ProjectFileSummary\[\]/);
  assert.match(implementation, /Array\.isArray\(response\)/);
  assert.match(implementation, /items:\s*response/);
  assert.match(implementation, /nextCursor:\s*null/);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("cross-view data caching is bounded and refreshes recently used entries", async () => {
  const source = await read("../src/view-data-cache.tsx");

  assert.match(source, /const viewDataCacheLimit = 48;/);
  assert.match(source, /function touchCacheValue[\s\S]*?cache\.delete\(key\);[\s\S]*?while \(cache\.size > viewDataCacheLimit\)/);
  assert.match(source, /if \(hasValue\) touchCacheValue\(cache, key, value\);/);
  assert.match(source, /touchCacheValue\(cache, key, value\);[\s\S]*?hasValue: true/);
});

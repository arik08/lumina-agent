import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const stylesPath = new URL("../src/styles.css", import.meta.url);

test("code and source surfaces follow the global UI font policy", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /--font-ui:\s*"Pretendard Variable"[^;]+;/);
  assert.match(styles, /--font-code:\s*var\(--font-ui\);/);
  assert.match(styles, /:where\(code, kbd, samp, pre\)\s*\{[^}]*font-family:\s*var\(--font-code\);/);
  assert.doesNotMatch(styles, /(?:ui-)?monospace|SFMono-Regular|Consolas|Liberation Mono/);
});

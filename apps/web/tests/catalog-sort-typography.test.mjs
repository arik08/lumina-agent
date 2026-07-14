import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const stylesPath = new URL("../src/styles.css", import.meta.url);

test("catalog sort trigger and options use 14px text", async () => {
  const styles = await readFile(stylesPath, "utf8");
  assert.match(styles, /\.lumina-select\.size-small \.lumina-select-trigger\[aria-label="카탈로그 정렬"\], \.lumina-select-menu\.size-small\[aria-label="카탈로그 정렬 목록"\] > button \{ font-size: 14px; \}/);
});

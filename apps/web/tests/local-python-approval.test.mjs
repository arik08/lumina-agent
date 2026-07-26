import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");

test("local Python execution approval is labeled separately from external changes", () => {
  assert.match(
    appSource,
    /approval\.effect === "local_execution" \? "로컬 Python 실행" : "외부 시스템을 변경하는 작업"/,
  );
});

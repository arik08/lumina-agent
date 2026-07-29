import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appUrl = new URL("../src/App.tsx", import.meta.url);

test("the hidden admin hotkey remains Ctrl or Command + Shift + X", async () => {
  const app = await readFile(appUrl, "utf8");

  assert.match(
    app,
    /!event\.repeat && isAdmin && \(event\.ctrlKey \|\| event\.metaKey\) && event\.shiftKey && !event\.altKey && event\.code === "KeyX"[\s\S]*?event\.preventDefault\(\);[\s\S]*?openAdmin\(\);/,
  );
});

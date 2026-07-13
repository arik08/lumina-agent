import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const typesPath = new URL("../src/api-types.ts", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("admin model settings expose the configured and hard output token limits", async () => {
  const [app, types, styles] = await Promise.all([
    readFile(appPath, "utf8"),
    readFile(typesPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(app, /type="range"/);
  assert.match(app, /최대 출력 토큰/);
  assert.match(app, /모델 최대/);
  assert.match(app, /configured_max_output_tokens/);
  assert.match(types, /configuredMaxOutputTokens: number \| null/);
  assert.match(types, /maxOutputTokens: number \| null/);
  assert.match(styles, /\.settings-token-slider input\[type="range"\]/);
});

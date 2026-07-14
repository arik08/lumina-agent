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
  assert.match(app, /모델 전체 컨텍스트/);
  assert.match(app, /기본 최대 입력 컨텍스트/);
  assert.match(app, /자동 압축 시작 비율/);
  assert.match(app, /기본 자동 압축 시작점/);
  assert.match(app, /contextPolicyLocked/);
  assert.doesNotMatch(app, /실제 사용 가능 컨텍스트/);
  assert.match(types, /configuredMaxOutputTokens: number \| null/);
  assert.match(types, /maxOutputTokens: number \| null/);
  assert.match(types, /contextPolicyLocked: boolean/);
  assert.match(styles, /\.settings-token-slider input\[type="range"\]/);
});

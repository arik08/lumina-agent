import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/AdminView.tsx", import.meta.url);
const apiPath = new URL("../src/api.ts", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("admin run safety exposes generous limits and a same-button emergency confirmation", async () => {
  const [view, api, styles] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(view, /실행 안전/);
  assert.match(view, /최대 모델 Turn/);
  assert.match(view, /최대 누적 Token/);
  assert.match(view, /모든 세션 작업 Kill/);
  assert.match(view, /한 번 더 눌러 모든 작업 중단/);
  assert.match(api, /\/admin\/run-safety/);
  assert.match(api, /\/admin\/run-safety\/emergency-stop/);
  assert.match(styles, /\.admin-emergency-stop-panel > button\.is-armed/);
});

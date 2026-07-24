import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const component = readFileSync(new URL("../src/components/AdminRunSafetySettings.tsx", import.meta.url), "utf8");
const apiTypes = readFileSync(new URL("../src/api-types.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("admin run safety exposes the global YOLO mode setting", () => {
  assert.match(apiTypes, /interface AdminRunSafetySettings[\s\S]*yoloMode: boolean/);
  assert.match(component, /YOLO mode 사용/);
  assert.match(component, /role="switch"/);
  assert.match(component, /aria-checked=\{runSafety\.yoloMode\}/);
  assert.match(component, /yoloMode: !runSafety\.yoloMode/);
  assert.match(styles, /\.admin-yolo-mode-setting/);
});

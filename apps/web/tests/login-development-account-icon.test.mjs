import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const componentUrl = new URL("../src/components/LoginScreen.tsx", import.meta.url);
const stylesheetUrl = new URL("../src/login.css", import.meta.url);

test("development account helper is a discreet accessible icon with a tooltip", async () => {
  const [component, stylesheet] = await Promise.all([
    readFile(componentUrl, "utf8"),
    readFile(stylesheetUrl, "utf8"),
  ]);

  assert.match(component, /\bUserPlus\b/);
  assert.match(component, /aria-label="개발 계정 admin@posco\.com 채우기"/);
  assert.match(component, /<UserPlus[^>]*aria-hidden="true"[^>]*\/>/);
  assert.match(component, /data-tooltip="개발 계정 admin@posco\.com 채우기"/);
  assert.doesNotMatch(component, /login-dev-account-tooltip|role="tooltip"/);
  assert.doesNotMatch(component, />\s*개발 계정 admin@posco\.com 채우기\s*<\/button>/);

  assert.doesNotMatch(stylesheet, /login-dev-account-tooltip/);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const componentUrl = new URL("../src/components/LoginScreen.tsx", import.meta.url);
const stylesheetUrl = new URL("../src/login.css", import.meta.url);

test("development account helper is hidden behind the Lumina wordmark", async () => {
  const [component, stylesheet] = await Promise.all([
    readFile(componentUrl, "utf8"),
    readFile(stylesheetUrl, "utf8"),
  ]);

  assert.match(component, /const handleWordmarkClick = \(event: MouseEvent<HTMLAnchorElement>\) => \{/);
  assert.match(component, /if \(!import\.meta\.env\.DEV\) return;/);
  assert.match(component, /<a className="login-wordmark" href="\/" aria-label="Lumina 홈" onClick=\{handleWordmarkClick\}>/);
  assert.match(component, /void loginAsDevelopmentAdmin\(\);/);
  assert.match(component, /authenticate\(\{ loginName: "admin", loginDomain: "posco\.com", password: "1111" \}\)/);
  assert.doesNotMatch(component, /\bUserPlus\b|login-dev-account|개발 관리자 계정으로 로그인/);

  assert.doesNotMatch(stylesheet, /login-dev-account/);
});

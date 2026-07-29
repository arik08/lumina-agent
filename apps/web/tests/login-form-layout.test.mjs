import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const componentUrl = new URL("../src/components/LoginScreen.tsx", import.meta.url);
const stylesheetUrl = new URL("../src/login.css", import.meta.url);

test("login identity and registration actions use consistent row and button affordances", async () => {
  const [component, stylesheet] = await Promise.all([
    readFile(componentUrl, "utf8"),
    readFile(stylesheetUrl, "utf8"),
  ]);

  assert.match(component, /className="login-field login-identity-control"/);
  assert.match(stylesheet, /\.login-identity-control\s*\{[\s\S]*grid-template-columns:\s*52px minmax\(0,\s*1fr\)/);
  assert.match(stylesheet, /\.login-register-open\s*\{[\s\S]*width:\s*100%[\s\S]*border:\s*1px solid/);
  assert.match(stylesheet, /\.login-register-open:focus-visible\s*\{/);
});

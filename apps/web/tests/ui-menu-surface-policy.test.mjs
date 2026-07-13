import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const stylesPath = new URL("../src/styles.css", import.meta.url);

const menuSurfaceSelectors = [
  ".sidebar",
  ".bulk-session-projects",
  ".project-options",
  ".session-options-menu",
  ".account-menu",
  ".settings-section-nav",
  ".project-manager-list",
  ".project-manager-list > header",
  ".admin-limit-menu",
  ".notification-panel",
  ".answer-usage-popover",
  ".composer-suggestions",
  ".composer-picker-menu",
  ".artifact-version-menu",
];

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test("navigation and menu surfaces share one neutral color token", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /--menu-surface:\s*oklch\(95\.5% 0\.003 255\);/);
  assert.match(styles, /--menu-surface:\s*#121417;/);
  assert.doesNotMatch(styles, /--sidebar\s*:/);
  assert.doesNotMatch(styles, /#(?:f7f7f5|fbfbfa|f4f4f2|f7f7f6)\b/i);

  for (const selector of menuSurfaceSelectors) {
    assert.match(
      styles,
      new RegExp(`${escapeRegExp(selector)}\\s*\\{[^}]*background:\\s*var\\(--menu-surface\\);`),
      `${selector} must use --menu-surface`,
    );
  }
});

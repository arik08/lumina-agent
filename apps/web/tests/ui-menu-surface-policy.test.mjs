import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const stylesPath = new URL("../src/styles.css", import.meta.url);
const selectStylesPath = new URL("../src/components/SelectMenu.css", import.meta.url);

const menuSurfaceSelectors = [
  ".sidebar",
  ".bulk-session-projects",
  ".project-options",
  ".session-options-menu",
  ".account-menu",
  ".settings-section-nav",
  ".project-manager-list",
  ".project-manager-list > header",
  ".notification-panel",
  ".answer-usage-popover",
  ".composer-picker-menu",
  ".lumina-select-menu",
];

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test("navigation and menu surfaces share one neutral color token", async () => {
  const styles = (await Promise.all([readFile(stylesPath, "utf8"), readFile(selectStylesPath, "utf8")])).join("\n");

  assert.match(styles, /--menu-surface:\s*oklch\(97\.2% 0\.002 255\);/);
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

test("embedded composer suggestions use the composer surface", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(
    styles,
    /\.composer-suggestions\s*\{[^}]*background:\s*var\(--surface\);/,
  );
});

test("project menu options have visible neutral hover feedback", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(
    styles,
    /\.project-options button:hover\s*\{[^}]*background:\s*color-mix\(in srgb, var\(--ink\) 6%, var\(--menu-surface\)\);/,
  );
});

test("scrollable surfaces use shared neutral scrollbar tokens", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /--scrollbar-thumb:\s*color-mix\(in srgb, var\(--ink\) 11%, transparent\);/);
  assert.match(styles, /--scrollbar-thumb-strong:\s*color-mix\(in srgb, var\(--ink\) 30%, transparent\);/);
  assert.doesNotMatch(
    styles,
    /scrollbar[^;}]*var\(--cobalt\)/,
    "scrollbars must not derive their color from the cobalt accent",
  );
});

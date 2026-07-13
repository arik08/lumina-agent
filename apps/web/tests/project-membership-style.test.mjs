import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const projectSettingsSource = await readFile(
  new URL("../src/components/ProjectSettings.tsx", import.meta.url),
  "utf8",
);
const projectSettingsStyles = await readFile(
  new URL("../src/components/ProjectSettings.css", import.meta.url),
  "utf8",
);
const selectMenuStyles = await readFile(
  new URL("../src/components/SelectMenu.css", import.meta.url),
  "utf8",
);
const globalStyles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

test("project member add action reuses the project information save style", () => {
  assert.match(
    projectSettingsSource,
    /className="primary-compact lumina-primary-action"[^>]*>\{memberActionId === "add"[\s\S]*?계정 추가<\/button>/,
  );
});

test("project role menus suppress the white focus aura without hiding state color", () => {
  assert.match(
    projectSettingsStyles,
    /\.project-membership-settings \.lumina-select-trigger:focus-visible,[\s\S]*?border-color: var\(--cobalt\);[\s\S]*?box-shadow: none;/,
  );
  assert.match(
    projectSettingsStyles,
    /\.project-membership-settings \.lumina-select-menu > button:focus-visible \{[\s\S]*?outline: 0;[\s\S]*?box-shadow: none;/,
  );
  assert.match(selectMenuStyles, /box-shadow: var\(--shadow-overlay\);/);
  assert.match(
    globalStyles,
    /\.app-shell\.theme-dark,[\s\S]*?--shadow-overlay: 0 12px 28px rgba\(0, 0, 0, 0\.38\)/,
  );
});

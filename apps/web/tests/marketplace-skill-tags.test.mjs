import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);
const apiPath = new URL("../src/api.ts", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);
const tagsPath = new URL("../../../extensions/skills/catalog.tags.json", import.meta.url);

test("repository skills display searchable hashtag metadata instead of a source label", async () => {
  const [view, tagsText] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(tagsPath, "utf8"),
  ]);
  const tags = JSON.parse(tagsText);

  assert.deepEqual(tags["visual-artifact"], ["경영기획", "디자인"]);
  assert.ok(Object.values(tags).every((value) => Array.isArray(value) && value.length > 0));
  assert.match(view, /className="marketplace-tags" aria-label="Skill 태그"/);
  assert.match(view, /tags\.map\(\(tag\) => `#\$\{tag\}`\)/);
  assert.doesNotMatch(view, /Lumina 기본 제공/);
});

test("skill visibility and draft state use clear Korean labels", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /if \(visibility === "organization"\) return "조직"/);
  assert.match(view, /if \(visibility === "project"\) return "프로젝트"/);
  assert.match(view, /className="is-draft">초안 r/);
  assert.match(view, /내 작업 초안 r/);
  assert.doesNotMatch(view, /<span>\{selected\.visibility\}<\/span>/);
  assert.doesNotMatch(view, />Draft r/);
  assert.doesNotMatch(view, /WorkingDraft/);
});

test("skill rows use a dedicated install and unused toggle without status badges", async () => {
  const [view, styles] = await Promise.all([readFile(viewPath, "utf8"), readFile(stylesPath, "utf8")]);

  assert.match(view, /className={`marketplace-install-toggle \$\{itemInstallation \? "is-installed" : ""}`}/);
  assert.match(view, /aria-pressed=\{Boolean\(itemInstallation\)\}/);
  assert.match(view, /className="install-toggle-rest">설치됨<\/span>/);
  assert.match(view, /className="install-toggle-hover">미사용<\/span>/);
  assert.match(styles, /\.marketplace-install-toggle\.is-installed:hover \.install-toggle-rest/);
  assert.match(styles, /\.marketplace-install-toggle\.is-installed:focus-visible \.install-toggle-hover/);
  assert.match(styles, /\.marketplace-install-toggle \{[^}]*background: color-mix\(in oklab, var\(--cobalt\) 8%, var\(--surface\)\)/);
  assert.match(styles, /\.marketplace-install-toggle\.is-installed \{[^}]*background: color-mix\(in oklab, var\(--success\) 8%, var\(--surface\)\)/);
  assert.match(styles, /\.marketplace-install-toggle\.is-installed:hover:not\(:disabled\)[^\{]*\{[^}]*background: color-mix\(in oklab, var\(--danger\) 12%, var\(--surface\)\)/);
  assert.match(styles, /\.marketplace-scope-tabs button span \{[^}]*min-width: 18px; height: 18px;[^}]*box-sizing: border-box;[^}]*justify-content: center;/);
  assert.doesNotMatch(view, />설치됨<\/em>/);
  assert.doesNotMatch(view, />공식<\/em>/);
});

test("skill installs are scoped to the signed-in account", async () => {
  const [view, api] = await Promise.all([readFile(viewPath, "utf8"), readFile(apiPath, "utf8")]);

  assert.match(api, /body: \{ versionId, scopeType: "user", enabled: true, settings: \{\} \}/);
  assert.doesNotMatch(api, /body: \{ versionId, scopeType: "project"/);
  assert.match(view, /installed\.filter\(\(entry\) => entry\.scopeType === "user"\)/);
  assert.match(view, /installation \? "미사용" : "설치"/);
  assert.doesNotMatch(view, /Project에 설치/);
});

test("install toggles update locally without replacing the marketplace list", async () => {
  const view = await readFile(viewPath, "utf8");
  const toggleStart = view.indexOf("const toggleInstallation = async");
  const toggleEnd = view.indexOf("const beginPackageEdit = async", toggleStart);
  const toggle = view.slice(toggleStart, toggleEnd);

  assert.match(toggle, /const installed = await api\.extensions\.install\(targetVersion\.id\)/);
  assert.match(toggle, /setInstallations\(\(current\) => \[\.\.\.current\.filter/);
  assert.match(toggle, /setInstallations\(\(current\) => current\.filter/);
  assert.doesNotMatch(toggle, /refresh\(/);
  assert.doesNotMatch(toggle, /setLoading\(/);
  assert.match(view, /pendingInstallationSurfaceById\[item\.id\] === "list"/);
  assert.match(view, /disabled=\{!itemVersion \|\| itemInstallationPending\}/);
});

test("skill draft editor keeps one aligned scroll surface", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /\.marketplace-package-detail \.marketplace-file-browser \.skill-file-editor \{[^}]*height: 520px;[^}]*min-height: 0;[^}]*overflow: hidden;[^}]*padding: 0;[^}]*font-family: var\(--font-code\);[^}]*font-size: 12\.5px;/);
  assert.match(styles, /\.marketplace-file-browser \.skill-file-editor > :is\(pre, textarea\) \{ padding: 13px 15px; \}/);
  assert.match(styles, /\.marketplace-package-detail\.is-editing \.skill-file-content \{ overflow: hidden; \}/);
  assert.match(styles, /\.syntax-editor > pre \{[^}]*overflow: hidden;[^}]*pointer-events: none;/);
  assert.match(styles, /\.skill-file-editor > textarea \{\s*scrollbar-color: var\(--scrollbar-thumb\) transparent;/);
});

test("skill metadata stays in place while editing", async () => {
  const [view, styles] = await Promise.all([readFile(viewPath, "utf8"), readFile(stylesPath, "utf8")]);

  assert.match(view, /<h2 className="marketplace-inline-editor" contentEditable="plaintext-only"/);
  assert.match(view, /<p className="marketplace-inline-editor" contentEditable="plaintext-only"/);
  assert.doesNotMatch(view, /className="marketplace-title-editor"/);
  assert.doesNotMatch(view, /className="marketplace-description-editor"/);
  assert.match(styles, /\.marketplace-inline-editor:focus \{[^}]*box-shadow: inset 0 -1px var\(--cobalt\);/);
});

test("skill file edits do not retain a released React event", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /onChange=\{\(event\) => \{ const nextValue = event\.currentTarget\.value; setEditableFiles\(\(current\) => \(\{ \.\.\.current, \[activeFile\]: nextValue \}\)\); \}\}/);
  assert.doesNotMatch(view, /setEditableFiles\(\(current\) => \(\{ \.\.\.current, \[activeFile\]: event\.currentTarget\.value \}\)\)/);
});

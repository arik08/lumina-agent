import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);
const apiPath = new URL("../src/api.ts", import.meta.url);
const featureApiPath = new URL("../src/feature-api.ts", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);
const tagEditorStylesPath = new URL("../src/components/MarketplaceTagEditor.css", import.meta.url);
const catalogPath = new URL("../../../extensions/skills/catalog.json", import.meta.url);

test("repository skills display searchable hashtag metadata instead of a source label", async () => {
  const [view, catalogText] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(catalogPath, "utf8"),
  ]);
  const catalog = JSON.parse(catalogText);

  assert.deepEqual(catalog["visual-artifact"].tags, ["경영기획", "디자인"]);
  assert.ok(Object.values(catalog).every((entry) => typeof entry.description === "string" && entry.description.length > 0));
  assert.ok(Object.values(catalog).every((entry) => Array.isArray(entry.tags) && entry.tags.length > 0));
  assert.match(view, /className="marketplace-tags" aria-label="Skill 태그"/);
  assert.match(view, /const storedTags = \(item as SkillExtension & \{ tags\?: unknown \}\)\.tags/);
  assert.match(view, /Array\.isArray\(storedTags\) && storedTags\.length > 0/);
  assert.match(view, /tags\.map\(\(tag\) => `#\$\{tag\}`\)/);
  assert.doesNotMatch(view, /Lumina 기본 제공/);
});

test("marketplace detects repository changes and keeps manual full refresh as fallback", async () => {
  const [view, api, featureApi] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(featureApiPath, "utf8"),
  ]);

  assert.match(api, /skillsChanged: number; mcpChanged: number; revision: string/);
  assert.match(featureApi, /getRepositoryState: getRepositoryExtensionState/);
  assert.match(view, /window\.setInterval\(pollWhenVisible, 15_000\)/);
  assert.match(view, /document\.addEventListener\("visibilitychange", pollWhenVisible\)/);
  assert.match(view, /previousRevision === state\.revision/);
  assert.match(view, /const state = await api\.extensions\.syncRepository\(\)/);
  assert.match(view, /onClick=\{\(\) => void refreshRepository\(\)\}/);
});

test("skill visibility and version use the reviewed Publish.Merge.Feedback display", async () => {
  const view = await readFile(viewPath, "utf8");
  const listStart = view.indexOf('<aside className="feature-list"');
  const listEnd = view.indexOf('</aside>', listStart);
  const list = view.slice(listStart, listEnd);

  assert.match(view, /if \(visibility === "organization"\) return "기본"/);
  assert.match(view, /if \(visibility === "project"\) return "프로젝트"/);
  assert.match(view, /function skillDisplayVersion\(item: SkillExtension\)/);
  assert.match(view, /return `v\$\{publish\}\.\$\{merge\}\.\$\{feedback\}`/);
  assert.match(view, /aria-label="Skill 태그"/);
  assert.match(view, /className="detail-badges"[^\n]*skillDisplayVersion\(selected\)/);
  assert.doesNotMatch(view, /`버전 \$\{skillDisplayVersion\(selected\)\}`/);
  assert.match(view, /nextSavedSkillDisplayVersion\(selected\)/);
  assert.doesNotMatch(list, /skillDisplayVersion\(item\)/);
  assert.doesNotMatch(list, /className="is-version"/);
  assert.doesNotMatch(view, /<span>\{selected\.visibility\}<\/span>/);
  assert.doesNotMatch(view, /초안 r/);
  assert.doesNotMatch(view, /내 작업 초안 r/);
  assert.doesNotMatch(view, /v\{latestVersion\.version\}/);
  assert.doesNotMatch(view, />Draft r/);
  assert.doesNotMatch(view, /WorkingDraft/);
});

test("only modified Skill drafts appear in My Drafts", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /if \(skillView === "drafts" && !item\.draft\?\.dirty\) return false/);
  assert.match(view, /drafts: items\.filter\(\(item\) => item\.draft\?\.dirty\)\.length/);
  assert.doesNotMatch(view, /if \(skillView === "drafts" && !item\.draft\) return false/);
  assert.doesNotMatch(view, /drafts: items\.filter\(\(item\) => item\.draft\)\.length/);
});

test("marketplace keeps Skill creation in the chat Skill Creator flow", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.doesNotMatch(view, /새 Skill<\/button>/);
  assert.doesNotMatch(view, /새 Skill 작업 초안/);
  assert.doesNotMatch(view, /const createSkill = async/);
  assert.doesNotMatch(view, /`Skill \$\{items\.length\} · 초안 \$\{counts\.drafts\} · 설치 \$\{counts\.installed\}`/);
});

test("skill rows use a dedicated install and unused toggle without status badges", async () => {
  const buttonPath = new URL("../src/components/MarketplaceInstallButton.tsx", import.meta.url);
  const [view, button, styles] = await Promise.all([readFile(viewPath, "utf8"), readFile(buttonPath, "utf8"), readFile(stylesPath, "utf8")]);

  assert.match(view, /<MarketplaceInstallButton name=\{item\.name\}/);
  assert.match(button, /className=\{`skill-install-toggle/);
  assert.match(button, /aria-pressed=\{installed\}/);
  assert.match(button, /className="marketplace-install-state install-toggle-rest"/);
  assert.match(button, /<span>Installed<\/span>/);
  assert.match(button, /className="marketplace-install-state install-toggle-hover"/);
  assert.match(button, /<span>Delete<\/span>/);
  assert.match(button, /const action = installed \? "Delete" : "Install"/);
  assert.match(styles, /\.skill-install-toggle\.is-installed:hover:not\(:disabled\) \.install-toggle-rest/);
  assert.match(styles, /\.skill-install-toggle\.is-installed:focus-visible:not\(:disabled\) \.install-toggle-hover/);
  assert.match(styles, /\.feature-view\.feature-view \.skill-install-toggle \{[^}]*width: 80px; min-width: 80px; max-width: 80px;[^}]*height: 26px; min-height: 26px; max-height: 26px;/);
  assert.match(styles, /\.skill-install-toggle:active \{ transform: none; \}/);
  assert.match(styles, /\.skill-install-toggle\.is-installed \{[^}]*background: color-mix\(in oklab, var\(--success\) 8%, var\(--surface\)\)/);
  assert.match(styles, /\.skill-install-toggle\.is-installed:hover:not\(:disabled\)[^\{]*\{[^}]*background: color-mix\(in oklab, var\(--danger\) 12%, var\(--surface\)\)/);
  assert.match(styles, /\.marketplace-scope-tabs button span \{[^}]*min-width: 28px; height: 18px;[^}]*box-sizing: border-box;[^}]*justify-content: center;/);
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
  const toggleStart = view.indexOf("const changeInstallation = async");
  const toggleEnd = view.indexOf("const beginPackageEdit = async", toggleStart);
  const toggle = view.slice(toggleStart, toggleEnd);

  assert.match(toggle, /const installed = await api\.extensions\.install\(versionId\)/);
  assert.match(toggle, /setInstallations\(\(current\) => \[\.\.\.current\.filter/);
  assert.match(toggle, /setInstallations\(\(current\) => current\.filter/);
  assert.doesNotMatch(toggle, /refresh\(/);
  assert.doesNotMatch(toggle, /setLoading\(/);
  assert.match(view, /pendingInstallationSurfaceById\[item\.id\] === "list"/);
  assert.match(view, /disabled=\{!itemVersion\}/);
});

test("skill draft editor keeps one aligned scroll surface", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /\.marketplace-package-detail \.marketplace-file-browser \.skill-file-editor \{[^}]*height: 100%;[^}]*min-height: 0;[^}]*overflow: hidden;[^}]*padding: 0;[^}]*font-family: var\(--font-code\);[^}]*font-size: 12\.5px;/);
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

test("Skill owners, maintainers, and administrators can edit tags with other metadata", async () => {
  const [view, api, types, tagEditorStyles] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(new URL("../src/api-types.ts", import.meta.url), "utf8"),
    readFile(tagEditorStylesPath, "utf8"),
  ]);

  assert.match(types, /canEditTags: boolean/);
  assert.match(types, /tags: string\[\]/);
  assert.match(api, /tags\?: string\[\]/);
  assert.match(view, /selected\.canEditTags && <div className="marketplace-tag-editor"/);
  assert.match(view, /aria-label="Skill 태그 추가"/);
  assert.match(view, /tags: tagsToSave/);
  assert.match(tagEditorStyles, /\.marketplace-tag-editor button \{/);
});

test("owners and administrators get a compact two-step Skill trash action", async () => {
  const [view, api, types] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(new URL("../src/api-types.ts", import.meta.url), "utf8"),
  ]);

  assert.match(types, /canDelete: boolean/);
  assert.match(api, /method: "DELETE"/);
  assert.match(view, /selected\.canDelete && <button/);
  assert.match(view, /deleteConfirmId !== selected\.id/);
  assert.match(view, /deleteConfirmId === selected\.id \? "경고" : "삭제"/);
  assert.match(view, /api\.extensions\.delete\(deletedId\)/);
});

test("trashed Skills explain 30-day retention and can be restored", async () => {
  const [view, api, types] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(new URL("../src/api-types.ts", import.meta.url), "utf8"),
  ]);

  assert.match(view, /삭제한 Skill은 30일 동안 보관되며 그 전에 복원할 수 있습니다\./);
  assert.match(view, /data-tooltip="삭제한 Skill은 30일 동안 보관되며 그 전에 복원할 수 있습니다\."/);
  assert.doesNotMatch(view, /<Info size=\{12\} aria-hidden="true" \/>/);
  assert.match(view, /api\.extensions\.listTrash\(\)/);
  assert.match(view, /api\.extensions\.restore\(selected\.id\)/);
  assert.match(view, / 복원<\/button>/);
  assert.match(api, /\/extensions\/trash/);
  assert.match(api, /\/extensions\/\$\{encodeURIComponent\(extensionId\)\}\/restore/);
  assert.match(types, /purgesAt: IsoDateTime \| null/);
});

test("skill file edits do not retain a released React event", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /onChange=\{\(event\) => \{ const nextValue = event\.currentTarget\.value; setEditableFiles\(\(current\) => \(\{ \.\.\.current, \[activeFile\]: nextValue \}\)\); \}\}/);
  assert.doesNotMatch(view, /setEditableFiles\(\(current\) => \(\{ \.\.\.current, \[activeFile\]: event\.currentTarget\.value \}\)\)/);
});

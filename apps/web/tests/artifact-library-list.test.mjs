import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/ArtifactLibraryView.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("artifact library keeps validation internals out of the list", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.doesNotMatch(view, /validationStatus|validation-mark|CheckCircle2/);
  assert.match(view, /<time>\{new Date\(artifact\.updatedAt\)\.toLocaleDateString\("ko-KR"\)\}<\/time>/);
});

test("artifact library uses the themed thin scrollbar", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /--scrollbar-thumb: color-mix\(in srgb, var\(--ink\) 11%, transparent\);/);
  assert.match(styles, /:where\(\*\) \{[\s\S]*?scrollbar-color: var\(--scrollbar-thumb\) transparent;[\s\S]*?scrollbar-width: thin;/);
  assert.match(styles, /:where\(\*\)::\-webkit-scrollbar \{ width: 6px; height: 6px; \}/);
  assert.match(styles, /\.artifact-library-open \{[^}]*grid-template-columns: 30px minmax\(0, 1fr\) auto;/);
  assert.match(styles, /\.artifact-library-scroll \{[^}]*background: var\(--surface\);/);
  assert.doesNotMatch(styles, /\.validation-mark/);
});

test("artifact library requires a second click before deleting", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /deleteArmedId !== artifact\.id[\s\S]*setDeleteArmedId\(artifact\.id\)[\s\S]*return;/);
  assert.match(view, /await api\.artifacts\.delete\(artifact\.id\)/);
  assert.match(view, /삭제 확인, 한 번 더 누르면 삭제/);
  assert.match(view, /data-tooltip=\{deleteArmedId === artifact\.id \? "한 번 더 눌러 삭제" : "삭제"\}/);
  assert.match(view, /setItems\(\(current\) => current\.filter\(\(item\) => item\.id !== artifact\.id\)\)/);
});

test("artifact library uses the main work surface", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /className="feature-scroll artifact-library-scroll"/);
});

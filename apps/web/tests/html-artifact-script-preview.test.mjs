import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const stylesSource = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const visualArtifactSkillSource = readFileSync(new URL("../../../extensions/skills/visual-artifact/SKILL.md", import.meta.url), "utf8");

test("HTML Artifact preview executes JavaScript without same-origin access", () => {
  assert.match(
    appSource,
    /sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads allow-popups allow-popups-to-escape-sandbox"/,
  );
  assert.doesNotMatch(appSource, /allow-scripts allow-same-origin/);
  assert.match(stylesSource, /\.artifact-preview-frame \{[^}]*background: #fff;[^}]*color-scheme: light;/);
});

test("legacy HTML report footnotes match chat citations and remain clickable", () => {
  assert.match(appSource, /function previewArtifactHtml\(source: string\)/);
  assert.match(appSource, /sup\.source-ref \{[^}]*vertical-align: baseline;/s);
  assert.match(appSource, /a\.source-ref:hover, sup\.source-ref > a:hover \{ text-decoration: none !important; \}/);
  assert.match(visualArtifactSkillSource, /\.source-ref:hover \{ text-decoration:none; \}/);
  assert.match(appSource, /link\.textContent = markers\[number - 1\]/);
  assert.match(appSource, /link\.target = "_blank"/);
  assert.match(appSource, /card\.setAttribute\("aria-label", "출처 링크"\)/);
  assert.match(appSource, /sourceLink\.textContent = link\.href/);
  assert.match(appSource, /srcDoc=\{previewArtifactHtml\(/);
});

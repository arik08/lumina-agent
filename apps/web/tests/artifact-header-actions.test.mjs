import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const stylesheetPath = new URL("../src/styles.css", import.meta.url);

test("artifact header keeps its actions visible above the preview", async () => {
  const [app, stylesheet] = await Promise.all([
    readFile(appPath, "utf8"),
    readFile(stylesheetPath, "utf8"),
  ]);

  for (const label of ["본문 수정", "코드 보기", "전체화면", "Artifact 공유 링크 복사", "Artifact 다운로드", "Artifact 닫기"]) {
    assert.ok(app.includes(label), `missing Artifact header action: ${label}`);
  }
  assert.match(stylesheet, /\.artifact-header\s*\{[^}]*position:\s*relative[^}]*z-index:\s*4[^}]*background:\s*var\(--surface\)/s);
  assert.match(stylesheet, /@media \(max-width: 720px\)\s*\{[\s\S]*?\.artifact-header\s*\{[^}]*padding:\s*0 14px 0 11px/s);
  assert.match(stylesheet, /@media \(max-width: 720px\)\s*\{[\s\S]*?\.artifact-header strong\s*\{[^}]*font-size:\s*12\.5px[^}]*\}[\s\S]*?\.artifact-version-select\.size-small \.lumina-select-trigger\s*\{[^}]*font-size:\s*12\.5px/s);
  assert.match(stylesheet, /\.artifact-header > div:last-child > button\s*\{[^}]*color:\s*var\(--muted\)/s);
  assert.match(stylesheet, /\.artifact-header > div:last-child > button:disabled\s*\{[^}]*color:\s*var\(--muted\)[^}]*opacity:\s*1/s);
  assert.ok(!stylesheet.includes(".artifact-header button"), "Artifact header icon rules must not override nested SelectMenu buttons");
  assert.match(stylesheet, /\.artifact-version-select\s*\{[^}]*min-width:\s*60px/s);
  assert.match(stylesheet, /\.artifact-version-select\.size-small \.lumina-select-trigger\s*\{[^}]*font-size:\s*14px/s);
  assert.match(app, /<SelectMenu className="artifact-version-select"/);
  assert.match(app, /const artifactDownloadVersion = artifactVersion\?\.version \?\? artifactSummary\?\.currentVersion \?\? null/);
  assert.match(app, /const \[summary, initialVersion, savedDraft\] = await Promise\.all\(\[[\s\S]*?api\.artifacts\.getVersion\([\s\S]*?artifact\.mimeType !== "text\/html"[\s\S]*?api\.artifacts\.getDraft\(artifact\.id\)/);
  assert.match(app, /artifactVersion\?\.sourceAvailable/);
  assert.match(app, /aria-label="Artifact 공유 링크 복사"[^>]*disabled=\{!artifactSummary\?\.conversationId\}/);
  assert.match(app, /url\.searchParams\.set\("artifact", artifactSummary\.id\)/);
  assert.match(app, /url\.searchParams\.set\("version", String\(artifactDownloadVersion \?\? artifactSummary\.currentVersion\)\)/);
  assert.match(app, /aria-label="Artifact 다운로드"[^>]*disabled=\{!artifactSummary \|\| artifactDownloadVersion === null\}/);
  assert.match(app, /aria-label="Artifact 다운로드"[\s\S]*?aria-label=\{artifactFullscreen \? "전체화면 종료" : "전체화면"\}[\s\S]*?aria-label="Artifact 닫기"/);
  assert.ok(!app.includes('className="artifact-footer"'), "artifact footer should not be rendered");
  assert.ok(!stylesheet.includes(".artifact-footer"), "artifact footer styles should be removed");
});

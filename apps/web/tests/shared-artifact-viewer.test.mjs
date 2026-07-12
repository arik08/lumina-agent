import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewerPath = new URL("../src/components/SharedSnapshotViewer.tsx", import.meta.url);
const stylesheetPath = new URL("../src/styles.css", import.meta.url);
const appPath = new URL("../src/App.tsx", import.meta.url);

test("shared Artifact links open the selected immutable version in a direct viewer", async () => {
  const [viewer, stylesheet, app] = await Promise.all([
    readFile(viewerPath, "utf8"),
    readFile(stylesheetPath, "utf8"),
    readFile(appPath, "utf8"),
  ]);

  assert.match(viewer, /artifactId\?: string \| null/);
  assert.match(viewer, /api\.sharing\.downloadArtifact\(token, artifactId, selectedArtifactVersion/);
  for (const label of ["내용 복사", "Artifact 다운로드"]) {
    assert.ok(viewer.includes(label), `missing shared Artifact action: ${label}`);
  }
  for (const label of ["코드 보기", "전체화면"]) {
    assert.ok(!viewer.includes(label), `unexpected shared Artifact action: ${label}`);
  }
  assert.match(viewer, /copyText\(sharedArtifactSource\)/);
  assert.match(viewer, /className="shared-artifact-frame"[^>]*sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads"[^>]*srcDoc=\{sharedArtifactSource\}/);
  assert.doesNotMatch(stylesheet, /\.shared-artifact-viewer\.is-fullscreen/);
  assert.match(stylesheet, /\.shared-artifact-body\s*\{[^}]*scrollbar-width:\s*thin/s);
  assert.match(app, /if \(sharedViewerToken\) \{\s*return \(\s*<SharedSnapshotViewer[\s\S]*?\);\s*\}\s*const streamLabel/);
  assert.doesNotMatch(app, /<SharedSnapshotViewer[\s\S]*?embedded/);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("file workspace keeps refresh at the far right of the header", async () => {
  const [view, styles] = await Promise.all([
    read("../src/components/ProjectFilesView.tsx"),
    read("../src/styles.css"),
  ]);

  const headerStart = view.indexOf('className="feature-header"');
  const headerEnd = view.indexOf("</header>", headerStart);
  const toolbarStart = view.indexOf('className="feature-toolbar file-workspace-toolbar"');
  const toolbarEnd = view.indexOf("</div>", toolbarStart);
  const dropTarget = view.indexOf("file-drop-target", toolbarStart);
  const refreshAction = view.indexOf('className="file-workspace-refresh"', headerStart);
  const searchField = view.indexOf('className="feature-search"', toolbarStart);

  assert.ok(headerStart >= 0 && headerEnd > headerStart);
  assert.ok(refreshAction > headerStart && refreshAction < headerEnd);
  assert.match(view.slice(headerStart, refreshAction), /파일 Workspace.*Server Workspace/s);
  assert.doesNotMatch(view.slice(headerStart, headerEnd), /업로드/);
  assert.ok(toolbarStart >= 0 && toolbarStart < dropTarget && dropTarget < searchField && searchField < toolbarEnd);
  assert.doesNotMatch(view.slice(toolbarStart, toolbarEnd), /새로 고침|file-workspace-refresh/);
  assert.doesNotMatch(view, /file-workspace-list-toolbar|file-workspace-list-refresh/);
  assert.doesNotMatch(styles, /\.file-workspace-list-toolbar/);
  assert.match(styles, /\.file-workspace-toolbar \.feature-search\s*\{[^}]*flex:\s*1;/);
});

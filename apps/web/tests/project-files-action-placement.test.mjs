import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("file workspace actions follow upload, refresh, and search order", async () => {
  const [view, styles] = await Promise.all([
    read("../src/components/ProjectFilesView.tsx"),
    read("../src/styles.css"),
  ]);

  const headerStart = view.indexOf('className="feature-header"');
  const headerEnd = view.indexOf("</header>", headerStart);
  const toolbarStart = view.indexOf('className="feature-toolbar file-workspace-toolbar"');
  const toolbarEnd = view.indexOf("</div>", toolbarStart);
  const dropTarget = view.indexOf("file-drop-target", toolbarStart);
  const refreshAction = view.indexOf('className="file-workspace-refresh"', toolbarStart);
  const searchField = view.indexOf('className="feature-search"', toolbarStart);

  assert.ok(headerStart >= 0 && headerEnd > headerStart);
  assert.doesNotMatch(view.slice(headerStart, headerEnd), /업로드|새로 고침/);
  assert.ok(toolbarStart >= 0 && toolbarStart < dropTarget && dropTarget < refreshAction && refreshAction < searchField && searchField < toolbarEnd);
  assert.doesNotMatch(view, /file-workspace-list-toolbar|file-workspace-list-refresh/);
  assert.doesNotMatch(styles, /\.file-workspace-list-toolbar/);
  assert.match(styles, /\.file-workspace-toolbar \.feature-search\s*\{[^}]*flex:\s*1;/);
});

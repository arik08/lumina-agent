import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("file upload and refresh actions stay with the left file list", async () => {
  const [view, styles] = await Promise.all([
    read("../src/components/ProjectFilesView.tsx"),
    read("../src/styles.css"),
  ]);

  const headerStart = view.indexOf('className="feature-header"');
  const headerEnd = view.indexOf("</header>", headerStart);
  const listStart = view.indexOf('className="feature-list file-workspace-list"');
  const toolbarStart = view.indexOf('className="feature-toolbar file-workspace-list-toolbar"');
  const emptyState = view.indexOf("Project 파일이 없습니다.");

  assert.ok(headerStart >= 0 && headerEnd > headerStart);
  assert.doesNotMatch(view.slice(headerStart, headerEnd), /업로드|새로 고침/);
  assert.ok(listStart >= 0 && listStart < toolbarStart && toolbarStart < emptyState);
  assert.match(styles, /\.file-workspace-list-toolbar\s*\{[^}]*position:\s*sticky;/);
});

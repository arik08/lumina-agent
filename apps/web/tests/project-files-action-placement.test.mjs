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
  const toolbarEnd = view.indexOf("{error &&", toolbarStart);
  const dropTarget = view.indexOf("file-drop-target", toolbarStart);
  const dropTargetEnd = view.indexOf("</div>", dropTarget);
  const refreshAction = view.indexOf('className="file-workspace-refresh"', headerStart);
  const searchField = view.indexOf('className="feature-search"', toolbarStart);
  const dropTargetMarkup = view.slice(dropTarget, dropTargetEnd);
  const fileButton = dropTargetMarkup.indexOf("파일 선택");
  const folderButton = dropTargetMarkup.indexOf("폴더 선택");
  const dropHint = dropTargetMarkup.indexOf('className="file-drop-hint"');

  assert.ok(headerStart >= 0 && headerEnd > headerStart);
  assert.ok(refreshAction > headerStart && refreshAction < headerEnd);
  assert.match(view.slice(headerStart, refreshAction), /파일 저장소.*사용자 전용.*@ 참조/s);
  assert.doesNotMatch(view.slice(headerStart, headerEnd), /업로드/);
  assert.ok(toolbarStart >= 0 && toolbarStart < dropTarget && dropTarget < searchField && searchField < toolbarEnd);
  assert.doesNotMatch(view.slice(toolbarStart, toolbarEnd), /새로 고침|file-workspace-refresh/);
  assert.doesNotMatch(dropTargetMarkup, /파일·폴더를 놓아 업로드/);
  assert.match(dropTargetMarkup, /onDragEnter=/);
  assert.match(dropTargetMarkup, /onDragOver=/);
  assert.match(dropTargetMarkup, /onDrop=/);
  assert.doesNotMatch(view, /file-workspace-list-toolbar|file-workspace-list-refresh/);
  assert.doesNotMatch(styles, /\.file-workspace-list-toolbar/);
  assert.match(styles, /\.file-workspace-toolbar \.feature-search\s*\{[^}]*flex:\s*1;/);
  assert.ok(fileButton >= 0 && fileButton < folderButton && folderButton < dropHint);
  assert.match(styles, /\.file-drop-hint\s*\{[^}]*margin-left:\s*auto;[^}]*white-space:\s*nowrap;/s);
});

test("file repository is an explorer and viewer with recursive folder upload", async () => {
  const [view, resizer, styles] = await Promise.all([
    read("../src/components/ProjectFilesView.tsx"),
    read("../src/components/ResizableSplitPane.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(view, /webkitGetAsEntry/);
  assert.match(view, /readDirectoryBatch/);
  assert.match(view, /webkitdirectory/);
  assert.match(view, /file-workspace-explorer/);
  assert.match(view, /file-workspace-viewer/);
  assert.match(view, /renderFilePreview/);
  assert.match(view, /import \{ MarkdownResponse \} from "\.\/ConversationTurn"/);
  assert.match(view, /isMarkdownFile\(detail\)[\s\S]*?<MarkdownResponse text=\{preview\.text\} \/>/);
  assert.match(view, /extension === "md" \|\| extension === "markdown" \|\| detail\.mimeType/);
  assert.match(view, /isMarkdownFile\(detail\) && !markdownSource/);
  assert.match(view, /aria-label=\{markdownSource \? "렌더링 보기" : "원문 보기"\}/);
  assert.match(view, /aria-pressed=\{markdownSource\}/);
  assert.match(view, /markdownSource \? <Eye size=\{14\} \/> : <Code2 size=\{14\} \/>/);
  assert.match(view, /setMarkdownSource\(false\);[\s\S]*?\}, \[selectedId\]\);/);
  assert.match(styles, /\.file-viewer-actions \.file-preview-mode-toggle\.is-active\s*\{[^}]*border-color:\s*var\(--cobalt\);[^}]*background:\s*var\(--cobalt-pale\);/s);
  assert.match(styles, /\.file-preview-markdown\s*\{[^}]*font-size:\s*var\(--conversation-font-size\);/s);
  assert.match(view, /sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads"/);
  assert.doesNotMatch(view, /allow-same-origin/);
  assert.doesNotMatch(view, /folder-reference-note/);
  assert.doesNotMatch(view, /채팅에서 이 폴더를 선택하면/);
  assert.doesNotMatch(view, /새 버전 사유|버전 기록|uploadVersion|currentVersion/);
  assert.match(view, /storageKey="lumina:file-explorer-width"/);
  assert.match(resizer, /window\.localStorage\.setItem/);
});

test("file detail keeps compact metadata immediately before download", async () => {
  const [view, styles] = await Promise.all([
    read("../src/components/ProjectFilesView.tsx"),
    read("../src/styles.css"),
  ]);

  const detailStart = view.indexOf('className="file-viewer-document"');
  const headerStart = view.indexOf('className="file-viewer-heading"', detailStart);
  const headerEnd = view.indexOf("</header>", headerStart);
  const header = view.slice(headerStart, headerEnd);
  const metadata = header.indexOf('className="file-viewer-meta"');
  const download = header.indexOf("void download()");
  const remove = header.indexOf("void remove()");

  assert.ok(detailStart >= 0 && headerStart > detailStart && headerEnd > headerStart);
  assert.match(header, /<h2>\{detail\.displayName\}<\/h2>/);
  assert.doesNotMatch(header, /detail\.logicalPath|detail\.mimeType/);
  assert.match(header, /formatBytes\(detail\.size\)/);
  assert.match(header, /formatDate\(detail\.createdAt\)/);
  assert.ok(metadata >= 0 && metadata < download && download < remove);
  assert.equal((view.match(/className="file-viewer-meta"/g) ?? []).length, 1);
  assert.match(styles, /\.file-viewer-meta\s*\{[^}]*display:\s*inline-flex;[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /\.file-viewer-actions button\s*\{[^}]*flex:\s*0 0 auto;[^}]*white-space:\s*nowrap;/s);
});

test("file explorer supports context actions and drag moves", async () => {
  const [view, api, styles] = await Promise.all([
    read("../src/components/ProjectFilesView.tsx"),
    read("../src/api.ts"),
    read("../src/styles.css"),
  ]);

  assert.match(view, /onContextMenu=\{\(event\) => openContextMenu\(event, node\)\}/);
  assert.match(view, /application\/x-lumina-file-tree/);
  assert.match(view, /void moveTreeNode\(source, node\.path\)/);
  assert.match(view, /새 폴더/);
  assert.match(view, /이름 변경/);
  assert.match(view, /한 번 더 눌러 삭제/);
  assert.match(view, /className="file-tree-editor"/);
  assert.match(view, /<strong>프로젝트 파일<\/strong>/);
  assert.match(view, /aria-label=\{bulkSelectionMode \? "여러 항목 선택 닫기" : "여러 항목 선택"\}/);
  assert.match(view, /bulkDeleteArmed \? <AlertCircle/);
  assert.match(view, /collectSelectedRoots/);
  assert.match(api, /createProjectFolder/);
  assert.match(api, /moveProjectFolder/);
  assert.match(api, /deleteProjectFolder/);
  assert.match(styles, /\.file-tree-context-menu/);
  assert.match(styles, /\.file-tree-context-menu\s*\{[^}]*width:\s*max-content;/s);
  assert.match(styles, /\.file-tree-context-menu button\s*\{[^}]*border:\s*0;/s);
  assert.match(styles, /\.file-tree-context-menu button\s*\{[^}]*background:\s*transparent;/s);
  assert.match(styles, /\.file-tree-context-menu button:hover\s*\{[^}]*background:\s*var\(--surface-soft\);/s);
  assert.match(view, /themeDark:\s*Boolean\(event\.currentTarget\.closest\("\.theme-dark"\)\)/);
  assert.match(view, /className=\{`file-tree-context-menu\$\{contextMenu\.themeDark \? " theme-dark" : ""\}`\}/);
  assert.match(view, /x:\s*Math\.max\(8, Math\.min\(event\.clientX, window\.innerWidth - 190\)\)/);
  assert.match(view, /y:\s*Math\.max\(8, Math\.min\(event\.clientY, window\.innerHeight - 150\)\)/);
  assert.match(styles, /\.file-tree-context-menu\.theme-dark,[\s\S]*?--menu-surface:\s*#121417;/);
  assert.match(styles, /\.file-tree-row\.is-drop-target/);
  assert.match(styles, /\.file-tree-row > span:last-child\s*\{[^}]*font-weight:\s*400;/s);
  assert.match(styles, /\.file-tree-row:is\(\.is-selected, \.is-bulk-selected\) > span:last-child\s*\{[^}]*font-weight:\s*640;/s);
  assert.match(styles, /\.file-explorer-heading-actions/);
  assert.match(styles, /\.file-explorer-heading-actions button\s*\{[^}]*background:\s*transparent;/s);
});

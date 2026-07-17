import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const helpView = readFileSync(new URL("../src/components/HelpCenterView.tsx", import.meta.url), "utf8");
const stylesheet = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");


test("the Help icon sits immediately after the theme control and opens the Help view", () => {
  const themeControl = app.indexOf('aria-label={theme === "dark" ? "Light 테마로 변경" : "Dark 테마로 변경"}');
  const helpControl = app.indexOf('aria-label="사용 안내 열기"');
  const collapseControl = app.indexOf('aria-label="사이드바 접기"');

  assert.ok(themeControl >= 0);
  assert.ok(helpControl > themeControl);
  assert.ok(collapseControl > helpControl);
  assert.match(app, /mainView === "help" && <HelpCenterView canManage=\{isAdmin\} initialAnnouncementId=\{helpAnnouncementId\}/);
});


test("the Help workspace is Markdown-first and hides mutations behind admin capability", () => {
  assert.match(helpView, /help-chat-markdown-body thin-scrollbar[\s\S]*?<MarkdownResponse text=\{selected\.markdownContent\}/);
  assert.match(helpView, /section === "manuals" \? <div className="feature-toolbar help-center-toolbar">[\s\S]*?effectiveCanManage \? <div className="help-create-actions">/);
  assert.match(helpView, /await api\.help\.create/);
  assert.match(helpView, /await api\.help\.update/);
  assert.match(helpView, /await api\.help\.delete/);
  assert.match(helpView, /application\/x-lumina-help-tree/);
  assert.match(helpView, /draggable=\{effectiveCanManage && !busy\}/);
  assert.match(helpView, /void moveHelpItem\(source, node\.item\.id\)/);
  assert.match(helpView, /void moveHelpItem\(source, null\)/);
  assert.match(helpView, /isHelpItemSelfOrDescendant/);
  assert.match(stylesheet, /\.file-tree-row\.is-drop-target/);
  assert.match(stylesheet, /\.file-workspace-explorer\.is-root-drop-target/);
  assert.match(helpView, /deleteArmed \? "한 번 더 눌러 삭제" : "삭제"/);
});


test("the Help workspace combines manuals and announcements with admin-only announcement mutations", () => {
  assert.match(helpView, /type HelpSection = "manuals" \| "announcements"/);
  assert.match(helpView, /aria-label="사용 안내 자료 유형"/);
  assert.match(helpView, /api\.notifications\.listAnnouncements/);
  assert.match(helpView, /api\.admin\.createAnnouncement/);
  assert.match(helpView, /api\.admin\.updateAnnouncement/);
  assert.match(helpView, /api\.admin\.deleteAnnouncement/);
  assert.match(helpView, /announcementDeleteArmed \? "한 번 더 눌러 삭제" : "삭제"/);
  assert.match(helpView, /help-announcement-explorer-controls[\s\S]*?공지 작성[\s\S]*?공지 제목이나 내용 검색[\s\S]*?file-explorer-heading/);
  assert.match(helpView, /본문 Markdown 원문 \(Raw code\)[\s\S]*?<textarea[^>]+spellCheck=\{false\}/);
  assert.match(helpView, /className="help-announcement-body-field"/);
  assert.match(helpView, /help-chat-markdown-body thin-scrollbar[\s\S]*?<MarkdownResponse text=\{selectedAnnouncement\.body\}/);
  assert.match(stylesheet, /\.help-chat-markdown-body > \.markdown-response \{[^}]*max-width: 74ch;[^}]*margin: 0 auto;/);
  assert.match(stylesheet, /\.feature-view\.feature-view \.help-chat-markdown-body \.markdown-response h1 \{ font-size: 1\.42em; \}/);
  assert.match(stylesheet, /\.help-announcement-form \{[^}]*height: 100%/);
  assert.match(stylesheet, /\.help-announcement-form \.help-announcement-body-field \{[^}]*flex: 1;[^}]*grid-template-rows: auto minmax\(0, 1fr\)/);
});

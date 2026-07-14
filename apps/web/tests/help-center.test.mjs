import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const helpView = readFileSync(new URL("../src/components/HelpCenterView.tsx", import.meta.url), "utf8");


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
  assert.match(helpView, /ReactMarkdown remarkPlugins=\{\[remarkGfm\]\}/);
  assert.match(helpView, /effectiveCanManage && section === "manuals" \? <div className="help-create-actions">/);
  assert.match(helpView, /await api\.help\.create/);
  assert.match(helpView, /await api\.help\.update/);
  assert.match(helpView, /await api\.help\.delete/);
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
});

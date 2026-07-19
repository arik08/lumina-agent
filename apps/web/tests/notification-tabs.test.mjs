import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("notification panel separates notifications and announcements with accessible tabs", async () => {
  const [app, stylesheet] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(app, /type NotificationTab = "notifications" \| "announcements"/);
  assert.match(app, /role="tablist" aria-label="받은 소식 분류"/);
  assert.match(app, /aria-controls="notification-panel-notifications"/);
  assert.match(app, /aria-controls="notification-panel-announcements"/);
  assert.match(app, /role="tabpanel"/);
  assert.match(app, /게시된 공지사항이 없습니다\./);
  assert.match(app, /api\.notifications\.listAnnouncements/);
  assert.match(app, /announcements\.map\(\(announcement\)/);
  assert.match(stylesheet, /\.notification-tabs/);
  assert.match(stylesheet, /button\[aria-selected="true"\]/);
  assert.match(stylesheet, /\.announcement-empty/);
});

test("announcement management lives in Help instead of System Admin", async () => {
  const [adminView, helpView, api, stylesheet] = await Promise.all([
    read("../src/components/AdminView.tsx"),
    read("../src/components/HelpCenterView.tsx"),
    read("../src/api.ts"),
    read("../src/styles.css"),
  ]);

  assert.doesNotMatch(adminView, /공지사항/);
  assert.doesNotMatch(adminView, /api\.admin\.(?:list|create|update|delete)Announcement/);
  assert.match(helpView, /공지 작성/);
  assert.match(helpView, /api\.admin\.createAnnouncement/);
  assert.match(helpView, /api\.admin\.updateAnnouncement/);
  assert.match(helpView, /api\.admin\.deleteAnnouncement/);
  assert.match(helpView, /한 번 더 눌러 삭제/);
  assert.match(helpView, /aria-label="사용 안내 자료 유형">\s*<button[^>]+announcements[^>]+>.*?공지사항.*?<button[^>]+manuals[^>]+>.*?매뉴얼/s);
  assert.match(api, /\/admin\/announcements/);
  assert.match(stylesheet, /\.help-announcement-form/);
  assert.match(stylesheet, /\.help-announcement-row/);
  assert.match(stylesheet, /\.announcement-item/);
});

test("announcement summaries link to the selected Help detail", async () => {
  const [app, stylesheet] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(app, /openAnnouncementInHelp\(announcement\.id\)/);
  assert.match(app, /setHelpAnnouncementId\(announcementId\)/);
  assert.match(app, /initialAnnouncementId=\{helpAnnouncementId\}/);
  assert.doesNotMatch(app, /사용 안내에서 자세히 보기/);
  assert.match(stylesheet, /\.chat-actions \.announcement-item \{[^}]*height: auto;[^}]*min-height: 78px/s);
});

test("notification receipt shows more compact title-only rows", async () => {
  const [app, stylesheet] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/styles.css"),
  ]);

  assert.doesNotMatch(app, /notificationContext/);
  assert.doesNotMatch(app, /<small>\{notificationContext/);
  assert.match(stylesheet, /\.notification-panel \{[^}]*width: min\(460px, calc\(100vw - 30px\)\)/s);
  assert.match(stylesheet, /\.notification-list \{ max-height: min\(720px, calc\(100vh - 100px\)\)/);
  assert.match(stylesheet, /\.notification-list \{[^}]*scrollbar-gutter: stable/s);
  assert.match(stylesheet, /\.notification-item \{[^}]*min-height: 40px/s);
});

test("notification trigger does not render an empty tooltip while the panel is open", async () => {
  const [app, stylesheet] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(app, /data-tooltip=\{notificationOpen \? undefined : "알림"\}/);
  assert.match(stylesheet, /\.global-tooltip-layer\s*\{/);
  assert.doesNotMatch(stylesheet, /tooltip-control:not\(\[data-tooltip\]\)::after/);
});

test("notification polling pauses offscreen without overlapping requests", async () => {
  const app = await read("../src/App.tsx");

  assert.match(app, /let refreshing = false;[\s\S]*?const refresh = async \(\) => \{\s*if \(refreshing\) return;/);
  assert.match(app, /const refreshWhenVisible = \(\) => \{\s*if \(document\.visibilityState === "visible"\) void refresh\(\);/);
  assert.match(app, /window\.setInterval\(refreshWhenVisible, 30_000\)/);
  assert.match(app, /document\.addEventListener\("visibilitychange", refreshWhenVisible\)/);
  assert.match(app, /document\.removeEventListener\("visibilitychange", refreshWhenVisible\)/);
});

test("notification trigger separates unread notifications and announcements", async () => {
  const [app, stylesheet] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(app, /notificationUnreadCount > 0 \|\| announcementUnreadCount > 0/);
  assert.match(app, /notification-trigger-count is-notification/);
  assert.match(app, /notification-trigger-count is-announcement/);
  assert.match(app, /announcementUnreadCount > 0 && <span>/);
  assert.match(stylesheet, /\.notification-trigger\.has-counts \{[^}]*width: auto;/s);
  assert.doesNotMatch(stylesheet, /\.notification-trigger\.has-counts \{[^}]*border:/s);
  assert.match(stylesheet, /\.notification-trigger-count \{[^}]*font-weight: 400;/s);
  assert.match(stylesheet, /\.notification-trigger-count\.is-announcement/);
});

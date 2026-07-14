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

test("admin view provides inline announcement create edit and two-step delete", async () => {
  const [view, api, stylesheet] = await Promise.all([
    read("../src/components/AdminView.tsx"),
    read("../src/api.ts"),
    read("../src/styles.css"),
  ]);

  assert.match(view, /공지 작성/);
  assert.match(view, /api\.admin\.createAnnouncement/);
  assert.match(view, /api\.admin\.updateAnnouncement/);
  assert.match(view, /announcementDeleteArmedId !== announcement\.id/);
  assert.match(view, /한 번 더 눌러 삭제/);
  assert.match(api, /\/admin\/announcements/);
  assert.match(stylesheet, /\.admin-announcement-form/);
  assert.match(stylesheet, /\.admin-announcement-row/);
  assert.match(stylesheet, /\.announcement-item/);
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

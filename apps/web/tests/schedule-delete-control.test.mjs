import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("scheduled tasks expose an inline two-step delete control", async () => {
  const [view, api, styles] = await Promise.all([
    read("../src/components/SchedulesView.tsx"),
    read("../src/api.ts"),
    read("../src/styles.css"),
  ]);

  assert.match(api, /request<void>\(`\/scheduled-tasks\/\$\{encodeURIComponent\(taskId\)\}`,[\s\S]*?method: "DELETE"/);
  assert.match(api, /schedules:\s*\{[\s\S]*?delete: deleteScheduledTask/);
  assert.match(view, /deleteConfirmId !== selected\.id[\s\S]*?setDeleteConfirmId\(selected\.id\)/);
  assert.match(view, /await api\.schedules\.delete\(selected\.id\)/);
  assert.match(view, /"한 번 더 눌러 삭제"/);
  assert.match(view, /"삭제 실패, 다시 시도"/);
  assert.match(styles, /\.detail-actions \.is-danger\.is-confirming\s*\{/);
});

test("schedule creation and refresh actions stay with the left task list", async () => {
  const [view, styles] = await Promise.all([
    read("../src/components/SchedulesView.tsx"),
    read("../src/styles.css"),
  ]);

  const headerStart = view.indexOf('className="feature-header"');
  const headerEnd = view.indexOf("</header>", headerStart);
  const listStart = view.indexOf('className="feature-list schedule-list"');
  const toolbarStart = view.indexOf('className="feature-toolbar schedule-list-toolbar"');
  const emptyState = view.indexOf("예약 작업이 없습니다.");

  assert.ok(headerStart >= 0 && headerEnd > headerStart);
  assert.doesNotMatch(view.slice(headerStart, headerEnd), /새 예약|새로 고침/);
  assert.ok(listStart >= 0 && listStart < toolbarStart && toolbarStart < emptyState);
  assert.match(styles, /\.schedule-list-toolbar\s*\{[^}]*position:\s*sticky;/);
});

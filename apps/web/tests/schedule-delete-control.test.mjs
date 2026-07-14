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

test("schedule creation and refresh actions stay at the right of the header", async () => {
  const view = await read("../src/components/SchedulesView.tsx");

  const headerStart = view.indexOf('className="feature-header"');
  const headerEnd = view.indexOf("</header>", headerStart);
  const listStart = view.indexOf('className="feature-list schedule-list"');
  const createAction = view.indexOf('className="feature-primary-action lumina-primary-action"', headerStart);
  const refreshAction = view.indexOf('className="schedule-list-refresh"', headerStart);
  const emptyState = view.indexOf("예약 작업이 없습니다.");

  assert.ok(headerStart >= 0 && headerEnd > headerStart);
  assert.ok(headerStart < createAction && createAction < refreshAction && refreshAction < headerEnd);
  assert.ok(listStart >= 0 && listStart < emptyState);
  assert.doesNotMatch(view.slice(listStart, emptyState), /새 예약|새로 고침|schedule-list-toolbar/);
});

test("running a scheduled task refreshes the sidebar conversation list immediately", async () => {
  const [view, app, workspace] = await Promise.all([
    read("../src/components/SchedulesView.tsx"),
    read("../src/App.tsx"),
    read("../src/use-lumina-workspace.ts"),
  ]);

  assert.match(view, /onConversationsChanged:\s*\(\)\s*=>\s*Promise<unknown>/);
  assert.match(view, /await api\.schedules\.runNow\(selected\.id\)[\s\S]*?await onConversationsChanged\(\)/);
  assert.match(app, /<SchedulesView[\s\S]*?onConversationsChanged=\{workspace\.refreshConversations\}/);
  assert.match(workspace, /return\s*\{[\s\S]*?refreshConversations,/);
});

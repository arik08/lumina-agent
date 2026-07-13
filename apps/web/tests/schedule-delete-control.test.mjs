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

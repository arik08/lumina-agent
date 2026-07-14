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

test("schedule creation lives in the left list and replaces the detail panel", async () => {
  const [view, styles] = await Promise.all([
    read("../src/components/SchedulesView.tsx"),
    read("../src/styles.css"),
  ]);

  const headerStart = view.indexOf('className="feature-header"');
  const headerEnd = view.indexOf("</header>", headerStart);
  const listStart = view.indexOf('className="feature-list schedule-list"');
  const toolbarStart = view.indexOf('className="feature-toolbar schedule-list-toolbar"', listStart);
  const toolbarEnd = view.indexOf("</div>", toolbarStart);
  const createAction = view.indexOf('className="feature-primary-action lumina-primary-action"', toolbarStart);
  const refreshAction = view.indexOf('className="schedule-list-refresh"', headerStart);
  const detailStart = view.indexOf('className="feature-detail schedule-detail"');
  const createBranch = view.indexOf("{createOpen ? (", detailStart);
  const formStart = view.indexOf('className="compact-form schedule-form schedule-detail-form"', detailStart);

  assert.ok(headerStart >= 0 && headerEnd > headerStart);
  assert.ok(headerStart < refreshAction && refreshAction < headerEnd);
  assert.ok(createAction > headerEnd);
  assert.ok(listStart < toolbarStart && toolbarStart < createAction && createAction < toolbarEnd);
  assert.ok(detailStart < createBranch && createBranch < formStart);
  assert.doesNotMatch(view, /feature-inline-dialog" role="dialog"/);
  assert.match(view, /setSelectedId\(task\.id\);\s*setCreateOpen\(false\);/);
  assert.match(styles, /\.schedule-list-toolbar\s*\{[^}]*justify-content:\s*flex-end;/);
  assert.match(styles, /\.schedule-list-toolbar \.feature-primary-action\s*\{[^}]*width:\s*100%;[^}]*justify-content:\s*center;/);
  assert.match(styles, /\.schedule-form\.schedule-detail-form\s*\{[^}]*padding:\s*0;/);
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

test("new schedules choose an independent execution from admin-enabled models", async () => {
  const [view, app] = await Promise.all([
    read("../src/components/SchedulesView.tsx"),
    read("../src/App.tsx"),
  ]);

  const candidateBlock = app.slice(app.indexOf("const candidateModelOptions"), app.indexOf("const selectedCandidateId"));
  assert.match(candidateBlock, /workspace\.providerModels\[provider\.id\]/);
  assert.doesNotMatch(candidateBlock, /modelCandidates/);
  assert.match(app, /<SchedulesView[\s\S]*?executionOptions=\{candidateModelOptions\}/);
  assert.match(view, /setDraftExecution\(defaultScheduleExecution\(execution, executionOptions\)\)/);
  assert.match(view, /ariaLabel="예약 Provider"/);
  assert.match(view, /ariaLabel="예약 Model"/);
  assert.match(view, /ariaLabel="예약 Effort"/);
  assert.match(view, /execution: draftExecution/);
});

test("new schedules choose the project where each session is saved", async () => {
  const [view, app] = await Promise.all([
    read("../src/components/SchedulesView.tsx"),
    read("../src/App.tsx"),
  ]);

  assert.match(app, /<SchedulesView[\s\S]*?projects=\{workspace\.projects\}/);
  assert.match(app, /<SchedulesView[\s\S]*?onProjectChange=\{workspace\.setActiveProjectId\}/);
  assert.match(view, /setDraftProjectId\(projectId \?\? projects\[0\]\?\.id \?\? null\)/);
  assert.match(view, /ariaLabel="예약 작업 세션 저장 프로젝트"/);
  assert.match(view, /projectId: draftProjectId/);
  assert.match(view, /created\.projectId !== projectId[\s\S]*?onProjectChange\(created\.projectId\)/);
  assert.match(view, /선택한 프로젝트에 새 채팅을 만들고 결과를 저장합니다\./);
});

test("weekly schedule controls keep weekday before hour with balanced widths", async () => {
  const [view, styles] = await Promise.all([
    read("../src/components/SchedulesView.tsx"),
    read("../src/styles.css"),
  ]);

  const timingStart = view.indexOf('className="schedule-form-row"');
  const timingEnd = view.indexOf('className="schedule-execution-row"', timingStart);
  const timingControls = view.slice(timingStart, timingEnd);
  assert.ok(timingControls.indexOf("예약 요일") < timingControls.indexOf('<span>시</span>'));
  assert.match(styles, /\.schedule-form-row\s*\{[^}]*repeat\(auto-fit, minmax\(92px, 1fr\)\)/);
});

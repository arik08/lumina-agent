import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { mergedToolActiveDurationMs, progressStageDurationById } from "../src/run-activity-duration.ts";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("stage durations cover the complete run instead of only tool execution time", () => {
  const startedAtMs = Date.parse("2026-07-12T15:17:05.256Z");
  const finishedAtMs = Date.parse("2026-07-12T15:22:47.876Z");
  const stages = [
    { id: "one", createdAt: "2026-07-12T15:17:05.273Z" },
    { id: "two", createdAt: "2026-07-12T15:17:46.232Z" },
    { id: "three", createdAt: "2026-07-12T15:18:07.219Z" },
    { id: "four", createdAt: "2026-07-12T15:18:38.647Z" },
    { id: "five", createdAt: "2026-07-12T15:19:01.885Z" },
    { id: "six", createdAt: "2026-07-12T15:19:29.160Z" },
    { id: "seven", createdAt: "2026-07-12T15:22:08.529Z" },
  ];

  const durations = progressStageDurationById(stages, startedAtMs, finishedAtMs);
  const totalDurationMs = [...durations.values()].reduce((total, duration) => total + duration, 0);

  assert.equal(totalDurationMs, finishedAtMs - startedAtMs);
  assert.equal(durations.get("six"), Date.parse(stages[6].createdAt) - Date.parse(stages[5].createdAt));
  assert.equal(durations.get("seven"), finishedAtMs - Date.parse(stages[6].createdAt));
});

test("an invalid run start falls back to the first persisted stage timestamp", () => {
  const stages = [
    { id: "one", createdAt: "2026-07-12T15:17:05.273Z" },
    { id: "two", createdAt: "2026-07-12T15:17:46.232Z" },
  ];

  const durations = progressStageDurationById(stages, Number.NaN, Date.parse("2026-07-12T15:18:00.000Z"));

  assert.equal(durations.get("one"), Date.parse(stages[1].createdAt) - Date.parse(stages[0].createdAt));
});

test("group wall time is shown once while expanded tools keep their own execution time", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /tool-call-group-duration" title="단계 전체 소요 시간"/);
  assert.doesNotMatch(app, /displayDurationMs=\{/);
});

test("a stage with one timed child hides the duplicate parent duration", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /const timedChildCount = toolActivities\.length \+ \(hasModelProcessingRow \? 1 : 0\)/);
  assert.match(app, /const showStageDuration = timedChildCount !== 1/);
  assert.match(app, /\{showStageDuration && <span className="progress-summary-duration"/);
});

test("model-selected skills enter the live timeline only through a selection event", async () => {
  const apiTypes = await read("../src/api-types.ts");
  const workspace = await read("../src/use-lumina-workspace.ts");
  const turn = await read("../src/components/ConversationTurn.tsx");

  assert.match(apiTypes, /RunEventEnvelope<"skill_selected"/);
  assert.match(workspace, /event\.type === "skill_selected"/);
  assert.match(workspace, /\{ \.\.\.event\.payload\.activity, sequence: event\.sequence \}/);
  assert.match(turn, /skill\.appliedBy === "auto" \? "AI 선택"/);
});

test("parallel tool intervals are merged before calculating non-tool model time", () => {
  const stageStartedAtMs = Date.parse("2026-07-12T15:18:38.647Z");
  const stageFinishedAtMs = Date.parse("2026-07-12T15:19:01.885Z");
  const executions = [
    { startedAt: "2026-07-12T15:18:38.656Z", completedAt: "2026-07-12T15:18:39.317Z" },
    { startedAt: "2026-07-12T15:18:38.669Z", completedAt: "2026-07-12T15:18:39.102Z" },
    { startedAt: "2026-07-12T15:18:39.116Z", completedAt: "2026-07-12T15:18:39.543Z" },
    { startedAt: "2026-07-12T15:18:39.227Z", completedAt: "2026-07-12T15:18:39.654Z" },
  ];

  const toolActiveDurationMs = mergedToolActiveDurationMs(executions, stageStartedAtMs, stageFinishedAtMs);

  assert.equal(toolActiveDurationMs, 998);
  assert.equal(stageFinishedAtMs - stageStartedAtMs - toolActiveDurationMs, 22_240);
});

test("non-tool time is rendered as a model processing row with a clear explanation", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /<ModelProcessingRow[\s\S]*durationMs=\{modelProcessingDurationMs\}/);
  assert.match(app, /Provider 요청 전송 · 응답 수신/);
  assert.match(app, /모델 요청 전송부터 응답 수신·처리까지의 시간\(도구 실행 제외\)/);
});

test("model processing expands to the actual persisted exchange instead of token totals", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /className=\{`tool-call-trigger model-processing-row/);
  assert.match(app, /aria-expanded=\{isOpen\}/);
  assert.match(app, /실제 교환 정보/);
  assert.match(app, /Provider로 보냄/);
  assert.match(app, /Provider에서 받음/);
  assert.doesNotMatch(app, /화면에 저장된 실제 사용자 메시지/);
  assert.doesNotMatch(app, /현재 Run 누적 토큰/);
});

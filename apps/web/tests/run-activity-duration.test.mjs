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

test("group heading shows only merged tool time while model time has its own row", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /const toolGroupDurationMs = stageTiming/);
  assert.match(app, /tool-call-group-duration" data-tooltip="도구 실행 시간"/);
  assert.match(app, /formatDuration\(toolGroupDurationMs\)/);
  assert.doesNotMatch(app, /formatDuration\(stageDurationMs \?\? toolCallGroupDuration/);
});

test("a stage hides its parent duration whenever timed child rows already account for it", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /const timedChildCount = toolActivities\.length \+ \(hasModelProcessingRow \? 1 : 0\)/);
  assert.match(app, /const showStageDuration = timedChildCount === 0/);
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
  assert.match(app, /모델 판단 · 내부 실행 합계/);
  assert.match(app, /여러 모델 호출과 Skill·계획 처리, 재시도 시간을 합산한 값\(외부 도구 실행 제외\)/);
  assert.doesNotMatch(app, /Provider 요청 전송 · 응답 수신/);
});

test("cancelled runs stop active Thinking and tool rows with explicit feedback", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /awaitingInput \? "Q&A" : "Thinking"/);
  assert.match(app, /state === "stopped" \? "사용자 요청으로 모델 처리를 중지했습니다\."/);
  assert.match(app, /state === "failed" \? "실패" : "중지됨"/);
  assert.match(app, /const stoppedByRun = executionActive && \(runOutcome === "stopped" \|\| runOutcome === "failed"\)/);
  assert.match(app, /stoppedByRun \? \(runOutcome === "failed" \? "실패" : "중지됨"\)/);
  assert.match(app, /요청에 따라 작업을 중지했습니다\./);
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

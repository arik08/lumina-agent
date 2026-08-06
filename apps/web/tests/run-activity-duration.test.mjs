import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { formatDuration, mergedToolActiveDurationMs, progressStageDurationById } from "../src/run-activity-duration.ts";

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

test("live durations keep zeroed decimals while completed durations keep measured precision", () => {
  assert.equal(formatDuration(13_140, true), "13.00초");
  assert.equal(formatDuration(13_140), "13.14초");
  assert.equal(formatDuration(null, true), "—");
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
  assert.match(app, /formatDuration\(toolGroupDurationMs, toolGroupRunning\)/);
  assert.doesNotMatch(app, /formatDuration\(stageDurationMs \?\? toolCallGroupDuration/);
});

test("tool and model durations never wrap between the number and seconds unit", async () => {
  const styles = await read("../src/styles.css");

  assert.match(styles, /\.tool-call-duration \{[^}]*white-space: nowrap;/);
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

test("non-tool time is rendered as a user-facing answer preparation row", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /<ModelProcessingRow[\s\S]*durationMs=\{modelProcessingDurationMs\}/);
  assert.match(app, /const modelProcessingRunning = timelineRunning[\s\S]*&& !toolGroupRunning/);
  assert.match(app, /!timelineRunning && summary\?\.id === latestProgressSummaryId[\s\S]*\? runOutcome[\s\S]*: "completed"/);
  assert.match(app, /hasModelProcessingRow && toolGroupRunning[\s\S]*<ModelProcessingRow[\s\S]*toolActivities\.map/);
  assert.match(app, /toolActivities\.map[\s\S]*hasModelProcessingRow && !toolGroupRunning[\s\S]*<ModelProcessingRow/);
  assert.match(app, /답변을 준비하고 있습니다\./);
  assert.match(app, /답변을 준비했습니다\./);
  assert.doesNotMatch(app, /모델 판단 · 내부 실행 합계/);
  assert.doesNotMatch(app, /내부 추론 \$\{reasoningTokens\.toLocaleString\(\)\} 토큰/);
  assert.match(app, /여러 모델 호출과 Skill·계획 처리, 재시도 시간을 합산한 값\(외부 도구 실행 제외\)/);
  assert.doesNotMatch(app, /Provider 응답/);
});

test("provider waits and retries stay internal while the user sees a stable processing state", async () => {
  const apiTypes = await read("../src/api-types.ts");
  const workspace = await read("../src/use-lumina-workspace.ts");
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(apiTypes, /RunEventEnvelope<"provider_activity_changed", ProviderActivity>/);
  assert.match(apiTypes, /RunEventEnvelope<"provider_retry_scheduled", Omit<ProviderRetry, "createdAt">>/);
  assert.match(workspace, /event\.type === "provider_activity_changed"/);
  assert.match(workspace, /event\.type === "provider_retry_scheduled"/);
  assert.match(app, /const statusLabel = running[\s\S]*\? "처리 중"/);
  assert.doesNotMatch(app, /Provider 첫 응답 대기 · 시도/);
  assert.doesNotMatch(app, /다음 이벤트 .*초 남음 \(무응답 시 자동 재시도\)/);
  assert.doesNotMatch(app, /재시도 대기/);
  assert.doesNotMatch(app, /자동 재시도 \$\{providerRetries\.length\}회 포함/);
});

test("search engine implementation names are normalized in visible tool text", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");
  const userFacingText = await read("../src/user-facing-system-text.ts");

  assert.match(userFacingText, /replace\(\/duckduckgo\(\?:_html\)\?\/gi, "검색"\)/);
  assert.match(app, /userFacingSystemText\(formatModelExchangeValue\(value\)\)/);
  assert.match(app, /userFacingSystemText\(activity\.execution\.resultSummary\[0\]\)/);
});

test("provider-only progress summaries are rewritten around the user task", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");
  const userFacingText = await read("../src/user-facing-system-text.ts");

  assert.match(userFacingText, /Provider가 빈 응답을 반환해/);
  assert.match(userFacingText, /return "답변을 계속 준비하고 있습니다\."/);
  assert.match(app, /userFacingSystemText\(summary\.text\)/);
});

test("cancelled runs stop active answer preparation and tool rows with explicit feedback", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /awaitingInput \? "Q&A" : "답변 준비"/);
  assert.match(app, /state === "stopped" \? "요청에 따라 답변 준비를 중지했습니다\."/);
  assert.match(app, /state === "failed" \? "실패" : "중지됨"/);
  assert.match(app, /const stoppedByRun = executionActive && \(runOutcome === "stopped" \|\| runOutcome === "failed"\)/);
  assert.match(app, /stoppedByRun \? \(runOutcome === "failed" \? "실패" : "중지됨"\)/);
  assert.match(app, /요청에 따라 작업을 중지했습니다\./);
});

test("answer preparation expands to user-facing persisted exchange details", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /className=\{`tool-call-trigger model-processing-row/);
  assert.match(app, /aria-expanded=\{isOpen\}/);
  assert.match(app, /처리 세부 정보/);
  assert.match(app, /모델에 전달한 내용/);
  assert.match(app, /모델이 반환한 내용/);
  assert.doesNotMatch(app, /화면에 저장된 실제 사용자 메시지/);
  assert.doesNotMatch(app, /현재 Run 누적 토큰/);
});

test("expanded model processing closes when the surrounding blank area is pressed", async () => {
  const app = await read("../src/components/ConversationTurn.tsx");

  assert.match(app, /const rootRef = useRef<HTMLDivElement>\(null\);/);
  assert.match(app, /if \(!isOpen\) return;[\s\S]*document\.addEventListener\("pointerdown", closeOnOutsidePointer\)/);
  assert.match(app, /event\.target instanceof Node && !rootRef\.current\?\.contains\(event\.target\)/);
  assert.match(app, /model-processing-call[\s\S]*ref=\{rootRef\}/);
});

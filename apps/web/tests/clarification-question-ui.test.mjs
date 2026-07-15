import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const cardSource = readFileSync(
  new URL("../src/components/UserInputRequestCard.tsx", import.meta.url),
  "utf8",
);
const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const workspaceSource = readFileSync(
  new URL("../src/use-lumina-workspace.ts", import.meta.url),
  "utf8",
);
const turnSource = readFileSync(
  new URL("../src/components/ConversationTurn.tsx", import.meta.url),
  "utf8",
);
const stylesheet = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("clarification card identifies questions and supports objective, custom, and AI answers", () => {
  assert.match(cardSource, /MessageCircleQuestion/);
  assert.match(cardSource, /질문 \{index \+ 1\} \/ \{request\.questions\.length\}/);
  assert.match(cardSource, /직접 답변하기/);
  assert.match(cardSource, /clarification-header-actions[\s\S]*AI가 판단[\s\S]*clarification-settings-trigger/);
  assert.doesNotMatch(cardSource, /이번에는 AI가 판단/);
  assert.match(cardSource, /updateCustomText\(question\.id, event\.currentTarget\.value\)/);
  assert.doesNotMatch(cardSource, /setCustomText\(\(current\)[\s\S]{0,120}event\.currentTarget\.value/);
  assert.match(cardSource, /request\.questions\.every/);
  assert.match(cardSource, /onSubmit\(orderedAnswers\)/);
  assert.match(cardSource, /is-collapsing/);
  assert.match(cardSource, /답변한 확인 질문 다시 보기/);
  assert.match(cardSource, /다시 접기/);
  assert.match(turnSource, /inputRequestActivity[\s\S]*<UserInputRequestCard/);
  assert.doesNotMatch(turnSource, /assistant-content">[\s\S]{0,300}inputRequests/);
  assert.match(stylesheet, /\.run-activity-timeline \.clarification-card \{[^}]*margin: 3px 0 1px/);
  assert.match(stylesheet, /\.clarification-question:disabled :is\(button, input\) \{ opacity: 0\.78; \}/);
});

test("awaiting clarification is shown as Q&A and freezes the model-work clock", () => {
  assert.match(turnSource, /status === "awaiting_input"/);
  assert.match(turnSource, /awaitingInput \? "Q&A" : "Thinking"/);
  assert.match(turnSource, /확인 질문 · 사용자 답변 대기/);
  assert.match(turnSource, /awaitingInput && Number\.isFinite\(inputWaitStartedAtMs\)/);
  assert.match(turnSource, /timelineRunning=\{!terminal && !awaitingInput\}/);
});

test("clarification mode is an account setting available in settings and the question card", () => {
  assert.match(appSource, /AI 확인 질문/);
  assert.match(appSource, /계정 기본값으로 계속 적용됩니다/);
  assert.match(appSource, /selectClarificationMode/);
  assert.match(cardSource, /AI가 되묻는 정도/);
  assert.match(cardSource, /data-tooltip="질문 깊이 설정"/);
  assert.match(cardSource, /알아서 진행/);
  assert.match(cardSource, /균형 있게/);
  assert.match(cardSource, /먼저 확인/);
  assert.match(workspaceSource, /type: "submit_user_input"/);
});

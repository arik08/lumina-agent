import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("composer keeps model controls intact and sends independent analysis and answer options", async () => {
  const [app, workspace, types] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/use-lumina-workspace.ts"),
    read("../src/api-types.ts"),
  ]);

  assert.match(app, /menuLabel="분석 범위"/);
  assert.match(app, /menuLabel="답변 분량"/);
  assert.match(app, /triggerLabel: "분석 자동"/);
  assert.match(app, /triggerLabel: "답변 자동"/);
  assert.match(app, /<ArtifactLengthSlider[\s\S]*?disabled=\{workspace\.settings\?\.outputMode === "chat"\}/);
  assert.match(app, /<ComposerPicker[\s\S]*?controlClassName="model-control"[\s\S]*?<ComposerPicker[\s\S]*?controlClassName="effort-control"/);
  assert.match(workspace, /analysisDepth: AnalysisDepth = "auto"/);
  assert.match(workspace, /answerLength: AnswerLength = "auto"/);
  assert.match(workspace, /outputMode: currentSettings\.outputMode,[\s\S]*?analysisDepth,[\s\S]*?answerLength/);
  assert.match(types, /analysisDepth: AnalysisDepth/);
  assert.match(types, /answerLength: AnswerLength/);
});

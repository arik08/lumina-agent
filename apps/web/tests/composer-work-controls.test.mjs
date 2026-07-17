import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("composer keeps model controls intact and sends independent analysis and answer options", async () => {
  const [app, styles, workspace, types] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/styles.css"),
    read("../src/use-lumina-workspace.ts"),
    read("../src/api-types.ts"),
  ]);

  assert.match(app, /menuLabel="분석 범위"/);
  assert.match(app, /menuLabel="답변 분량"/);
  assert.match(app, /menuDescription="웹 검색과 자료 확인을 포함해 어디까지 분석할지 정합니다\."/);
  assert.match(app, /menuDescription="채팅에 표시할 최종 답변의 분량을 정합니다\."/);
  assert.match(app, /controlClassName=\{`analysis-depth-control is-\$\{analysisDepth\}`\}[\s\S]*?triggerIcon=\{<Search[\s\S]*?hideChevron/);
  assert.match(app, /controlClassName=\{`answer-length-control is-\$\{answerLength\}`\}[\s\S]*?triggerIcon=\{<AlignLeft[\s\S]*?hideChevron/);
  assert.match(styles, /\.is-auto, \.is-brief\) \{ color: var\(--muted\); \}/);
  assert.match(styles, /\.is-standard \{ color: var\(--ink\); \}/);
  assert.match(styles, /\.composer-footer \{ --artifact-length-warning: oklch\(62% 0\.18 52\);/);
  assert.match(styles, /\.analysis-depth-control\.is-deep, \.answer-length-control\.is-detailed\) \{ color: var\(--artifact-length-warning\); \}/);
  assert.match(app, /id: "brief", label: "간단"/);
  assert.match(app, /id: "standard", label: "충분"/);
  assert.match(app, /id: "detailed", label: "상세"/);
  assert.match(app, /analysis-depth-control is-\$\{analysisDepth\}[\s\S]*?answer-length-control is-\$\{answerLength\}[\s\S]*?<ArtifactLengthSlider/);
  assert.doesNotMatch(app, /triggerLabel: "분석/);
  assert.doesNotMatch(app, /triggerLabel: "답변/);
  assert.doesNotMatch(app, /tooltip="웹 검색과 자료 확인을 포함한 분석 범위"/);
  assert.doesNotMatch(app, /tooltip="채팅에 표시할 최종 답변 분량"/);
  assert.doesNotMatch(app, /composer-picker\.is-open \.composer-picker-trigger > svg/);
  assert.doesNotMatch(app, /className="output-mode-toggle"/);
  assert.equal((app.match(/className="composer-utility-button(?: tooltip-control)?"/g) ?? []).length, 3);
  assert.match(styles, /\.composer-footer \.composer-utility-button \{ color: var\(--muted\); \}/);
  assert.match(app, /artifact-output-mode-value is-\$\{outputMode\}/);
  assert.match(styles, /\.artifact-output-mode-value\.is-chat \{ color: var\(--ink\); \}/);
  assert.match(styles, /\.artifact-output-mode-value\.is-file \{ color: var\(--artifact-length-warning\); \}/);
  assert.match(app, /outputMode=\{workspace\.settings\?\.outputMode \?\? "auto"\}/);
  assert.match(app, /disabled=\{outputMode === "chat"\}/);
  assert.match(styles, /\.artifact-output-mode-picker > div \{[^}]*border: 1px solid var\(--line\)/);
  assert.match(styles, /\.artifact-output-mode-picker > span \{[^}]*font-size: 12\.5px/);
  assert.match(app, /triggerRect\.left \+ \(triggerRect\.width - popoverRect\.width\) \/ 2/);
  assert.match(styles, /\.composer-picker:has\(\.analysis-depth-control\) \.composer-picker-menu,[\s\S]*?left: 50%; transform: translateX\(-50%\)/);
  assert.match(app, /<ComposerPicker[\s\S]*?controlClassName="model-control"[\s\S]*?<ComposerPicker[\s\S]*?controlClassName="effort-control"/);
  assert.match(workspace, /analysisDepth: AnalysisDepth = "auto"/);
  assert.match(workspace, /answerLength: AnswerLength = "auto"/);
  assert.match(workspace, /outputMode: currentSettings\.outputMode,[\s\S]*?analysisDepth,[\s\S]*?answerLength/);
  assert.match(types, /analysisDepth: AnalysisDepth/);
  assert.match(types, /answerLength: AnswerLength/);
});

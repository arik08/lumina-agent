import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("composer keeps model controls intact and sends independent analysis and answer options", async () => {
  const [rawApp, controls, styles, workspace, types] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/components/ComposerControls.tsx"),
    read("../src/styles.css"),
    read("../src/use-lumina-workspace.ts"),
    read("../src/api-types.ts"),
  ]);
  const app = `${rawApp}\n${controls}`;

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
  assert.match(app, /className="composer-utility-button tooltip-control" aria-label="파일 첨부" data-tooltip="업로드"/);
  assert.match(app, /className="composer-utility-button tooltip-control" aria-label="Context 연결" data-tooltip="참고문서"/);
  assert.match(app, /className="composer-utility-button tooltip-control" aria-label="Skill 및 MCP 호출" data-tooltip="Skill \/ MCP"/);
  assert.match(app, /composerTrigger\.trigger === "@" \? "파일, 폴더 및 Artifact 후보"/);
  assert.match(styles, /\.composer-footer \.composer-utility-button \{ color: var\(--muted\); \}/);
  assert.match(styles, /\.chat-pane\.view-chat :is\(\.composer-reference, \.composer-attachment\) strong \{[^}]*font-size: calc\(var\(--conversation-font-size\) - 2px\);/);
  assert.doesNotMatch(app, /<strong>\{item\.token\}<\/strong><small>\{item\.subtitle\}<\/small>/);
  assert.match(app, /attachment\.kind === "image"[\s\S]*?composer-attachment-preview[\s\S]*?setPreviewComposerAttachment\(attachment\)/);
  assert.match(app, /attachment\.kind === "pasted_text"[\s\S]*?composer-attachment-preview[\s\S]*?setPreviewComposerTextAttachment\(attachment\)/);
  assert.match(styles, /\.composer-attachment \{[^}]*background: var\(--cobalt-pale\);/);
  assert.match(styles, /\.theme-dark :is\(\.composer-reference, \.composer-attachment\) \{ background: #26334d; color: #c8d6f5; \}/);
  assert.match(styles, /\.model-control, \.composer-footer \.effort-control \{[^}]*color: var\(--muted\)/);
  assert.match(styles, /\.composer-footer \.effort-control \{ font-weight: 700; \}/);
  assert.match(app, /controlClassName=\{`effort-control is-\$\{workspace\.settings\?\.execution\.effortId \?\? "auto"\}`\}/);
  assert.match(styles, /\.composer-footer \.effort-control\.is-medium \{ color: var\(--ink\); \}/);
  assert.match(styles, /\.composer-footer \.effort-control\.is-high \{ color: var\(--artifact-length-warning\); \}/);
  assert.match(app, /artifact-output-mode-value is-\$\{outputMode\}/);
  assert.match(styles, /\.artifact-output-mode-value\.is-chat \{ color: var\(--ink\); \}/);
  assert.match(styles, /\.artifact-output-mode-value\.is-file \{ color: var\(--artifact-length-warning\); \}/);
  assert.match(app, /outputMode=\{workspace\.settings\?\.outputMode \?\? "auto"\}/);
  assert.match(app, /disabled=\{outputMode === "chat"\}/);
  assert.match(styles, /\.artifact-output-mode-picker > div \{[^}]*border: 1px solid var\(--line\)/);
  assert.match(styles, /\.artifact-output-mode-picker > span \{[^}]*font-size: 12\.5px/);
  assert.match(app, /triggerRect\.left \+ \(triggerRect\.width - popoverRect\.width\) \/ 2/);
  assert.match(styles, /\.composer-picker:has\(\.analysis-depth-control\) \.composer-picker-menu,[\s\S]*?left: 50%; transform: translateX\(-50%\)/);
  assert.match(styles, /@container composer \(max-width: 560px\) \{[\s\S]*?\.chat-pane\.view-chat \.composer-footer \.artifact-length-control \{ display: none; \}/);
  assert.match(styles, /@container composer \(max-width: 500px\) \{[\s\S]*?\.composer-picker:has\(\.answer-length-control\) \{ display: none; \}/);
  assert.match(styles, /@container composer \(max-width: 440px\) \{[\s\S]*?\.composer-picker:has\(\.analysis-depth-control\) \{ display: none; \}/);
  assert.match(styles, /@container composer \(max-width: 380px\) \{[\s\S]*?\.prompt-enhancement-picker \{ display: none; \}/);
  assert.match(app, /<ComposerPicker[\s\S]*?controlClassName="model-control"[\s\S]*?<ComposerPicker[\s\S]*?controlClassName=\{`effort-control/);
  assert.match(app, /contextInputLimit: model\.capabilities\.contextInputLimit \?\? model\.capabilities\.contextWindow/);
  assert.match(app, /saveAdminContextCapacityMode[\s\S]*?setAdminSettingsModels[\s\S]*?await workspace\.refreshProviderCatalog\(\)/);
  assert.match(app, /<ContextUsageIndicator[\s\S]*?usedTokens=\{latestContextInputTokens\}[\s\S]*?contextWindow=\{selectedCandidate\.contextInputLimit\}[\s\S]*?<ComposerPicker[\s\S]*?controlClassName="model-control"/);
  assert.match(app, /activeRun\?\.modelTurnMetrics\.at\(-1\)\?\.inputTokens \?\? 0/);
  assert.match(app, /컨텍스트 길이[\s\S]*?usagePercent[\s\S]*?remainingPercent[\s\S]*?formatContextTokens\(safeUsedTokens\)[\s\S]*?formatContextTokens\(contextWindow\)/);
  assert.match(styles, /\.composer-footer \.context-usage-trigger \{[^}]*width: 31px;[^}]*color: var\(--muted\)/);
  assert.match(styles, /\.context-usage-popover \{[^}]*background: var\(--menu-surface\)[^}]*text-align: center/);
  assert.match(workspace, /analysisDepth: AnalysisDepth = "auto"/);
  assert.match(workspace, /answerLength: AnswerLength = "auto"/);
  assert.match(workspace, /outputMode: currentSettings\.outputMode,[\s\S]*?analysisDepth,[\s\S]*?answerLength/);
  assert.match(app, /setAnalysisDepth\(workspace\.settings\.analysisDepth\)/);
  assert.match(app, /setAnswerLength\(workspace\.settings\.answerLength\)/);
  assert.match(app, /workspace\.selectAnalysisDepth\(next\)/);
  assert.match(app, /workspace\.selectAnswerLength\(next\)/);
  assert.doesNotMatch(app, /setTargetOutputTokens\(defaultArtifactOutputTokens\);\s*setAnalysisDepth\("auto"\)/);
  assert.match(types, /analysisDepth: AnalysisDepth/);
  assert.match(types, /answerLength: AnswerLength/);
  assert.match(types, /contextInputLimit: number \| null/);
});

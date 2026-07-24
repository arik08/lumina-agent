import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("composer defaults file length to 10k and sends the selected target", async () => {
  const [rawApp, controls, styles, workspace, types] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/components/ComposerControls.tsx"),
    read("../src/styles.css"),
    read("../src/use-lumina-workspace.ts"),
    read("../src/api-types.ts"),
  ]);
  const app = `${rawApp}\n${controls}`;

  assert.match(app, /defaultArtifactOutputTokens = 10_000/);
  assert.doesNotMatch(app, /value: null, label: "자동"/);
  assert.match(app, /label: "10k"/);
  assert.match(app, /문서 출력 토큰/);
  assert.doesNotMatch(app, />파일 분량</);
  assert.doesNotMatch(app, /className="artifact-length-label"/);
  assert.match(app, /<FileText size=\{12\} aria-hidden="true" \/>[\s\S]*artifact-output-mode-value[\s\S]*artifact-length-value/);
  assert.match(app, /type="range"/);
  assert.match(app, /aria-expanded=\{open\}/);
  assert.match(app, /open && createPortal\(/);
  assert.match(app, /document\.body/);
  assert.match(app, /popoverRef\.current\?\.contains\(target\)/);
  assert.match(styles, /\.artifact-length-popover \{[^}]*position: fixed;/);
  assert.match(styles, /\.artifact-length-popover \{[^}]*box-shadow: 0 6px 16px/);
  assert.match(styles, /\.composer-footer \.artifact-length-trigger[^}]+padding: 0 8px;/);
  assert.match(app, /closeOnOutsidePointer/);
  assert.match(app, /event\.key !== "Escape"/);
  assert.match(app, /onChange=\{\(event\) => selectStep/);
  assert.doesNotMatch(app, /onInput=/);
  for (const key of ["Home", "End", "ArrowRight", "ArrowUp", "ArrowLeft", "ArrowDown"]) {
    assert.match(app, new RegExp(`event\\.key.{0,80}${key}|${key}.{0,80}event\\.key`, "s"));
  }
  assert.match(app, /data-testid="artifact-length-slider"/);
  assert.doesNotMatch(app, /요청 내용에 맞춰 생성 파일의 분량을 결정/);
  assert.match(app, /채팅 답변이 아닌 생성 파일의 목표 분량/);
  for (const target of ["8_000", "10_000", "12_000", "15_000", "20_000", "30_000", "40_000"]) {
    assert.match(app, new RegExp(`value: ${target}`));
  }
  assert.match(app, /warning: "장문"/);
  assert.match(app, /warning: "최대"/);
  assert.match(app, /selected\.warning === "최대"/);
  assert.match(app, /selected\.value <= 10_000/);
  assert.match(styles, /\.artifact-length-control\.is-muted \.artifact-length-value \{ color: var\(--muted\); \}/);
  assert.match(styles, /\.artifact-length-popover\.is-muted output > span \{ color: var\(--muted\); \}/);
  assert.match(styles, /--artifact-length-warning: oklch\(62% 0\.18 52\);/);
  assert.match(styles, /\.artifact-length-control\.is-warning \{ --artifact-length-accent: var\(--artifact-length-warning\); \}/);
  assert.match(app, /targetOutputTokens \?\? undefined/);
  assert.match(app, /value === "chat" \? null : current \?\? defaultArtifactOutputTokens/);
  assert.match(app, /useState<number \| null>\(defaultArtifactOutputTokens\)/);
  assert.match(app, /resetLargeOutputTargetAfterRunRef\.current = \([\s\S]*?targetOutputTokens !== null && targetOutputTokens >= 20_000[\s\S]*?\? targetOutputTokens[\s\S]*?: null[\s\S]*?\)/);
  assert.match(app, /resetLargeOutputTargetAfterRunRef\.current === null[\s\S]*?!isTerminalRunStatus\(activeRun\.status\)[\s\S]*?current === submittedTarget \? defaultArtifactOutputTokens : current/);
  assert.match(app, /const startNewConversation = useCallback[\s\S]*?setTargetOutputTokens\(\(current\) => \([\s\S]*?current !== null && current >= 20_000 \? defaultArtifactOutputTokens : current/);
  assert.match(workspace, /targetOutputTokens\?: number/);
  assert.match(workspace, /currentSettings\.outputMode !== "chat" && targetOutputTokens/);
  assert.match(types, /targetOutputTokens\?: number/);
});

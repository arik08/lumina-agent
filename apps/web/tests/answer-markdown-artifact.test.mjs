import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [turnSource, apiSource] = await Promise.all([
  readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/api.ts", import.meta.url), "utf8"),
]);

test("completed answers expose Markdown Artifact save immediately after copy", () => {
  assert.match(
    turnSource,
    /aria-label="원문 복사"[\s\S]*?aria-label="라이브러리 저장"[\s\S]*?aria-label="링크 공유"/,
  );
  assert.match(turnSource, /aria-label="원문 복사" data-tooltip="원문 복사"/);
  assert.match(turnSource, /aria-label="라이브러리 저장" data-tooltip="라이브러리 저장"/);
  assert.match(turnSource, /api\.artifacts\.createFromMessage\(finalMessage\.id\)/);
  assert.match(turnSource, /onOpenArtifact\(artifact\)/);
  assert.match(turnSource, /disabled=\{!finalMessage \|\| !sanitizedAssistantText \|\| markdownSaving\}/);
});

test("Markdown save uses the authenticated Artifact API", () => {
  assert.match(apiSource, /request<ArtifactSummary>\(`\/artifacts\/from-message\/\$\{encodeURIComponent\(messageId\)\}`/);
  assert.match(apiSource, /createFromMessage: createMessageMarkdownArtifact/);
});

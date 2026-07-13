import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8");
const sanitizerSource = await readFile(new URL("../src/assistant-response.ts", import.meta.url), "utf8");
const sharedViewerSource = await readFile(new URL("../src/components/SharedSnapshotViewer.tsx", import.meta.url), "utf8");

test("assistant responses hide internal artifact UUID metadata everywhere users can read or copy them", () => {
  assert.ok(sanitizerSource.includes("Artifact(?: ID)?"));
  assert.ok(sanitizerSource.includes("[0-9a-f]{12}`?[ \\t]*\\r?\\n?/gim"));
  assert.match(appSource, /const sanitizedAssistantText = sanitizeAssistantResponse\(assistantText, artifacts\.length > 0\)/);
  assert.match(appSource, /copyText\(sanitizedAssistantText\)/);
  assert.match(sharedViewerSource, /sanitizeAssistantResponse\(message\.text, snapshot\.artifacts\.length > 0\)/);
});

test("artifact metadata matcher handles the response formats produced by providers", () => {
  const regexLiteral = sanitizerSource.match(/internalArtifactMetadataLine\s*=\s*\/(.+)\/gim;/s);
  assert.ok(regexLiteral);
  const metadataLine = new RegExp(regexLiteral[1], "gim");
  const uuid = "be2125dd-0bff-489c-8ab4-6b537595a101";

  for (const line of [
    `Artifact: ${uuid}\n`,
    `Artifact ID: ${uuid}\n`,
    `- **Artifact:** \`${uuid}\`\n`,
    `__Artifact ID__: ${uuid}\r\n`,
  ]) {
    assert.equal(line.replace(metadataLine, ""), "");
  }

  assert.equal(
    "Artifact는 생성된 문서를 뜻합니다.\n".replace(metadataLine, ""),
    "Artifact는 생성된 문서를 뜻합니다.\n",
  );
});

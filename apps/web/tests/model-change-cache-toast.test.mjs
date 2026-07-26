import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");

test("changing the model in an existing conversation warns before the next request", () => {
  assert.match(
    appSource,
    /candidateId !== selectedCandidateId[\s\S]*?activeRuntime\.turnSets\.length > 0[\s\S]*?showToast\(modelChangeCacheWarning\)[\s\S]*?selectModelCandidate/,
  );
});

test("restoring the pre-request model clears the warning instead of showing it again", () => {
  assert.match(
    appSource,
    /origin\?\.conversationId === workspace\.activeConversationId && candidateId === origin\.candidateId[\s\S]*?modelChangeOriginRef\.current = null[\s\S]*?current === modelChangeCacheWarning \? null : current/,
  );
  assert.match(
    appSource,
    /modelChangeOriginRef\.current = null;[\s\S]*?\[activeRuntime\.turnSets\.length, workspace\.activeConversationId\]/,
  );
});

test("changing effort does not show the model cache warning", () => {
  assert.match(
    appSource,
    /options=\{effortOptions\}[\s\S]*?onChange=\{\(effortId\) => void workspace\.selectEffort\(effortId \|\| null\)\}/,
  );
});

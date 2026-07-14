import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");

test("footer provider availability controls are admin-only", () => {
  assert.match(app, /\{isAdmin && <>[\s\S]*사용자 모델 허용 관리[\s\S]*setAdminFooterProviderEnabled/);
  assert.match(app, /setAdminFooterModelEnabled\(provider\.id, model\.modelKey, !model\.enabled\)/);
});

test("composer candidates come from the server-filtered enabled model catalog", () => {
  const candidateBlock = app.slice(
    app.indexOf("const candidateModelOptions"),
    app.indexOf("const selectedCandidateId"),
  );
  assert.doesNotMatch(candidateBlock, /modelCandidates/);
  assert.match(candidateBlock, /workspace\.providerModels\[provider\.id\]/);
});

test("admin availability mutations use protected admin provider endpoints", () => {
  assert.match(api, /request<AdminProviderSummary>\(`\/admin\/providers\/\$\{encodeURIComponent\(providerId\)\}`/);
  assert.match(api, /body: \{ enabled \}/);
});

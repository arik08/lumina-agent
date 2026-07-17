import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const sourceUrl = new URL("../src/mermaid-semantic.ts", import.meta.url);
const typescriptSource = await readFile(sourceUrl, "utf8");
const javascriptSource = ts.transpileModule(typescriptSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { inferMermaidNodeTone } = await import(`data:text/javascript;base64,${Buffer.from(javascriptSource).toString("base64")}`);

test("keeps ordinary peer workflow nodes neutral", () => {
  assert.equal(inferMermaidNodeTone("사업현황 분석"), "neutral");
  assert.equal(inferMermaidNodeTone("포스코홀딩스 본부 검토"), "neutral");
});

test("groups workflow nodes by semantic role instead of node order", () => {
  assert.equal(inferMermaidNodeTone("시장 변화"), "input");
  assert.equal(inferMermaidNodeTone("CEO / 그룹 경영진 논의"), "decision");
  assert.equal(inferMermaidNodeTone("포스코홀딩스 이사회 심의"), "decision");
  assert.equal(inferMermaidNodeTone("사업회사 실행"), "execution");
  assert.equal(inferMermaidNodeTone("배포 완료"), "success");
  assert.equal(inferMermaidNodeTone("실행 실패"), "danger");
});

test("uses decision geometry only when the label has no stronger status meaning", () => {
  assert.equal(inferMermaidNodeTone("조건 확인", true), "decision");
  assert.equal(inferMermaidNodeTone("처리 실패", true), "danger");
});

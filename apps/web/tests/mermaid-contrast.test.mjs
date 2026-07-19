import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/mermaid-contrast.ts", import.meta.url), "utf8");
const javascript = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { mermaidTextContrastRatio, readableMermaidTextColor } = await import(
  `data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`
);

test("keeps authored Mermaid text colors that already meet WCAG contrast", () => {
  assert.ok(mermaidTextContrastRatio("#20242c", "#fee08b") >= 4.5);
  assert.equal(readableMermaidTextColor("#20242c", "#fee08b"), null);
});

test("uses white text when a dark Mermaid node has unreadable dark text", () => {
  assert.ok(mermaidTextContrastRatio("#111827", "#1f2937") < 4.5);
  assert.equal(readableMermaidTextColor("#111827", "#1f2937"), "#ffffff");
  assert.ok(mermaidTextContrastRatio("#ffffff", "#1f2937") >= 4.5);
});

test("uses dark ink when a pale Mermaid node has unreadable light text", () => {
  assert.ok(mermaidTextContrastRatio("#ffffff", "#edf2fb") < 4.5);
  assert.equal(readableMermaidTextColor("#ffffff", "#edf2fb"), "#20242c");
  assert.ok(mermaidTextContrastRatio("#20242c", "#edf2fb") >= 4.5);
});

test("falls back to black for mid-tone fills where the product ink is not strong enough", () => {
  assert.equal(readableMermaidTextColor("#20242c", "#777777"), "#000000");
  assert.ok(mermaidTextContrastRatio("#000000", "#777777") >= 4.5);
});

test("skips colors whose effective contrast cannot be safely resolved", () => {
  assert.equal(readableMermaidTextColor("currentColor", "url(#gradient)"), null);
  assert.equal(readableMermaidTextColor("rgba(0, 0, 0, 0.5)", "#ffffff"), null);
});

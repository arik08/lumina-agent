import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const rendererSource = readFileSync(new URL("../src/components/InteractiveResponse.tsx", import.meta.url), "utf8");
const rendererStyles = readFileSync(new URL("../src/components/InteractiveResponse.css", import.meta.url), "utf8");
const instructionSource = readFileSync(new URL("../../server/src/lumina/instructions/service.py", import.meta.url), "utf8");
const visualArtifactSkillSource = readFileSync(new URL("../../../extensions/skills/visual-artifact/SKILL.md", import.meta.url), "utf8");

test("LLM instructions require context-specific Mermaid classes in saved source", () => {
  assert.match(instructionSource, /infer a coherent grouping from the/);
  assert.match(instructionSource, /`classDef` and `class` assignments/);
  assert.match(instructionSource, /Do not rely on the viewer to infer or reassign semantic colors/);
  assert.match(visualArtifactSkillSource, /infer a coherent color system from the actual subject/);
  assert.match(visualArtifactSkillSource, /Encode those choices directly in Mermaid source with `classDef` and `class` assignments/);
  assert.doesNotMatch(visualArtifactSkillSource, /blue `#3288bd` for external inputs/);
});

test("Mermaid renderer does not infer or override authored colors", () => {
  assert.doesNotMatch(rendererSource, /inferMermaidNodeTone|decorateMermaidSvg|luminaTone/);
  assert.doesNotMatch(rendererStyles, /data-lumina-tone|--mermaid-node-fill|--mermaid-node-stroke/);
});

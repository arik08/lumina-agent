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
  assert.match(instructionSource, /each top-level semantic branch one hue family/);
  assert.match(instructionSource, /assign every node instead of leaving arbitrary/);
  assert.match(instructionSource, /Reserve red, coral, and amber for explicit risk, warning/);
  assert.match(instructionSource, /at least 4\.5:1/);
  assert.match(instructionSource, /contrast against node fills/);
  assert.match(instructionSource, /Prefix authored Mermaid class names with `lumina-`/);
  assert.match(instructionSource, /structural class names such as `root`/);
  assert.match(instructionSource, /Do not rely on the/);
  assert.match(instructionSource, /viewer to infer or reassign semantic colors/);
  assert.match(visualArtifactSkillSource, /infer a coherent color system from the actual subject/);
  assert.match(visualArtifactSkillSource, /Encode the complete system directly in Mermaid source with `classDef` and `class` assignments/);
  assert.match(visualArtifactSkillSource, /apply it to every descendant in that branch/);
  assert.match(visualArtifactSkillSource, /Keep meaning available in labels, grouping, or structure rather than color alone/);
  assert.doesNotMatch(visualArtifactSkillSource, /blue `#3288bd` for external inputs/);
});

test("Mermaid renderer preserves authored semantic colors while enforcing readable node labels", () => {
  assert.match(rendererSource, /repairMermaidClassNames\(source\.trim\(\)\)/);
  assert.match(rendererSource, /ensureMermaidNodeTextContrast\(renderedSvg\)/);
  assert.doesNotMatch(rendererSource, /inferMermaidNodeTone|decorateMermaidSvg|luminaTone/);
  assert.doesNotMatch(rendererStyles, /data-lumina-tone|--mermaid-node-fill|--mermaid-node-stroke/);
});

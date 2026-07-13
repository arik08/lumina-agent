import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const designDocument = await readFile(new URL("../../../DESIGN.md", import.meta.url), "utf8");
const designSidecar = JSON.parse(
  await readFile(new URL("../../../.impeccable/design.json", import.meta.url), "utf8"),
);
const globalStyles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const selectMenuStyles = await readFile(
  new URL("../src/components/SelectMenu.css", import.meta.url),
  "utf8",
);

test("DESIGN.md keeps the six Stitch sections in their required order", () => {
  assert.deepEqual(
    [...designDocument.matchAll(/^## (.+)$/gm)].map((match) => match[1]),
    ["Overview", "Colors", "Typography", "Elevation", "Components", "Do's and Don'ts"],
  );
  assert.match(designDocument, /^---\nname: Lumina Agent[\s\S]*?\n---\n/m);
});

test("the design sidecar and live controls share the documented tokens", () => {
  assert.equal(designSidecar.schemaVersion, 2);
  assert.equal(designSidecar.narrative.northStar, "조용한 컨트롤 데스크");
  assert.ok(designSidecar.components.length >= 5);
  for (const token of [
    "--radius-control: 5px",
    "--radius-select: 8px",
    "--radius-menu: 10px",
    "--shadow-overlay:",
  ]) {
    assert.ok(globalStyles.includes(token), `missing live design token: ${token}`);
  }
  assert.match(selectMenuStyles, /border-radius: var\(--radius-select\);/);
  assert.match(selectMenuStyles, /border-radius: var\(--radius-menu\);/);
  assert.match(selectMenuStyles, /box-shadow: var\(--shadow-overlay\);/);
});

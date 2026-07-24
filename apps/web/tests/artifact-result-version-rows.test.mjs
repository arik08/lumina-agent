import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnSource = await readFile(
  new URL("../src/components/ConversationTurn.tsx", import.meta.url),
  "utf8",
);
const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");

test("report revisions render as separate original and version rows", () => {
  assert.match(turnSource, /const artifactVersionRows = artifacts\.flatMap/);
  assert.match(turnSource, /execution\.artifactId === artifact\.id/);
  assert.match(turnSource, /version === 1 \? "\(\uC6D0\uBCF8\)" : `\(v\$\{version\}\)`/);
  assert.match(turnSource, /onOpenArtifact\(artifact, version\)/);
});

test("clicking a revision opens that exact immutable version", () => {
  assert.match(appSource, /requestedVersion\?: number/);
  assert.match(appSource, /const targetVersion = requestedVersion \?\? artifact\.currentVersion/);
  assert.match(appSource, /requestedVersion !== undefined\s*\?\s*initialVersion/);
});

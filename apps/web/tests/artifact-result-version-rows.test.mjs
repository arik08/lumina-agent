import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnSource = await readFile(
  new URL("../src/components/ConversationTurn.tsx", import.meta.url),
  "utf8",
);
const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

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

test("report revision rows form one continuous list without repeated outer spacing", () => {
  assert.match(turnSource, /className="artifact-results"/);
  assert.match(styles, /\.artifact-results \{ margin: 20px 0 23px; \}/);
  assert.match(styles, /\.artifact-result \{[\s\S]*?margin: 0;[\s\S]*?border-bottom: 1px solid var\(--line\);/);
  assert.match(styles, /\.artifact-result:first-child \{ border-top: 1px solid var\(--line\); \}/);
});

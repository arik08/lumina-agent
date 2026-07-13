import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appUrl = new URL("../src/App.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("the composer primary action becomes a working stop control during an active run", async () => {
  const app = await readFile(appUrl, "utf8");

  assert.match(app, /const runIsActive = Boolean\([\s\S]*?activeRun[\s\S]*?!isTerminalRunStatus\(activeRun\.status\)/);
  assert.match(app, /const composerShowsStop = Boolean\(runIsActive && !composerHasPayload\)/);
  assert.match(app, /className=\{`send-button tooltip-control \$\{composerShowsStop \? "is-stop" : ""\}`\}/);
  assert.match(app, /aria-label=\{composerShowsStop \? "작업 중단"/);
  assert.match(app, /composerShowsStop[\s\S]*?controlRun\("cancel"\)/);
  assert.match(app, /composerShowsStop[\s\S]*?<span className="stop-glyph" aria-hidden="true"/);
});

test("the stop control uses a calm neutral treatment in light and dark themes", async () => {
  const styles = await readFile(stylesUrl, "utf8");

  assert.match(styles, /\.composer-footer \.send-button\.is-stop\s*\{[^}]*border-radius:\s*50%[^}]*background:\s*var\(--surface\)/);
  assert.match(styles, /\.composer-footer \.send-button \.stop-glyph\s*\{[^}]*border-radius:\s*2\.5px[^}]*background:\s*currentColor/);
  assert.doesNotMatch(styles, /\.composer-footer \.send-button\.is-stop\s*\{[^}]*var\(--danger\)/);
  assert.match(styles, /\.theme-dark \.composer-footer \.send-button\.is-stop\s*\{/);
});

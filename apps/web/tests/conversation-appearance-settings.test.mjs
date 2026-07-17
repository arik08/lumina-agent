import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const app = fs.readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const styles = fs.readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("conversation and run dock share the persisted width token", () => {
  assert.match(app, /--conversation-content-width/);
  assert.match(styles, /\.conversation \{ width: min\(var\(--conversation-content-width\)/);
  assert.match(styles, /\.run-dock \{[\s\S]*?width: min\(var\(--conversation-content-width\)/);
});

test("personal settings expose bounded one-pixel font controls", () => {
  assert.match(app, /대화 글꼴 크기/);
  assert.match(app, /conversationFontSize <= 14/);
  assert.match(app, /conversationFontSize \+ 1/);
  assert.match(styles, /font-size: var\(--conversation-font-size\)/);
});

test("conversation font size controls every center-panel text surface", () => {
  assert.match(app, /style=\{\{ \.\.\.conversationLayoutStyle, "--artifact-pane-width"/);
  assert.doesNotMatch(app, /className=\{`chat-pane view-\$\{mainView\}`\} id="top" style=/);
  assert.match(styles, /\.chat-pane\.view-chat :is\(\.chat-header, \.conversation-scroll, \.dock-area\) \*/);
  assert.match(styles, /\.app-shell > \.tool-message\.is-global \*[\s\S]*?font-size: calc\(var\(--conversation-font-size\) - 2px\)/);
  assert.match(styles, /\.chat-pane\.view-chat \.composer-footer \*[\s\S]*?font-size: calc\(var\(--conversation-font-size\) - 2px\)/);
  assert.match(styles, /\.chat-pane\.view-chat \.turn-work-details \*[\s\S]*?font-size: calc\(var\(--conversation-font-size\) - 1px\)/);
});

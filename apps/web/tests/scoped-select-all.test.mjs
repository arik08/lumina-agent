import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("Ctrl+A selects only the focused chat or artifact content region", async () => {
  const app = await readFile(appPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(app, /function selectAllInRegion[\s\S]*?range\.selectNodeContents\(event\.currentTarget\);/);
  assert.match(app, /target instanceof HTMLInputElement \|\| target instanceof HTMLTextAreaElement \|\| \(target instanceof HTMLElement && target\.isContentEditable\)/);
  assert.match(app, /className="conversation-scroll"[\s\S]*?tabIndex=\{-1\}[\s\S]*?onKeyDown=\{selectAllInRegion\}/);
  assert.match(app, /className=\{`artifact-body[\s\S]*?tabIndex=\{-1\} onPointerDown=\{focusSelectableRegion\} onKeyDown=\{selectAllInRegion\}/);
  assert.match(styles, /\.conversation-scroll:focus, \.artifact-body:focus \{ outline: none; \}/);
});

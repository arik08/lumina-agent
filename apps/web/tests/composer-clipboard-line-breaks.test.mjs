import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [appSource, clipboardSource, styles] = await Promise.all([
  readFile(new URL("../src/App.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/composer-clipboard.ts", import.meta.url), "utf8"),
  readFile(new URL("../src/styles.css", import.meta.url), "utf8"),
]);

test("rich-text paste recovers internal block line breaks without changing different plain text", () => {
  assert.match(clipboardSource, /querySelectorAll\("br"\)[\s\S]*?createTextNode\("\\n"\)/);
  assert.match(clipboardSource, /querySelectorAll\(clipboardBlockSelector\)[\s\S]*?createTextNode\("\\n"\)/);
  assert.match(clipboardSource, /comparableClipboardText\(recovered\) !== comparableClipboardText\(plainText\)/);
  assert.match(appSource, /clipboardTextWithLineBreaks\(plainText, event\.clipboardData\.getData\("text\/html"\)\)/);
  assert.match(appSource, /const nextDraft = `\$\{input\.value\.slice\(0, selectionStart\)\}\$\{pasted\}\$\{input\.value\.slice\(selectionEnd\)\}`/);
});

test("user message bubbles preserve stored internal line breaks", () => {
  assert.match(styles, /\.user-message-text \{ white-space: pre-wrap; \}/);
});

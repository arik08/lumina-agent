import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("syntax editor keeps highlight glyph metrics aligned with the textarea selection layer", () => {
  assert.match(
    styles,
    /\.syntax-editor\.syntax-editor > pre > \.hljs,\s*\.syntax-editor\.syntax-editor > pre > \.hljs \*\s*\{[^}]*font-family:\s*inherit;[^}]*font-size:\s*inherit;[^}]*font-style:\s*inherit;[^}]*font-weight:\s*inherit;[^}]*line-height:\s*inherit;[^}]*letter-spacing:\s*inherit;/s,
    "highlight tokens must inherit every glyph metric used by the textarea selection layer",
  );
});

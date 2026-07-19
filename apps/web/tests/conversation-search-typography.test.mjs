import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const styles = fs.readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("conversation search keeps labels readable at the design typography scale", () => {
  assert.match(styles, /\.conversation-search-dialog > header small \{[^}]*font-size: 13px;/);
  assert.match(styles, /\.conversation-search-header-actions kbd \{[^}]*font-size: 13px;/);
  assert.match(styles, /\.conversation-search-summary \{[^}]*font-size: 13px;/);
  assert.match(styles, /\.conversation-search-group-label \{[^}]*font-size: 13px;/);
  assert.match(styles, /\.conversation-search-results small \{[^}]*font-size: 13px;/);
  assert.match(styles, /\.conversation-search-results time \{[^}]*font-size: 13px;/);
  assert.match(styles, /\.conversation-search-more button \{[^}]*font-size: 14px;/);
});

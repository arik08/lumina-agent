import assert from "node:assert/strict";
import test from "node:test";

import { copyText } from "../src/clipboard.ts";

test("uses the Clipboard API when it accepts the write", async () => {
  const writes = [];
  let fallbackCalled = false;

  await copyText("tool log", {
    clipboard: { writeText: async (text) => { writes.push(text); } },
    legacyCopy: () => { fallbackCalled = true; return true; },
  });

  assert.deepEqual(writes, ["tool log"]);
  assert.equal(fallbackCalled, false);
});

test("falls back when the Clipboard API rejects the write", async () => {
  let fallbackText = "";

  await copyText("tool log", {
    clipboard: { writeText: async () => { throw new Error("NotAllowedError"); } },
    legacyCopy: (text) => { fallbackText = text; return true; },
  });

  assert.equal(fallbackText, "tool log");
});

test("falls back when the Clipboard API is unavailable", async () => {
  let fallbackText = "";

  await copyText("tool log", {
    clipboard: null,
    legacyCopy: (text) => { fallbackText = text; return true; },
  });

  assert.equal(fallbackText, "tool log");
});

test("rejects when both copy paths fail", async () => {
  const clipboardError = new Error("NotAllowedError");

  await assert.rejects(
    copyText("tool log", {
      clipboard: { writeText: async () => { throw clipboardError; } },
      legacyCopy: () => false,
    }),
    clipboardError,
  );
});

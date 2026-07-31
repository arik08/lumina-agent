import assert from "node:assert/strict";
import test from "node:test";

import { copyText, deliverPngCapture } from "../src/clipboard.ts";

async function withBrowserGlobals({ secure, clipboard }, callback) {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const originalClipboardItem = Object.getOwnPropertyDescriptor(globalThis, "ClipboardItem");
  class TestClipboardItem {
    constructor(data) {
      this.data = data;
    }
  }
  Object.defineProperty(globalThis, "window", { configurable: true, value: { isSecureContext: secure } });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { clipboard } });
  Object.defineProperty(globalThis, "ClipboardItem", { configurable: true, value: TestClipboardItem });
  try {
    await callback();
  } finally {
    for (const [name, descriptor] of [
      ["window", originalWindow],
      ["navigator", originalNavigator],
      ["ClipboardItem", originalClipboardItem],
    ]) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
}

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

test("copies PNG data directly in a secure browser context", async () => {
  const blob = new Blob(["png"], { type: "image/png" });
  const writes = [];
  let downloaded = false;

  await withBrowserGlobals({
    secure: true,
    clipboard: { write: async (items) => { writes.push(...items); } },
  }, async () => {
    const result = await deliverPngCapture(Promise.resolve(blob), () => { downloaded = true; });
    assert.equal(result, "copied");
  });

  assert.equal(writes.length, 1);
  assert.equal(await writes[0].data["image/png"], blob);
  assert.equal(downloaded, false);
});

test("downloads PNG data instead of calling the clipboard on HTTP", async () => {
  const blob = new Blob(["png"], { type: "image/png" });
  let clipboardCalled = false;
  let downloadedBlob = null;

  await withBrowserGlobals({
    secure: false,
    clipboard: { write: async () => { clipboardCalled = true; } },
  }, async () => {
    const result = await deliverPngCapture(Promise.resolve(blob), (download) => { downloadedBlob = download; });
    assert.equal(result, "downloaded");
  });

  assert.equal(clipboardCalled, false);
  assert.equal(downloadedBlob, blob);
});

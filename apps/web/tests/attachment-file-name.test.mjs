import assert from "node:assert/strict";
import test from "node:test";

import { imageAttachmentFileName } from "../src/attachment-file-name.ts";

test("names image attachments with the local attachment time", () => {
  const attachedAt = new Date(2026, 6, 12, 22, 58, 41);

  assert.equal(imageAttachmentFileName("image.PNG", attachedAt), "img_225841.png");
});

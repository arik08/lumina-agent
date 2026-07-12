import assert from "node:assert/strict";
import test from "node:test";

import { createClientId } from "../src/client-id.ts";

test("uses native randomUUID when the browser provides it", () => {
  const id = createClientId({
    randomUUID: () => "123e4567-e89b-42d3-a456-426614174000",
  });

  assert.equal(id, "123e4567-e89b-42d3-a456-426614174000");
});

test("creates an RFC 4122 version 4 UUID when randomUUID is unavailable", () => {
  const id = createClientId({
    getRandomValues: (bytes) => {
      bytes.fill(0);
      return bytes;
    },
  });

  assert.equal(id, "00000000-0000-4000-8000-000000000000");
});

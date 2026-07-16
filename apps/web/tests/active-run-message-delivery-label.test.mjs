import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const conversationTurnUrl = new URL("../src/components/ConversationTurn.tsx", import.meta.url);

test("active-run user messages keep their Queue or Steering delivery label", async () => {
  const source = (await readFile(conversationTurnUrl, "utf8")).replaceAll("\r\n", "\n");
  const helper = source.match(/function messageDeliveryLabel[\s\S]*?\n}\n/)?.[0] ?? "";

  assert.match(helper, /command\?\.type \?\? message\.metadata\?\.command_type/);
  assert.match(helper, /commandType === "queue_next"[\s\S]*?`Queue · \$\{command\.queuePosition}번 대기`[\s\S]*?"Queue · 실행됨"/);
  assert.match(helper, /commandType === "steer"[\s\S]*?"Steering · 반영 대기"[\s\S]*?"Steering · 반영됨"/);
  assert.match(
    source,
    /<div className="user-message">[\s\S]*?<\/div>\s*\{messageDeliveryLabel\(message, pendingCommands\) && <small className="message-state">/,
  );
});

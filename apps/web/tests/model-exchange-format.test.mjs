import assert from "node:assert/strict";
import test from "node:test";

import { formatModelExchangeValue } from "../src/model-exchange-format.ts";

test("model exchange objects keep their content lines but not standalone outer braces", () => {
  assert.equal(
    formatModelExchangeValue({ query: "POSCO news", result_limit: 10 }),
    '{ "query": "POSCO news",\n  "result_limit": 10 }',
  );
});

test("model exchange arrays use the same compact outer delimiter format", () => {
  assert.equal(
    formatModelExchangeValue(["en.sedaily.com 본문을 확인했습니다.", "www.businesskorea.co.kr 본문을 확인했습니다."]),
    '[ "en.sedaily.com 본문을 확인했습니다.",\n  "www.businesskorea.co.kr 본문을 확인했습니다." ]',
  );
});

test("the model exchange formatter stays scoped to values passed through that UI", () => {
  assert.equal(formatModelExchangeValue("응답을 수신하고 있습니다."), "응답을 수신하고 있습니다.");
  assert.equal(formatModelExchangeValue(null), "(내용 없음)");
  assert.equal(formatModelExchangeValue({}), "{}");
  assert.equal(formatModelExchangeValue([]), "[]");
});

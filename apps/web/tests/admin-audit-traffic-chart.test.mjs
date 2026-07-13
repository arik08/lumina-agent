import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const componentUrl = new URL("../src/components/AdminTrafficChart.tsx", import.meta.url);
const apiUrl = new URL("../src/api.ts", import.meta.url);

test("monitoring renders a full-width minute traffic chart from the aggregate endpoint", async () => {
  const [component, api] = await Promise.all([
    readFile(componentUrl, "utf8"),
    readFile(apiUrl, "utf8"),
  ]);

  assert.match(api, /request<AdminAuditTraffic>\("\/admin\/audit-traffic"/);
  assert.match(component, /최근 60분 · 전체 모니터링 이벤트 기준/);
  assert.match(component, /onPointerMove=\{selectFromPointer\}/);
  assert.match(component, /event\.key !== "ArrowLeft"/);
  assert.match(component, /className="admin-traffic-chart"/);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const componentUrl = new URL("../src/components/AdminTrafficChart.tsx", import.meta.url);
const adminViewUrl = new URL("../src/components/AdminView.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);
const apiUrl = new URL("../src/api.ts", import.meta.url);

test("monitoring renders a full-width minute traffic chart from the aggregate endpoint", async () => {
  const [component, api] = await Promise.all([
    readFile(componentUrl, "utf8"),
    readFile(apiUrl, "utf8"),
  ]);

  assert.match(api, /request<AdminAuditTraffic>\("\/admin\/audit-traffic"/);
  assert.match(component, /value: "60", label: "1시간"/);
  assert.match(component, /value: "240", label: "4시간"/);
  assert.match(component, /value: "480", label: "8시간"/);
  assert.match(component, /getAuditTraffic\(periodMinutes, controller\.signal\)/);
  assert.match(component, /className="admin-traffic-line is-abnormal"/);
  assert.match(component, /오류 .*자동 .*수동/);
  assert.match(component, /admin-traffic-axis-right/);
  assert.match(component, /onPointerMove=\{selectFromPointer\}/);
  assert.match(component, /event\.key !== "ArrowLeft"/);
  assert.match(component, /className="admin-traffic-chart"/);
});

test("monitoring highlights non-success event rows with the danger palette", async () => {
  const [adminView, styles] = await Promise.all([
    readFile(adminViewUrl, "utf8"),
    readFile(stylesUrl, "utf8"),
  ]);

  assert.equal([...adminView.matchAll(/className=\{event\.result === "success" \? undefined : "is-abnormal"\}/g)].length, 2);
  assert.match(styles, /\.admin-audit-list article\.is-abnormal \{ background: var\(--danger-surface\); \}/);
  assert.match(styles, /\.admin-audit-list article\.is-abnormal time, \.admin-audit-list article\.is-abnormal small \{ color: var\(--danger\);/);
  assert.match(styles, /\.app-shell\.theme-dark,[\s\S]*--danger-surface: color-mix\(in srgb, var\(--surface\) 92%, var\(--danger\)\);/);
});

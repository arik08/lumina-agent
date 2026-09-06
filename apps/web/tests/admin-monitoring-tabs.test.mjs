import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const adminViewUrl = new URL("../src/components/AdminView.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("system monitoring separates traffic, cache, and audit log into accessible tabs", async () => {
  const [adminView, styles] = await Promise.all([
    readFile(adminViewUrl, "utf8"),
    readFile(stylesUrl, "utf8"),
  ]);

  assert.match(adminView, /type MonitoringView = "traffic" \| "cache" \| "audit"/);
  assert.match(adminView, /useState<MonitoringView>\("traffic"\)/);
  assert.match(adminView, /aria-label="모니터링 항목"/);
  assert.match(adminView, /id="admin-monitoring-tab-traffic"[^>]*aria-controls="admin-monitoring-panel-traffic"/);
  assert.match(adminView, /id="admin-monitoring-tab-cache"[^>]*aria-controls="admin-monitoring-panel-cache"/);
  assert.match(adminView, /id="admin-monitoring-tab-audit"[^>]*aria-controls="admin-monitoring-panel-audit"/);
  assert.match(adminView, /id="admin-monitoring-panel-traffic"[^>]*role="tabpanel"/);
  assert.match(adminView, /id="admin-monitoring-panel-cache"[^>]*role="tabpanel"/);
  assert.match(adminView, /id="admin-monitoring-panel-audit"[^>]*role="tabpanel"/);
  assert.match(adminView, /tab === "audit" && monitoringView === "cache"/);
  assert.match(adminView, /tab === "audit" && monitoringView !== "audit"/);
  assert.match(styles, /\.admin-monitoring-tabs button\[aria-selected="true"\]/);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("file schedules and marketplace remember independent split widths", async () => {
  const [files, schedules, marketplace, mcp, resizer] = await Promise.all([
    read("../src/components/ProjectFilesView.tsx"),
    read("../src/components/SchedulesView.tsx"),
    read("../src/components/MarketplaceView.tsx"),
    read("../src/components/McpMarketplacePanel.tsx"),
    read("../src/components/ResizableSplitPane.tsx"),
  ]);

  assert.match(files, /lumina:file-explorer-width/);
  assert.match(schedules, /lumina:schedules-list-width/);
  assert.match(marketplace, /lumina:marketplace-list-width/);
  assert.match(mcp, /lumina:marketplace-list-width/);
  assert.match(resizer, /role="separator"/);
  assert.match(resizer, /ArrowLeft/);
  assert.match(resizer, /ArrowRight/);
  assert.match(resizer, /localStorage/);
});

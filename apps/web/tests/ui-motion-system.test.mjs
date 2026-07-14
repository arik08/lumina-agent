import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("streamed text is visually paced near 60fps without changing event ingestion", async () => {
  const source = await read("../src/streaming-ui.ts");

  assert.match(source, /const visibleFrameIntervalMs = 16;/);
  assert.match(source, /frameTimerRef\.current = window\.setTimeout\(\(\) => \{[\s\S]*?window\.requestAnimationFrame/s);
  assert.match(source, /function smoothRevealCount\(pendingLength: number, desiredCount: number\)/);
  assert.match(source, /Math\.max\(streamCatchUpDeadlineMs, streamRevealDurationMs \* 3\)/);
  assert.match(source, /prefers-reduced-motion: reduce/);
});

test("new run activities reveal sequentially only while the timeline is live", async () => {
  const source = await read("../src/components/ConversationTurn.tsx");

  assert.match(source, /const runActivityRevealDelayMs = 85;/);
  assert.match(source, /function useStaggeredRunActivities\(activities: RunActivity\[\], enabled: boolean\)/);
  assert.match(source, /window\.setTimeout\(\(\) => \{[\s\S]*?Math\.min\(activities\.length, current \+ 1\)/s);
  assert.match(source, /const visibleActivities = useStaggeredRunActivities\(activities, timelineRunning\)/);
  assert.match(source, /onVisibleGrowth=\{onVisibleGrowth\}/);
});

test("artifact resizing coalesces pointer movement into animation frames", async () => {
  const source = await read("../src/App.tsx");

  assert.match(source, /let resizeFrame: number \| null = null;/);
  assert.match(source, /pendingClientX = moveEvent\.clientX;/);
  assert.match(source, /resizeFrame = window\.requestAnimationFrame\(applyResize\)/);
  assert.match(source, /window\.cancelAnimationFrame\(resizeFrame\)/);
});

test("motion styling uses shared easing and disables itself for reduced motion", async () => {
  const styles = await read("../src/styles.css");

  assert.match(styles, /--ease-out-quint: cubic-bezier\(0\.22, 1, 0\.36, 1\);/);
  assert.match(styles, /\.progress-group \{[^}]*animation: activity-enter/s);
  assert.match(styles, /\.artifact-pane \{[\s\S]*?animation: artifact-pane-enter/s);
  assert.match(styles, /\.artifact-resize-handle::after \{[^}]*transition: opacity var\(--motion-fast\) var\(--ease-out-quart\);/s);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
});

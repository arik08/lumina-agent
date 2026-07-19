import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("streamed text keeps smooth buffering within a 180ms visual-lag deadline", async () => {
  const source = await read("../src/streaming-ui.ts");

  assert.match(source, /const streamStartBufferMs = 40;/);
  assert.match(source, /const maxVisualLagMs = 180;/);
  assert.match(source, /const renderCommitReserveMs = 80;/);
  assert.match(source, /const visibleFrameIntervalMs = 15;/);
  assert.match(source, /frameTimerRef\.current = window\.setTimeout\(\(\) => \{[\s\S]*?window\.requestAnimationFrame/s);
  assert.match(source, /pendingRef\.current = targetText;/);
  assert.match(source, /function commonPrefixLength\(left: string, right: string\)/);
  assert.match(source, /function smoothBufferedRevealCount\(pendingLength: number, remainingMs: number\)/);
  assert.match(source, /pendingStartedAt \+ maxVisualLagMs - renderCommitReserveMs - timestamp/);
  assert.match(source, /Math\.ceil\(pendingLength \/ remainingFrames\)/);
  assert.doesNotMatch(source, /maxBufferedRevealCharsPerFrame|revealRateRef|recentChunksRef|streamCatchUpDeadlineMs/);
  assert.doesNotMatch(source, /if \(!target\.startsWith\(visibleRef\.current\)\) \{\s*visibleRef\.current = target;/);
  assert.match(source, /prefers-reduced-motion: reduce/);
});

test("new run activities reveal sequentially only while the timeline is live", async () => {
  const source = await read("../src/components/ConversationTurn.tsx");

  assert.match(source, /const runActivityRevealDelayMs = 85;/);
  assert.match(source, /function useStaggeredRunActivities\(activities: RunActivity\[\], enabled: boolean\)/);
  assert.match(source, /window\.setTimeout\(\(\) => \{[\s\S]*?Math\.min\(activities\.length, current \+ 1\)/s);
  assert.match(source, /const visibleActivities = useStaggeredRunActivities\(activities, timelineRunning\)/);
  assert.doesNotMatch(source, /onVisibleGrowth/);
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

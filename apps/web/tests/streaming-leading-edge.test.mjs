import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("streaming prose decorates the newest 24 visible graphemes in six four-character ranks", async () => {
  const source = await read("../src/components/ConversationTurn.tsx");

  assert.match(source, /const streamingLeadingEdgeLength = 24;/);
  assert.match(source, /const streamingLeadingEdgeRankSize = 4;/);
  assert.match(source, /const streamingLeadingEdgeRanks = 6;/);
  assert.match(source, /new Intl\.Segmenter\(undefined, \{ granularity: "grapheme" \}\)/);
  assert.match(source, /return !\/\^\\s\+\$\/u\.test\(value\);/);
  assert.match(source, /streamingLeadingEdgeExcludedParents = new Set\(\["link", "linkReference"\]\)/);
  assert.match(source, /dataStreamRank: String\(rank\)/);
  assert.match(source, /\(\) => leadingEdge[\s\S]*remarkStreamingLeadingEdge/);
});

test("the newest rank is a 60 percent cobalt and 40 percent chat-canvas mix", async () => {
  const styles = await read("../src/styles.css");

  assert.match(styles, /--stream-leading-1: color-mix\(in oklch, var\(--cobalt\) 60%, var\(--chat-canvas\)\);/);
  for (let rank = 1; rank <= 6; rank += 1) {
    assert.match(styles, new RegExp(`\\.streaming-leading-edge\\[data-stream-rank="${rank}"\\]`));
  }
  assert.match(styles, /\.streaming-text-settling \.streaming-leading-edge \{ color: var\(--ink\); \}/);
  assert.match(styles, /@media \(forced-colors: active\)[\s\S]*\.streaming-leading-edge \{ color: CanvasText; \}/);
});

test("the leading edge settles before streaming markup is removed", async () => {
  const source = await read("../src/streaming-ui.ts");

  assert.match(source, /const streamSettleDurationMs = 180;/);
  assert.match(source, /setSettling\(true\);/);
  assert.match(source, /revealing: streaming \|\| visibleText !== targetText \|\| settling, settling/);
});

test("streaming keeps completed markdown blocks immutable with buffered smooth frames", async () => {
  const [turnSource, streamingSource, streamingMarkdownSource] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/streaming-ui.ts"),
    read("../src/streaming-markdown.ts"),
  ]);

  assert.match(streamingSource, /const visibleFrameIntervalMs = 15;/);
  assert.match(streamingSource, /function smoothBufferedRevealCount\(pendingLength: number, remainingMs: number\)/);
  assert.match(turnSource, /const MemoizedMarkdownChunk = memo\(function MarkdownChunk/);
  assert.match(streamingMarkdownSource, /stableBlocks: \[\]/);
  assert.match(streamingMarkdownSource, /!input\.startsWith\(previous\.input\)/);
  assert.match(turnSource, /stableBlocks\.map\(\(block, index\) => \([\s\S]*?<MemoizedMarkdownChunk key=\{index\} text=\{block\}[\s\S]*?leadingEdge=\{false\}/);
  assert.match(turnSource, /tailText && <MemoizedMarkdownChunk text=\{tailText\}[\s\S]*?leadingEdge \/>/);
  assert.doesNotMatch(turnSource, /prefixText/);
});

test("closed tool rows defer hidden request and result serialization", async () => {
  const source = await read("../src/components/ConversationTurn.tsx");

  assert.match(source, /const toolDetailText = useMemo\(\(\) => \{\s*if \(!isOpen\) return null;/);
  assert.match(source, /isOpen && overlayStyle && toolDetailText && createPortal/);
  assert.match(source, /SyntaxCode value=\{toolDetailText\.requestText\}/);
  assert.match(source, /SyntaxCode value=\{toolDetailText\.resultText\}/);
});

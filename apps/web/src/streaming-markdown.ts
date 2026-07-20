import { useMemo, useRef } from "react";

export type StreamingPendingKind = "mermaid" | "chart" | "table" | null;

interface StreamingMarkdownScanner {
  input: string;
  source: string;
  stableBlocks: string[];
  blockStart: number;
  scanPosition: number;
  inFence: boolean;
  fenceMarker: string;
  fenceLanguage: string;
  previousLine: string;
  tailHasTable: boolean;
}

export interface StreamingMarkdownParts {
  stableBlocks: string[];
  liveTail: string;
  pendingKind: StreamingPendingKind;
}

function markdownTableCells(line: string) {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) return [];
  return trimmed.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function isMarkdownTableRow(line: string) {
  const cells = markdownTableCells(line);
  return cells.length >= 2 && cells.some(Boolean);
}

function isMarkdownTableDivider(line: string) {
  const cells = markdownTableCells(line);
  return cells.length >= 2 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function freshScanner(input: string): StreamingMarkdownScanner {
  return {
    input,
    source: input.replace(/\r\n?/g, "\n"),
    stableBlocks: [],
    blockStart: 0,
    scanPosition: 0,
    inFence: false,
    fenceMarker: "",
    fenceLanguage: "",
    previousLine: "",
    tailHasTable: false,
  };
}

function appendedScanner(previous: StreamingMarkdownScanner | null, input: string) {
  if (
    !previous
    || !input.startsWith(previous.input)
    || (previous.input.endsWith("\r") && input.slice(previous.input.length).startsWith("\n"))
  ) return freshScanner(input);
  return {
    ...previous,
    input,
    source: previous.source + input.slice(previous.input.length).replace(/\r\n?/g, "\n"),
  };
}

function scanStreamingMarkdown(previous: StreamingMarkdownScanner | null, input: string) {
  const scanner = appendedScanner(previous, input);
  let {
    blockStart,
    scanPosition,
    inFence,
    fenceMarker,
    fenceLanguage,
    previousLine,
    tailHasTable,
  } = scanner;
  let stableBlocks = scanner.stableBlocks;
  let lineEnd = scanner.source.indexOf("\n", scanPosition);
  while (lineEnd >= 0) {
    const line = scanner.source.slice(scanPosition, lineEnd);
    const nextPosition = lineEnd + 1;
    const fence = line.match(/^ {0,3}(`{3,}|~{3,})\s*([A-Za-z0-9_-]+)?/);
    if (fence) {
      const marker = fence[1];
      if (!inFence) {
        inFence = true;
        fenceMarker = marker;
        fenceLanguage = String(fence[2] || "").toLowerCase();
      } else if (marker[0] === fenceMarker[0] && marker.length >= fenceMarker.length) {
        inFence = false;
        fenceMarker = "";
        fenceLanguage = "";
        const block = scanner.source.slice(blockStart, nextPosition).trimEnd();
        if (block.trim()) stableBlocks = [...stableBlocks, block];
        blockStart = nextPosition;
        previousLine = "";
        tailHasTable = false;
      }
    } else if (!inFence && line.trim() === "") {
      const block = scanner.source.slice(blockStart, nextPosition).trimEnd();
      if (block.trim()) stableBlocks = [...stableBlocks, block];
      blockStart = nextPosition;
      previousLine = "";
      tailHasTable = false;
    } else if (!inFence) {
      if (isMarkdownTableRow(previousLine) && isMarkdownTableDivider(line)) tailHasTable = true;
      previousLine = line;
    }
    scanPosition = nextPosition;
    lineEnd = scanner.source.indexOf("\n", scanPosition);
  }

  const nextScanner: StreamingMarkdownScanner = {
    ...scanner,
    stableBlocks,
    blockStart,
    scanPosition,
    inFence,
    fenceMarker,
    fenceLanguage,
    previousLine,
    tailHasTable,
  };
  const partialLine = scanner.source.slice(scanPosition);
  const partialFence = !inFence && scanPosition === blockStart
    ? partialLine.match(/^ {0,3}(`{3,}|~{3,})\s*([A-Za-z0-9_-]+)?/)
    : null;
  const pendingFenceLanguage = inFence
    ? fenceLanguage
    : String(partialFence?.[2] || "").toLowerCase();
  const pendingKind: StreamingPendingKind = pendingFenceLanguage === "mermaid" || pendingFenceLanguage === "mmd"
    ? "mermaid"
    : pendingFenceLanguage === "lumina-chart"
      ? "chart"
      : tailHasTable || (isMarkdownTableRow(previousLine) && isMarkdownTableDivider(partialLine))
        ? "table"
        : null;
  return {
    scanner: nextScanner,
    parts: {
      stableBlocks,
      liveTail: scanner.source.slice(blockStart),
      pendingKind,
    } satisfies StreamingMarkdownParts,
  };
}

export function useStreamingMarkdownParts(text: string, streaming: boolean): StreamingMarkdownParts {
  const scannerRef = useRef<StreamingMarkdownScanner | null>(null);
  return useMemo(() => {
    if (!streaming) {
      scannerRef.current = null;
      return { stableBlocks: [text], liveTail: "", pendingKind: null };
    }
    const result = scanStreamingMarkdown(scannerRef.current, text);
    scannerRef.current = result.scanner;
    return result.parts;
  }, [streaming, text]);
}

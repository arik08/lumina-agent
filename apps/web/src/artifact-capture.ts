import html2canvas from "html2canvas";

export const artifactCaptureRequestMessage = "lumina:artifact-capture-request";
export const artifactCaptureSnapshotMessage = "lumina:artifact-capture-snapshot";

const artifactCaptureDesktopWidths = [960, 1120, 1280, 1440, 1600, 1920];
const artifactCaptureDesktopHeight = 900;
const artifactCaptureMaxDimension = 32_767;
const artifactCaptureMaxPixels = 50_000_000;

export type ArtifactCaptureSnapshot = {
  html: string;
  width: number;
  height: number;
  viewportHeight: number;
};

function waitForCaptureLayout() {
  return new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });
}

function renderedContentWidth(document: Document) {
  const view = document.defaultView;
  if (!view) return 0;
  let left = Number.POSITIVE_INFINITY;
  let right = Number.NEGATIVE_INFINITY;
  const visualTags = new Set(["IMG", "SVG", "CANVAS", "TABLE", "PRE", "VIDEO", "HR"]);
  for (const element of document.body?.querySelectorAll<HTMLElement>("*") ?? []) {
    const hasDirectText = Array.from(element.childNodes).some(
      (node) => node.nodeType === Node.TEXT_NODE && Boolean(node.textContent?.trim()),
    );
    const style = view.getComputedStyle(element);
    const hasBoundedWidth = style.maxWidth !== "none" && style.maxWidth !== "0px";
    const isReportContainer = element.tagName === "MAIN"
      || element.tagName === "ARTICLE"
      || element.getAttribute("role") === "main";
    const leftMargin = Number.parseFloat(style.marginLeft);
    const rightMargin = Number.parseFloat(style.marginRight);
    const isCenteredContainer = leftMargin > 0 && Math.abs(leftMargin - rightMargin) < 1;
    if (
      !hasDirectText
      && !visualTags.has(element.tagName)
      && !hasBoundedWidth
      && !isReportContainer
      && !isCenteredContainer
    ) continue;
    if (style.display === "none" || style.visibility === "hidden") continue;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    left = Math.min(left, rect.left);
    right = Math.max(right, rect.right);
  }
  return Number.isFinite(left) && Number.isFinite(right) ? Math.ceil(right - left) : 0;
}

export function selectArtifactCaptureViewportWidth(measurements: Array<{
  viewportWidth: number;
  contentWidth: number;
  contentHeight: number;
  hasHorizontalOverflow: boolean;
}>) {
  const viable = measurements.filter((measurement) => !measurement.hasHorizontalOverflow);
  if (viable.length === 0) {
    return measurements.at(-1)?.viewportWidth ?? artifactCaptureDesktopWidths[0];
  }
  const shortestHeight = Math.min(...viable.map((measurement) => measurement.contentHeight));
  const stableHeightLimit = Math.ceil(shortestHeight * 1.08);
  return viable.find((measurement) => measurement.contentHeight <= stableHeightLimit)?.viewportWidth
    ?? viable.at(-1)!.viewportWidth;
}

async function optimalCaptureWidth(
  frame: HTMLIFrameElement,
  document: Document,
  originalWidth: number,
) {
  const widths = [...new Set([
    ...artifactCaptureDesktopWidths,
    ...(originalWidth > artifactCaptureDesktopWidths.at(-1)! ? [Math.ceil(originalWidth)] : []),
  ])].sort((left, right) => left - right);
  const measurements: Array<{
    viewportWidth: number;
    contentWidth: number;
    contentHeight: number;
    hasHorizontalOverflow: boolean;
  }> = [];
  for (const viewportWidth of widths) {
    frame.style.width = `${viewportWidth}px`;
    await waitForCaptureLayout();
    const root = document.documentElement;
    const body = document.body;
    const scrollWidth = Math.max(root.scrollWidth, body?.scrollWidth ?? 0);
    const contentHeight = Math.max(root.scrollHeight, body?.scrollHeight ?? 0);
    const contentWidth = renderedContentWidth(document) || scrollWidth || viewportWidth;
    measurements.push({
      viewportWidth,
      contentWidth,
      contentHeight,
      hasHorizontalOverflow: scrollWidth > viewportWidth + 1,
    });
  }
  return selectArtifactCaptureViewportWidth(measurements);
}

export async function captureArtifactSnapshot(snapshot: ArtifactCaptureSnapshot) {
  const viewportHeight = Math.max(artifactCaptureDesktopHeight, Math.ceil(snapshot.viewportHeight));
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-same-origin");
  frame.setAttribute("aria-hidden", "true");
  Object.assign(frame.style, {
    position: "fixed",
    left: "-100000px",
    top: "0",
    width: `${artifactCaptureDesktopWidths[0]}px`,
    height: `${viewportHeight}px`,
    opacity: "0",
    pointerEvents: "none",
  });
  frame.srcdoc = snapshot.html;
  document.body.append(frame);
  try {
    await new Promise<void>((resolve, reject) => {
      const timeoutId = window.setTimeout(
        () => reject(new Error("캡처 문서 준비 시간이 초과되었습니다.")),
        15_000,
      );
      frame.addEventListener("load", () => {
        window.clearTimeout(timeoutId);
        resolve();
      }, { once: true });
    });
    const captureDocument = frame.contentDocument;
    if (!captureDocument?.documentElement) throw new Error("캡처 문서를 열지 못했습니다.");
    if (captureDocument.fonts?.ready) await captureDocument.fonts.ready;
    const viewportWidth = await optimalCaptureWidth(frame, captureDocument, snapshot.width);
    frame.style.width = `${viewportWidth}px`;
    await waitForCaptureLayout();
    const root = captureDocument.documentElement;
    const body = captureDocument.body;
    const width = Math.max(viewportWidth, renderedContentWidth(captureDocument));
    const height = Math.max(viewportHeight, root.scrollHeight, body?.scrollHeight ?? 0);
    if (
      width > artifactCaptureMaxDimension
      || height > artifactCaptureMaxDimension
      || width * height > artifactCaptureMaxPixels
    ) {
      throw new Error(`보고서가 너무 커서 한 장의 이미지로 만들 수 없습니다. (${width}×${height}px)`);
    }
    const transparent = new Set(["", "transparent", "rgba(0, 0, 0, 0)"]);
    const rootBackground = getComputedStyle(root).backgroundColor;
    const bodyBackground = body ? getComputedStyle(body).backgroundColor : "";
    const backgroundColor = !transparent.has(rootBackground)
      ? rootBackground
      : !transparent.has(bodyBackground) ? bodyBackground : "#ffffff";
    const canvas = await html2canvas(root, {
      backgroundColor,
      width,
      height,
      windowWidth: viewportWidth,
      windowHeight: viewportHeight,
      scrollX: 0,
      scrollY: 0,
      scale: 1,
      useCORS: true,
      allowTaint: false,
      imageTimeout: 15_000,
      logging: false,
    });
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (value) => value ? resolve(value) : reject(new Error("PNG 이미지 생성에 실패했습니다.")),
        "image/png",
      );
    });
  } finally {
    frame.remove();
  }
}

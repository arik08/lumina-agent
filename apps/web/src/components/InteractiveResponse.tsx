import {
  Image as ImageIcon,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
  type WheelEvent,
} from "react";
import { createPortal } from "react-dom";
import { SyntaxCode } from "./SyntaxCode";
import "./InteractiveResponse.css";

let mermaidRenderSequence = 0;
let mermaidModulePromise: Promise<typeof import("mermaid")> | null = null;
const mermaidRenderJobs = new Map<string, ReturnType<(typeof import("mermaid"))["default"]["render"]>>();
const artifactVisualPalette = {
  blue: "#3288bd",
  teal: "#66c2a5",
  lime: "#e6f598",
  red: "#d53e4f",
  magenta: "#9e0142",
  coral: "#f46d43",
  amber: "#fdae61",
  yellow: "#fee08b",
  green: "#abdda4",
  purple: "#5e4fa2",
} as const;
const artifactVisualPaletteSequence = Object.values(artifactVisualPalette);
const mermaidNodeTones = ["blue", "teal", "orange", "red", "purple"] as const;

async function loadMermaid() {
  if (!mermaidModulePromise) {
    mermaidModulePromise = import("mermaid").catch((error: unknown) => {
      mermaidModulePromise = null;
      throw error;
    });
  }
  return mermaidModulePromise;
}

export function preloadMermaid() {
  void loadMermaid().catch(() => undefined);
}

if (typeof window !== "undefined") {
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(preloadMermaid, { timeout: 1500 });
  } else {
    window.setTimeout(preloadMermaid, 0);
  }
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function useOverlayLifecycle(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return undefined;
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, open]);
}

function ZoomViewer({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const dragRef = useRef<{ pointerId: number; x: number; y: number; startX: number; startY: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  useOverlayLifecycle(open, onClose);

  useEffect(() => {
    if (!open) return;
    setZoom(1);
    setOffset({ x: 0, y: 0 });
    window.requestAnimationFrame(() => closeRef.current?.focus());
  }, [open]);

  if (!open) return null;

  const themeClassName = document.querySelector(".app-shell.theme-dark") ? " theme-dark" : "";
  const changeZoom = (next: number) => setZoom(clamp(next, 0.5, 4));
  const reset = () => {
    setZoom(1);
    setOffset({ x: 0, y: 0 });
  };
  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, startX: offset.x, startY: offset.y };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.classList.add("is-dragging");
  };
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setOffset({ x: drag.startX + event.clientX - drag.x, y: drag.startY + event.clientY - drag.y });
  };
  const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    event.currentTarget.classList.remove("is-dragging");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey && Math.abs(event.deltaY) < Math.abs(event.deltaX)) return;
    event.preventDefault();
    changeZoom(zoom * (event.deltaY > 0 ? 0.9 : 1.1));
  };

  return createPortal(
    <div className={`response-zoom-backdrop${themeClassName}`} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="response-zoom-dialog" role="dialog" aria-modal="true" aria-label={`${title} 확대 보기`}>
        <header className="response-zoom-header">
          <button
            type="button"
            className="response-zoom-title"
            aria-label={`${title} 확대 보기 닫기`}
            data-tooltip="닫기"
            onClick={onClose}
          >
            <strong>{title}</strong>
          </button>
          <div className="response-zoom-controls" aria-label="확대 보기 조작">
            <button type="button" aria-label="축소" data-tooltip="축소" onClick={() => changeZoom(zoom / 1.2)}><Minus size={16} /></button>
            <output aria-live="polite">{Math.round(zoom * 100)}%</output>
            <button type="button" aria-label="확대" data-tooltip="확대" onClick={() => changeZoom(zoom * 1.2)}><Plus size={16} /></button>
            <button type="button" aria-label="보기 초기화" data-tooltip="보기 초기화" onClick={reset}><RotateCcw size={15} /></button>
            <button ref={closeRef} type="button" aria-label="확대 보기 닫기" data-tooltip="닫기" onClick={onClose}><X size={17} /></button>
          </div>
        </header>
        <div
          className="response-zoom-viewport"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={finishDrag}
          onPointerCancel={finishDrag}
          onWheel={handleWheel}
        >
          <div className="response-zoom-canvas" style={{ transform: `translate3d(${offset.x}px, ${offset.y}px, 0) scale(${zoom})` }}>
            {children}
          </div>
        </div>
      </section>
    </div>,
    document.body,
  );
}

function MermaidSurface({ source, expanded = false, zoom = 1 }: { source: string; expanded?: boolean; zoom?: number }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const baseWidthRef = useRef(0);
  const zoomRef = useRef(zoom);
  const dragRef = useRef<{ pointerId: number; x: number; y: number; scrollLeft: number; scrollTop: number } | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    void renderMermaidSvg(source).then(({ svg, bindFunctions }) => {
      if (cancelled || !containerRef.current) return;
      containerRef.current.innerHTML = svg;
      bindFunctions?.(containerRef.current);
      const renderedSvg = containerRef.current.querySelector("svg");
      if (renderedSvg) {
        const naturalWidth = renderedSvg.viewBox.baseVal.width || renderedSvg.getBoundingClientRect().width;
        baseWidthRef.current = Math.min(naturalWidth, containerRef.current.clientWidth);
        renderedSvg.style.width = `${baseWidthRef.current * zoomRef.current}px`;
        renderedSvg.style.maxWidth = zoomRef.current > 1 ? "none" : "100%";
      }
    }).catch(() => {
      if (!cancelled) setError(true);
    });
    return () => { cancelled = true; };
  }, [source]);

  useEffect(() => {
    zoomRef.current = zoom;
    const renderedSvg = containerRef.current?.querySelector("svg");
    if (!renderedSvg || !baseWidthRef.current) return;
    renderedSvg.style.width = `${baseWidthRef.current * zoom}px`;
    renderedSvg.style.maxWidth = zoom > 1 ? "none" : "100%";
  }, [zoom]);

  if (error) return <SyntaxCode className="mermaid-render-error" value={source} language="mermaid" />;
  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (expanded || event.button !== 0) return;
    dragRef.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      scrollLeft: event.currentTarget.scrollLeft,
      scrollTop: event.currentTarget.scrollTop,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.classList.add("is-dragging");
  };
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.currentTarget.scrollLeft = drag.scrollLeft - (event.clientX - drag.x);
    event.currentTarget.scrollTop = drag.scrollTop - (event.clientY - drag.y);
  };
  const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    event.currentTarget.classList.remove("is-dragging");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return (
    <div
      ref={containerRef}
      className={`mermaid-surface ${expanded ? "is-expanded" : ""}`}
      role="img"
      aria-label="Mermaid 다이어그램"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
    >
      <span>다이어그램 렌더링 중…</span>
    </div>
  );
}

function mermaidAppearance() {
  const styles = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback;
  const themeVariables = {
    background: "transparent",
    primaryColor: token("--cobalt-pale", "#edf2fb"),
    primaryTextColor: token("--ink", "#20242c"),
    primaryBorderColor: artifactVisualPalette.blue,
    secondaryColor: token("--surface-soft", "#f5f6f7"),
    secondaryTextColor: token("--ink", "#20242c"),
    tertiaryColor: token("--surface", "#ffffff"),
    tertiaryTextColor: token("--ink", "#20242c"),
    lineColor: artifactVisualPalette.purple,
    textColor: token("--ink", "#20242c"),
    noteBkgColor: token("--surface-selected", "#edf2fb"),
    noteTextColor: token("--ink", "#20242c"),
    actorBkg: token("--surface", "#ffffff"),
    actorBorder: artifactVisualPalette.blue,
    actorTextColor: token("--ink", "#20242c"),
    clusterBkg: token("--surface-soft", "#f5f6f7"),
    clusterBorder: artifactVisualPalette.teal,
    pie1: artifactVisualPalette.blue,
    pie2: artifactVisualPalette.teal,
    pie3: artifactVisualPalette.lime,
    pie4: artifactVisualPalette.red,
    pie5: artifactVisualPalette.magenta,
    pie6: artifactVisualPalette.coral,
    pie7: artifactVisualPalette.amber,
    pie8: artifactVisualPalette.yellow,
    pie9: artifactVisualPalette.green,
    pie10: artifactVisualPalette.purple,
    pie11: artifactVisualPalette.blue,
    pie12: artifactVisualPalette.teal,
    cScale0: artifactVisualPalette.blue,
    cScale1: artifactVisualPalette.teal,
    cScale2: artifactVisualPalette.lime,
    cScale3: artifactVisualPalette.red,
    cScale4: artifactVisualPalette.magenta,
    cScale5: artifactVisualPalette.coral,
    cScale6: artifactVisualPalette.amber,
    cScale7: artifactVisualPalette.yellow,
    cScale8: artifactVisualPalette.green,
    cScale9: artifactVisualPalette.purple,
    cScale10: artifactVisualPalette.blue,
    cScale11: artifactVisualPalette.teal,
    git0: artifactVisualPalette.blue,
    git1: artifactVisualPalette.teal,
    git2: artifactVisualPalette.lime,
    git3: artifactVisualPalette.red,
    git4: artifactVisualPalette.magenta,
    git5: artifactVisualPalette.coral,
    git6: artifactVisualPalette.amber,
    git7: artifactVisualPalette.purple,
    xyChart: {
      plotColorPalette: artifactVisualPaletteSequence.join(","),
    },
    fontFamily: token("--font-ui", "Segoe UI, sans-serif"),
  };
  return {
    signature: JSON.stringify(themeVariables),
    config: {
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      themeVariables,
      flowchart: {
        htmlLabels: false,
      },
    },
  } as const;
}

function decorateMermaidSvg(svg: string) {
  const template = document.createElement("template");
  template.innerHTML = svg;
  template.content.querySelectorAll<SVGGElement>("g.node").forEach((node, index) => {
    const hasAuthoredClass = Array.from(node.classList).some((className) => className !== "node" && className !== "default");
    if (hasAuthoredClass) return;
    const isDecision = Array.from(node.children).some((child) => child.tagName.toLowerCase() === "polygon");
    node.dataset.luminaTone = isDecision ? "orange" : mermaidNodeTones[index % mermaidNodeTones.length];
  });
  return template.innerHTML;
}

export async function renderMermaidSvg(source: string) {
  const normalizedSource = source.trim();
  const appearance = mermaidAppearance();
  const cacheKey = `${appearance.signature}\u0000${normalizedSource}`;
  const activeJob = mermaidRenderJobs.get(cacheKey);
  if (activeJob) return activeJob;

  const renderJob = loadMermaid().then(async ({ default: mermaid }) => {
    mermaid.initialize(appearance.config);
    const result = await mermaid.render(`lumina-mermaid-${++mermaidRenderSequence}`, normalizedSource);
    return { ...result, svg: decorateMermaidSvg(result.svg) };
  });
  mermaidRenderJobs.set(cacheKey, renderJob);
  void renderJob.finally(() => {
    if (mermaidRenderJobs.get(cacheKey) === renderJob) mermaidRenderJobs.delete(cacheKey);
  }).catch(() => undefined);
  return renderJob;
}

export function MermaidDiagram({ source }: { source: string }) {
  const [expanded, setExpanded] = useState(false);
  const [zoom, setZoom] = useState(1);
  const changeZoom = (next: number) => setZoom(clamp(next, 0.5, 2));
  return (
    <>
      <section className="interactive-response-block mermaid-diagram" aria-label="Mermaid 다이어그램">
        <div className="interactive-response-toolbar">
          <span>Mermaid</span>
          <div className="interactive-response-toolbar-actions">
            <div className="mermaid-inline-zoom-controls" aria-label="Mermaid 다이어그램 배율 조절">
              <button type="button" aria-label="Mermaid 다이어그램 축소" data-tooltip="축소" disabled={zoom <= 0.5} onClick={() => changeZoom(zoom - 0.25)}><Minus size={15} /></button>
              <button type="button" className="mermaid-inline-zoom-value" aria-label="Mermaid 다이어그램 배율 초기화" data-tooltip="100%로 초기화" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
              <button type="button" aria-label="Mermaid 다이어그램 확대" data-tooltip="확대" disabled={zoom >= 2} onClick={() => changeZoom(zoom + 0.25)}><Plus size={15} /></button>
            </div>
            <button type="button" className="interactive-response-expand-icon" aria-label="Mermaid 다이어그램 크게 보기" data-tooltip="크게 보기" onClick={() => setExpanded(true)}><Maximize2 size={15} /></button>
          </div>
        </div>
        <div className="interactive-response-content" onDoubleClick={() => setExpanded(true)}>
          <MermaidSurface source={source} zoom={zoom} />
        </div>
      </section>
      <ZoomViewer title="Mermaid" open={expanded} onClose={() => setExpanded(false)}>
        <MermaidSurface source={source} expanded />
      </ZoomViewer>
    </>
  );
}

type InteractiveChartSpec = {
  title: string;
  option: Record<string, unknown>;
  metrics: Array<{ label: string; value: string }>;
  source: { label: string; url: string; asOf: string } | null;
};

function shortText(value: unknown, maximum: number, fallback = "") {
  return typeof value === "string" ? value.trim().slice(0, maximum) : fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function safeExternalUrl(value: unknown) {
  const text = shortText(value, 500);
  if (!text) return "";
  try {
    const url = new URL(text);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : "";
  } catch {
    return "";
  }
}

function isSafeChartJson(value: unknown, depth = 0): boolean {
  if (depth > 50) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((item) => isSafeChartJson(item, depth + 1));
  if (!isRecord(value)) return false;
  return Object.entries(value).every(([key, item]) => (
    key !== "__proto__" && key !== "prototype" && key !== "constructor" && isSafeChartJson(item, depth + 1)
  ));
}

function chartTitle(option: Record<string, unknown>, fallback = "데이터 차트") {
  const rawTitle = Array.isArray(option.title) ? option.title[0] : option.title;
  return isRecord(rawTitle) ? shortText(rawTitle.text, 120, fallback) : fallback;
}

function legacyChartOption(raw: Record<string, unknown>) {
  if (!Array.isArray(raw.categories) || !Array.isArray(raw.series)) return null;
  const categories = raw.categories.map((value) => shortText(value, 100)).filter(Boolean);
  if (!categories.length) return null;
  const series = raw.series.flatMap((item, index) => {
    if (!isRecord(item) || !Array.isArray(item.values) || item.values.length !== categories.length) return [];
    const data = item.values.map(Number);
    if (data.some((value) => !Number.isFinite(value))) return [];
    return [{
      name: shortText(item.name, 80, `Series ${index + 1}`),
      type: item.type === "bar" ? "bar" : "line",
      data,
      yAxisIndex: item.axis === "right" ? 1 : 0,
      smooth: item.type !== "bar",
    }];
  });
  if (!series.length) return null;
  const hasRightAxis = series.some((item) => item.yAxisIndex === 1);
  return {
    title: { text: shortText(raw.title, 120, "데이터 차트"), subtext: shortText(raw.subtitle, 180) },
    tooltip: { trigger: "axis" },
    legend: { top: 54 },
    grid: { top: 92, right: hasRightAxis ? 62 : 28, bottom: 52, left: 58, containLabel: true },
    xAxis: { type: "category", name: shortText(raw.xLabel, 50), data: categories },
    yAxis: hasRightAxis ? [{ type: "value" }, { type: "value" }] : { type: "value" },
    series,
  };
}

export function parseInteractiveChart(source: string): InteractiveChartSpec | null {
  try {
    const raw: unknown = JSON.parse(source);
    if (!isRecord(raw) || !isSafeChartJson(raw)) return null;
    const legacyOption = legacyChartOption(raw);
    const candidate = isRecord(raw.option) ? raw.option : legacyOption ?? raw;
    if (!isRecord(candidate) || !isSafeChartJson(candidate) || !Object.keys(candidate).length) return null;
    const metrics = Array.isArray(raw.metrics) ? raw.metrics.slice(0, 8).flatMap((item) => {
      if (!isRecord(item)) return [];
      const label = shortText(item.label, 50);
      const value = shortText(item.value, 80);
      return label && value ? [{ label, value }] : [];
    }) : [];
    const sourceInfo = isRecord(raw.source) ? {
      label: shortText(raw.source.label, 80),
      url: safeExternalUrl(raw.source.url),
      asOf: shortText(raw.source.asOf, 80),
    } : null;
    return {
      title: shortText(raw.title, 120) || chartTitle(candidate),
      option: candidate,
      metrics,
      source: sourceInfo && (sourceInfo.label || sourceInfo.asOf) ? sourceInfo : null,
    };
  } catch {
    return null;
  }
}

function InteractiveChartContent({ spec, expanded = false }: { spec: InteractiveChartSpec; expanded?: boolean }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    let cancelled = false;
    let dispose = () => {};
    setError(false);
    void import("echarts").then((echarts) => {
      if (cancelled) return;
      const chart = echarts.init(container, undefined, { renderer: "canvas" });
      const applyOption = () => {
        const currentStyles = getComputedStyle(container);
        const currentToken = (name: string, fallback: string) => currentStyles.getPropertyValue(name).trim() || fallback;
        chart.setOption({
          darkMode: Boolean(container.closest(".theme-dark")),
          color: [currentToken("--cobalt", "#3f66c9"), currentToken("--danger", "#c34f51"), currentToken("--success", "#2f9765"), currentToken("--warning", "#b8771f"), currentToken("--muted", "#6c737e")],
          backgroundColor: "transparent",
          textStyle: { color: currentToken("--ink", "#20242c"), fontFamily: currentToken("--font-ui", "Segoe UI, sans-serif") },
          ...spec.option,
        }, { notMerge: true });
      };
      applyOption();
      const observer = new ResizeObserver(() => chart.resize());
      observer.observe(container);
      const themeRoot = container.closest(".app-shell, .shared-viewer");
      const themeObserver = themeRoot ? new MutationObserver(applyOption) : null;
      if (themeRoot) themeObserver?.observe(themeRoot, { attributes: true, attributeFilter: ["class"] });
      dispose = () => {
        observer.disconnect();
        themeObserver?.disconnect();
        chart.dispose();
      };
    }).catch(() => {
      if (!cancelled) setError(true);
    });
    return () => {
      cancelled = true;
      dispose();
    };
  }, [spec.option]);

  if (error) return <SyntaxCode className="interactive-chart-error" value={JSON.stringify(spec.option, null, 2)} language="json" />;
  return (
    <div className={`echarts-chart ${expanded ? "is-expanded" : ""}`}>
      <div ref={containerRef} className="echarts-chart-canvas" role="img" aria-label={`${spec.title} 인터랙티브 차트`} />
      {spec.metrics.length > 0 && <dl className="echarts-chart-metrics">{spec.metrics.map((metric) => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl>}
      {spec.source && <footer>{spec.source.url ? <a href={spec.source.url} target="_blank" rel="noreferrer noopener">{spec.source.label || "출처"}</a> : <span>{spec.source.label}</span>}{spec.source.asOf && <time>{spec.source.asOf}</time>}</footer>}
    </div>
  );
}

export function InteractiveChart({ source }: { source: string }) {
  const spec = useMemo(() => parseInteractiveChart(source), [source]);
  const [expanded, setExpanded] = useState(false);
  if (!spec) return <SyntaxCode className="interactive-chart-error" value={source} language="json" />;
  return (
    <>
      <section className="interactive-response-block interactive-chart" aria-label={`${spec.title} 차트`}>
        <div className="interactive-response-toolbar">
          <span>Apache ECharts</span>
          <button type="button" aria-label={`${spec.title} 확대`} data-tooltip="확대해서 보기" onClick={() => setExpanded(true)}><Maximize2 size={15} /></button>
        </div>
        <InteractiveChartContent spec={spec} />
      </section>
      <ZoomViewer title={spec.title} open={expanded} onClose={() => setExpanded(false)}>
        <InteractiveChartContent spec={spec} expanded />
      </ZoomViewer>
    </>
  );
}

export function InlineMarkdownImage({ src, alt }: { src: string; alt: string }) {
  const [expanded, setExpanded] = useState(false);
  const close = useCallback(() => setExpanded(false), []);
  useOverlayLifecycle(expanded, close);
  return (
    <>
      <span className="inline-markdown-image">
        <button type="button" aria-label={`${alt || "이미지"} 크게 보기`} onClick={() => setExpanded(true)}>
          <img src={src} alt={alt} loading="lazy" />
          <span><ImageIcon size={14} /> 크게 보기</span>
        </button>
        {alt && <span className="inline-markdown-image-caption">{alt}</span>}
      </span>
      {expanded && createPortal(
        <div className="inline-image-backdrop" role="dialog" aria-modal="true" aria-label={`${alt || "이미지"} 크게 보기`} onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
          <button type="button" aria-label="이미지 닫기" onClick={close}><X size={18} /></button>
          <img src={src} alt={alt} />
        </div>,
        document.body,
      )}
    </>
  );
}

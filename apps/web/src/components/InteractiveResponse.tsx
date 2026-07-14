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
    <div className="response-zoom-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="response-zoom-dialog" role="dialog" aria-modal="true" aria-label={`${title} 확대 보기`}>
        <header className="response-zoom-header">
          <strong>{title}</strong>
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

function MermaidSurface({ source, expanded = false }: { source: string; expanded?: boolean }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    void import("mermaid").then(async ({ default: mermaid }) => {
      const styles = getComputedStyle(document.documentElement);
      const token = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback;
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "base",
        themeVariables: {
          background: token("--surface", "#ffffff"),
          primaryColor: token("--surface-soft", "#f5f6f7"),
          primaryTextColor: token("--ink", "#20242c"),
          primaryBorderColor: token("--line-strong", "#d4d8de"),
          lineColor: token("--muted", "#6c737e"),
          secondaryColor: token("--cobalt-pale", "#edf2fb"),
          tertiaryColor: token("--surface", "#ffffff"),
          fontFamily: token("--font-ui", "Segoe UI, sans-serif"),
        },
      });
      const { svg, bindFunctions } = await mermaid.render(`lumina-mermaid-${++mermaidRenderSequence}`, source.trim());
      if (cancelled || !containerRef.current) return;
      containerRef.current.innerHTML = svg;
      bindFunctions?.(containerRef.current);
    }).catch(() => {
      if (!cancelled) setError(true);
    });
    return () => { cancelled = true; };
  }, [source]);

  if (error) return <SyntaxCode className="mermaid-render-error" value={source} language="mermaid" />;
  return <div ref={containerRef} className={`mermaid-surface ${expanded ? "is-expanded" : ""}`} role="img" aria-label="Mermaid 다이어그램"><span>다이어그램 렌더링 중…</span></div>;
}

export function MermaidDiagram({ source }: { source: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <section className="interactive-response-block mermaid-diagram" aria-label="Mermaid 다이어그램">
        <div className="interactive-response-toolbar">
          <span>Mermaid</span>
          <button type="button" aria-label="Mermaid 다이어그램 확대" data-tooltip="확대해서 보기" onClick={() => setExpanded(true)}><Maximize2 size={15} /></button>
        </div>
        <div className="interactive-response-content" onDoubleClick={() => setExpanded(true)}>
          <MermaidSurface source={source} />
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

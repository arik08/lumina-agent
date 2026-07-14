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
  type KeyboardEvent,
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

type ChartAxis = "left" | "right";
type ChartSeriesType = "bar" | "line";
type ChartColor = "cobalt" | "red" | "green" | "amber" | "slate";

type InteractiveChartSeries = {
  name: string;
  type: ChartSeriesType;
  values: number[];
  axis: ChartAxis;
  color: ChartColor;
  unit: string;
  unitPosition: "prefix" | "suffix";
};

export type InteractiveChartSpec = {
  title: string;
  subtitle: string;
  categories: string[];
  xLabel: string;
  series: InteractiveChartSeries[];
  metrics: Array<{ label: string; value: string }>;
  source: { label: string; url: string; asOf: string } | null;
};

const chartColors: Record<ChartColor, string> = {
  cobalt: "var(--cobalt)",
  red: "var(--danger)",
  green: "var(--success)",
  amber: "var(--warning)",
  slate: "var(--muted)",
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

export function parseInteractiveChart(source: string): InteractiveChartSpec | null {
  try {
    const raw: unknown = JSON.parse(source);
    if (!isRecord(raw) || !Array.isArray(raw.categories) || !Array.isArray(raw.series)) return null;
    const categories = raw.categories.map((value) => shortText(value, 48)).filter(Boolean).slice(0, 24);
    if (categories.length < 2) return null;
    const series: InteractiveChartSeries[] = raw.series.slice(0, 4).flatMap((item, index) => {
      if (!isRecord(item) || !Array.isArray(item.values) || item.values.length !== categories.length) return [];
      const values = item.values.map(Number);
      if (values.some((value) => !Number.isFinite(value))) return [];
      const type: ChartSeriesType = item.type === "bar" ? "bar" : "line";
      const axis: ChartAxis = item.axis === "right" ? "right" : "left";
      const availableColors: ChartColor[] = ["cobalt", "red", "green", "amber", "slate"];
      const requestedColor = shortText(item.color, 16) as ChartColor;
      return [{
        name: shortText(item.name, 60, `Series ${index + 1}`),
        type,
        values,
        axis,
        color: availableColors.includes(requestedColor) ? requestedColor : availableColors[index % availableColors.length],
        unit: shortText(item.unit, 12),
        unitPosition: item.unitPosition === "prefix" ? "prefix" : "suffix",
      }];
    });
    if (!series.length) return null;
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
      title: shortText(raw.title, 120, "데이터 차트"),
      subtitle: shortText(raw.subtitle, 180),
      categories,
      xLabel: shortText(raw.xLabel, 50),
      series,
      metrics,
      source: sourceInfo && (sourceInfo.label || sourceInfo.asOf) ? sourceInfo : null,
    };
  } catch {
    return null;
  }
}

function axisExtent(series: InteractiveChartSeries[], axis: ChartAxis) {
  const selected = series.filter((item) => item.axis === axis);
  const values = selected.flatMap((item) => item.values);
  if (!values.length) return null;
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (selected.some((item) => item.type === "bar")) minimum = Math.min(0, minimum);
  if (minimum === maximum) maximum = minimum + 1;
  const padding = Math.max((maximum - minimum) * 0.08, 0.01);
  return { minimum: minimum >= 0 ? Math.max(0, minimum - padding) : minimum - padding, maximum: maximum + padding };
}

function formatChartValue(value: number, series: InteractiveChartSeries) {
  const formatted = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: Math.abs(value) < 10 ? 2 : 1 }).format(value);
  return series.unitPosition === "prefix" ? `${series.unit}${formatted}` : `${formatted}${series.unit}`;
}

function InteractiveChartContent({ spec, expanded = false }: { spec: InteractiveChartSpec; expanded?: boolean }) {
  const [activeIndex, setActiveIndex] = useState(spec.categories.length - 1);
  const width = 820;
  const height = expanded ? 390 : 310;
  const inset = { top: 28, right: 58, bottom: 48, left: 58 };
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  const leftExtent = axisExtent(spec.series, "left");
  const rightExtent = axisExtent(spec.series, "right");
  const xFor = (index: number) => inset.left + index / Math.max(1, spec.categories.length - 1) * plotWidth;
  const yFor = (value: number, axis: ChartAxis) => {
    const extent = (axis === "right" ? rightExtent : leftExtent) ?? leftExtent ?? rightExtent ?? { minimum: 0, maximum: 1 };
    return inset.top + plotHeight - (value - extent.minimum) / (extent.maximum - extent.minimum) * plotHeight;
  };
  const barSeries = spec.series.filter((series) => series.type === "bar");
  const categoryBand = plotWidth / Math.max(1, spec.categories.length);
  const barWidth = Math.min(48, categoryBand * 0.68) / Math.max(1, barSeries.length);
  const selectFromPointer = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = clamp((event.clientX - bounds.left) / bounds.width, inset.left / width, (width - inset.right) / width);
    setActiveIndex(clamp(Math.round(((ratio * width) - inset.left) / plotWidth * (spec.categories.length - 1)), 0, spec.categories.length - 1));
  };
  const selectFromKeyboard = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setActiveIndex((current) => clamp(current + (event.key === "ArrowLeft" ? -1 : 1), 0, spec.categories.length - 1));
  };
  const activeX = xFor(activeIndex);
  const tooltipRatio = activeX / width;
  const tooltipClassName = `native-chart-tooltip ${tooltipRatio < 0.22 ? "is-left" : tooltipRatio > 0.78 ? "is-right" : ""}`.trim();

  return (
    <div className={`native-chart ${expanded ? "is-expanded" : ""}`}>
      <div className="native-chart-heading"><strong>{spec.title}</strong>{spec.subtitle && <span>{spec.subtitle}</span>}</div>
      <div className="native-chart-plot">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${spec.title} 인터랙티브 차트`} tabIndex={0} onPointerMove={selectFromPointer} onPointerDown={selectFromPointer} onKeyDown={selectFromKeyboard}>
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const y = inset.top + plotHeight * ratio;
            return <line key={ratio} className="native-chart-grid" x1={inset.left} x2={width - inset.right} y1={y} y2={y} />;
          })}
          {leftExtent && [0, 0.5, 1].map((ratio) => {
            const value = leftExtent.maximum - (leftExtent.maximum - leftExtent.minimum) * ratio;
            return <text key={`left-${ratio}`} className="native-chart-axis-label" x={inset.left - 9} y={inset.top + plotHeight * ratio + 4} textAnchor="end">{new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 }).format(value)}</text>;
          })}
          {rightExtent && [0, 0.5, 1].map((ratio) => {
            const value = rightExtent.maximum - (rightExtent.maximum - rightExtent.minimum) * ratio;
            return <text key={`right-${ratio}`} className="native-chart-axis-label" x={width - inset.right + 9} y={inset.top + plotHeight * ratio + 4}>{new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 }).format(value)}</text>;
          })}
          {spec.series.map((series) => {
            const color = chartColors[series.color];
            if (series.type === "bar") {
              const barIndex = barSeries.indexOf(series);
              return <g key={series.name}>{series.values.map((value, index) => {
                const zeroY = yFor(0, series.axis);
                const valueY = yFor(value, series.axis);
                return <rect key={index} className="native-chart-bar" x={xFor(index) - (barSeries.length * barWidth) / 2 + barIndex * barWidth + 1} y={Math.min(zeroY, valueY)} width={Math.max(2, barWidth - 2)} height={Math.max(1, Math.abs(zeroY - valueY))} rx="2" style={{ fill: color }} />;
              })}</g>;
            }
            const path = series.values.map((value, index) => `${index ? "L" : "M"}${xFor(index).toFixed(1)},${yFor(value, series.axis).toFixed(1)}`).join(" ");
            return <g key={series.name}><path className="native-chart-line" d={path} style={{ stroke: color }} />{series.values.map((value, index) => <circle key={index} className={index === activeIndex ? "native-chart-point is-active" : "native-chart-point"} cx={xFor(index)} cy={yFor(value, series.axis)} r={index === activeIndex ? 5 : 3} style={{ fill: color }} />)}</g>;
          })}
          <line className="native-chart-cursor" x1={activeX} x2={activeX} y1={inset.top} y2={inset.top + plotHeight} />
          {spec.categories.map((category, index) => {
            const show = spec.categories.length <= 8 || index === 0 || index === spec.categories.length - 1 || index % Math.ceil(spec.categories.length / 6) === 0;
            return show ? <text key={category + index} className="native-chart-axis-label" x={xFor(index)} y={height - 20} textAnchor="middle">{category}</text> : null;
          })}
          {spec.xLabel && <text className="native-chart-x-label" x={width / 2} y={height - 2} textAnchor="middle">{spec.xLabel}</text>}
        </svg>
        <div className={tooltipClassName} style={{ left: `${tooltipRatio * 100}%` }}>
          <strong>{spec.categories[activeIndex]}</strong>
          {spec.series.map((series) => <span key={series.name}><i style={{ background: chartColors[series.color] }} />{series.name}<b>{formatChartValue(series.values[activeIndex], series)}</b></span>)}
        </div>
      </div>
      <div className="native-chart-legend">{spec.series.map((series) => <span key={series.name}><i style={{ background: chartColors[series.color] }} />{series.name}</span>)}</div>
      {spec.metrics.length > 0 && <dl className="native-chart-metrics">{spec.metrics.map((metric) => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl>}
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
          <span>Interactive chart</span>
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

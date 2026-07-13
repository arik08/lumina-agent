import { useEffect, useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import { api } from "../api";
import type { AdminAuditTraffic } from "../api-types";
import "./AdminTrafficChart.css";

interface AdminTrafficChartProps {
  refreshKey: number;
}

const minuteFormatter = new Intl.DateTimeFormat("ko-KR", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function formatMinute(value: string) {
  return minuteFormatter.format(new Date(value));
}

function chartErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "트래픽을 불러오지 못했습니다.";
}

export function AdminTrafficChart({ refreshKey }: AdminTrafficChartProps) {
  const [traffic, setTraffic] = useState<AdminAuditTraffic | null>(null);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    api.admin.getAuditTraffic(60, controller.signal)
      .then((result) => {
        setTraffic(result);
        setActiveIndex(null);
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(chartErrorMessage(requestError));
      });
    return () => controller.abort();
  }, [refreshKey]);

  const chart = useMemo(() => {
    const width = 1200;
    const height = 190;
    const inset = { top: 16, right: 14, bottom: 28, left: 34 };
    const plotWidth = width - inset.left - inset.right;
    const plotHeight = height - inset.top - inset.bottom;
    const buckets = traffic?.buckets ?? [];
    const max = Math.max(1, traffic?.peak ?? 0);
    const points = buckets.map((bucket, index) => ({
      ...bucket,
      x: inset.left + (buckets.length === 1 ? 0 : index / (buckets.length - 1)) * plotWidth,
      y: inset.top + plotHeight - (bucket.count / max) * plotHeight,
    }));
    const line = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const area = points.length
      ? `${line} L${points.at(-1)?.x},${inset.top + plotHeight} L${points[0].x},${inset.top + plotHeight} Z`
      : "";
    return { width, height, inset, plotWidth, plotHeight, max, points, line, area };
  }, [traffic]);

  const selectedIndex = activeIndex ?? Math.max(0, chart.points.length - 1);
  const selected = chart.points[selectedIndex];
  const labelIndexes = new Set([0, 15, 30, 45, Math.max(0, chart.points.length - 1)]);

  const selectFromPointer = (event: PointerEvent<SVGSVGElement>) => {
    if (!chart.points.length) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
    setActiveIndex(Math.round(ratio * (chart.points.length - 1)));
  };

  const selectFromKeyboard = (event: KeyboardEvent<SVGSVGElement>) => {
    if (!chart.points.length || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    const step = event.key === "ArrowLeft" ? -1 : 1;
    setActiveIndex(Math.min(chart.points.length - 1, Math.max(0, selectedIndex + step)));
  };

  return (
    <section className="admin-traffic" aria-labelledby="admin-traffic-title">
      <header className="admin-traffic-heading">
        <div>
          <strong id="admin-traffic-title">분당 트래픽</strong>
          <small>최근 60분 · 전체 모니터링 이벤트 기준</small>
        </div>
        <div className="admin-traffic-summary" aria-live="polite">
          <span><small>{selected ? formatMinute(selected.minute) : "현재"}</small><strong>{selected?.count ?? 0}건/분</strong></span>
          <span><small>최대</small><strong>{traffic?.peak ?? 0}건/분</strong></span>
          <span><small>60분 합계</small><strong>{traffic?.total ?? 0}건</strong></span>
        </div>
      </header>
      {error && <p className="admin-traffic-error" role="alert">{error}</p>}
      {!traffic && !error && <div className="admin-traffic-skeleton" aria-label="트래픽을 불러오는 중" />}
      {traffic && (
        <div className="admin-traffic-chart-wrap">
          <svg
            className="admin-traffic-chart"
            viewBox={`0 0 ${chart.width} ${chart.height}`}
            role="img"
            tabIndex={0}
            aria-label={`최근 60분 분당 모니터링 이벤트. 선택 시각 ${selected ? formatMinute(selected.minute) : "현재"}, ${selected?.count ?? 0}건`}
            onPointerMove={selectFromPointer}
            onPointerDown={selectFromPointer}
            onPointerLeave={() => setActiveIndex(null)}
            onKeyDown={selectFromKeyboard}
          >
            {[0, 0.5, 1].map((ratio) => (
              <g key={ratio}>
                <line x1={chart.inset.left} x2={chart.width - chart.inset.right} y1={chart.inset.top + chart.plotHeight * ratio} y2={chart.inset.top + chart.plotHeight * ratio} />
                <text x={chart.inset.left - 8} y={chart.inset.top + chart.plotHeight * ratio + 4}>{Math.round(chart.max * (1 - ratio))}</text>
              </g>
            ))}
            <path className="admin-traffic-area" d={chart.area} />
            <path className="admin-traffic-line" d={chart.line} />
            {selected && <g className="admin-traffic-cursor"><line x1={selected.x} x2={selected.x} y1={chart.inset.top} y2={chart.inset.top + chart.plotHeight} /><circle cx={selected.x} cy={selected.y} r="4" /></g>}
            {chart.points.map((point, index) => labelIndexes.has(index) && (
              <text className="admin-traffic-time" x={point.x} y={chart.height - 7} key={point.minute}>{formatMinute(point.minute)}</text>
            ))}
          </svg>
        </div>
      )}
    </section>
  );
}

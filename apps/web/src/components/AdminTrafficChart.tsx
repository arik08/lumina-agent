import { useEffect, useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";
import { api } from "../api";
import type { AdminAuditTraffic } from "../api-types";
import { SelectMenu } from "./SelectMenu";
import "./AdminTrafficChart.css";

interface AdminTrafficChartProps {
  refreshKey: number;
}

type TrafficPeriodMinutes = 60 | 240 | 480;

const trafficPeriodOptions = [
  { value: "60", label: "1시간" },
  { value: "240", label: "4시간" },
  { value: "480", label: "8시간" },
];

const trafficPeriodLabels: Record<TrafficPeriodMinutes, string> = {
  60: "최근 1시간",
  240: "최근 4시간",
  480: "최근 8시간",
};

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
  const [periodMinutes, setPeriodMinutes] = useState<TrafficPeriodMinutes>(60);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    setTraffic(null);
    api.admin.getAuditTraffic(periodMinutes, controller.signal)
      .then((result) => {
        setTraffic(result);
        setActiveIndex(null);
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(chartErrorMessage(requestError));
      });
    return () => controller.abort();
  }, [periodMinutes, refreshKey]);

  const chart = useMemo(() => {
    const width = 1200;
    const height = 190;
    const inset = { top: 16, right: 38, bottom: 28, left: 34 };
    const plotWidth = width - inset.left - inset.right;
    const plotHeight = height - inset.top - inset.bottom;
    const buckets = traffic?.buckets ?? [];
    const normalMax = Math.max(1, traffic?.normalPeak ?? 0);
    const abnormalMax = Math.max(1, traffic?.abnormalPeak ?? 0);
    const points = buckets.map((bucket, index) => ({
      ...bucket,
      x: inset.left + (buckets.length === 1 ? 0 : index / (buckets.length - 1)) * plotWidth,
      normalY: inset.top + plotHeight - (bucket.normalCount / normalMax) * plotHeight,
      abnormalY: inset.top + plotHeight - (bucket.abnormalCount / abnormalMax) * plotHeight,
    }));
    const normalLine = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.normalY.toFixed(1)}`).join(" ");
    const abnormalLine = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.abnormalY.toFixed(1)}`).join(" ");
    const normalArea = points.length
      ? `${normalLine} L${points.at(-1)?.x},${inset.top + plotHeight} L${points[0].x},${inset.top + plotHeight} Z`
      : "";
    return { width, height, inset, plotWidth, plotHeight, normalMax, abnormalMax, points, normalLine, abnormalLine, normalArea };
  }, [traffic]);

  const selectedIndex = activeIndex ?? Math.max(0, chart.points.length - 1);
  const selected = chart.points[selectedIndex];
  const lastPointIndex = Math.max(0, chart.points.length - 1);
  const labelIndexes = new Set([0, 0.25, 0.5, 0.75, 1].map((ratio) => Math.round(lastPointIndex * ratio)));
  const selectedAbnormalAuditCount = selected?.abnormalAuditCount ?? 0;
  const selectedAutomaticRecoveryCount = selected?.automaticRecoveryCount ?? 0;
  const selectedManualRestartCount = selected?.manualRestartCount ?? 0;

  const selectFromPointer = (event: PointerEvent<SVGSVGElement>) => {
    if (!chart.points.length) return;
    const screenMatrix = event.currentTarget.getScreenCTM();
    if (!screenMatrix) return;
    const pointer = event.currentTarget.createSVGPoint();
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    const chartPoint = pointer.matrixTransform(screenMatrix.inverse());
    const ratio = Math.min(1, Math.max(0, (chartPoint.x - chart.inset.left) / chart.plotWidth));
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
        <div className="admin-traffic-title-block">
          <div className="admin-traffic-title-row">
            <strong id="admin-traffic-title">분당 트래픽</strong>
            <SelectMenu
              className="admin-traffic-period-select"
              size="small"
              width="auto"
              value={String(periodMinutes)}
              options={trafficPeriodOptions}
              ariaLabel="트래픽 조회 기간"
              onChange={(value) => setPeriodMinutes(Number(value) as TrafficPeriodMinutes)}
            />
          </div>
          <small>{trafficPeriodLabels[periodMinutes]} · <span className="admin-traffic-legend is-normal">정상</span> / <span className="admin-traffic-legend is-abnormal">비정상</span> 모니터링 이벤트</small>
        </div>
        <div className="admin-traffic-summary" aria-live="polite">
          <span><small>{selected ? formatMinute(selected.minute) : "현재"} · 정상</small><strong>{selected?.normalCount ?? 0}건/분</strong></span>
          <span className="is-abnormal"><small>비정상 · 오류 {selectedAbnormalAuditCount} · 자동 {selectedAutomaticRecoveryCount} · 수동 {selectedManualRestartCount}</small><strong>{selected?.abnormalCount ?? 0}건/분</strong></span>
          <span><small>최대 정상 / 비정상</small><strong>{traffic?.normalPeak ?? 0} / {traffic?.abnormalPeak ?? 0}건/분</strong></span>
          <span><small>{trafficPeriodLabels[periodMinutes]} 합계</small><strong>{traffic?.normalTotal ?? 0} / <em>{traffic?.abnormalTotal ?? 0}</em>건</strong></span>
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
            aria-label={`${trafficPeriodLabels[periodMinutes]} 분당 모니터링 이벤트. 선택 시각 ${selected ? formatMinute(selected.minute) : "현재"}, 정상 ${selected?.normalCount ?? 0}건, 비정상 ${selected?.abnormalCount ?? 0}건`}
            onPointerMove={selectFromPointer}
            onPointerDown={selectFromPointer}
            onPointerLeave={() => setActiveIndex(null)}
            onKeyDown={selectFromKeyboard}
          >
            {[0, 0.5, 1].map((ratio) => (
              <g key={ratio}>
                <line x1={chart.inset.left} x2={chart.width - chart.inset.right} y1={chart.inset.top + chart.plotHeight * ratio} y2={chart.inset.top + chart.plotHeight * ratio} />
                <text x={chart.inset.left - 8} y={chart.inset.top + chart.plotHeight * ratio + 4}>{Math.round(chart.normalMax * (1 - ratio))}</text>
                <text className="admin-traffic-axis-right" x={chart.width - chart.inset.right + 8} y={chart.inset.top + chart.plotHeight * ratio + 4}>{Math.round(chart.abnormalMax * (1 - ratio))}</text>
              </g>
            ))}
            <path className="admin-traffic-area" d={chart.normalArea} />
            <path className="admin-traffic-line is-normal" d={chart.normalLine} />
            <path className="admin-traffic-line is-abnormal" d={chart.abnormalLine} />
            {selected && <g className="admin-traffic-cursor"><line x1={selected.x} x2={selected.x} y1={chart.inset.top} y2={chart.inset.top + chart.plotHeight} /><circle className="is-normal" cx={selected.x} cy={selected.normalY} r="4" /><circle className="is-abnormal" cx={selected.x} cy={selected.abnormalY} r="4" /></g>}
            {chart.points.map((point, index) => labelIndexes.has(index) && (
              <text className="admin-traffic-time" x={point.x} y={chart.height - 7} key={point.minute}>{formatMinute(point.minute)}</text>
            ))}
          </svg>
        </div>
      )}
    </section>
  );
}

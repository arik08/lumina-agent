import {
  AlertCircle,
  ArrowDown,
  ArrowLeft,
  Bot,
  Brain,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Circle,
  Clock3,
  Code2,
  Coins,
  Copy,
  CircleDollarSign,
  Download,
  Eye,
  FileCheck2,
  FileCode2,
  FilePenLine,
  FileText,
  FolderSearch,
  GitBranch,
  Globe2,
  Image as ImageIcon,
  LoaderCircle,
  MessageSquarePlus,
  Play,
  RotateCcw,
  Sparkles,
  Table2,
  ThumbsDown,
  ThumbsUp,
  Wrench,
  X,
} from "lucide-react";
import { copyText } from "../clipboard";
import { isTerminalRunStatus } from "../run-status";
import type { Link, Parent, PhrasingContent, Root, Text } from "mdast";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import ReactMarkdown, {
  defaultUrlTransform,
  type Components,
  type Options as ReactMarkdownOptions,
} from "react-markdown";
import { createPortal } from "react-dom";
import remarkGfm from "remark-gfm";
import { visit } from "unist-util-visit";
import { api, attachmentContentUrl } from "../api";
import type {
  ArtifactSummary,
  AttachmentSummary,
  ChatMessage,
  MessageCitation,
  RunActivity,
  RunCommand,
  RunSnapshot,
  RunStatus,
  SourceEvidence,
  ToolExecution,
  TurnSet,
} from "../api-types";
import { sanitizeAssistantResponse } from "../assistant-response";
import { GlobalTooltipLayer } from "./GlobalTooltip";
import { formatModelExchangeValue } from "../model-exchange-format";
import {
  mergedToolActiveDurationMs,
  progressStageTimingById,
} from "../run-activity-duration";
import { useStreamingText } from "../streaming-ui";
import { SyntaxCode, SyntaxCodeContent } from "./SyntaxCode";
import { BranchFromHereIcon, ShareActionIcon } from "./ActionIcons";
import {
  InlineMarkdownImage,
  InteractiveChart,
  MermaidDiagram,
} from "./InteractiveResponse";

function toolCallIcon(toolName: string, size = 15) {
  const normalizedName = toolName.toLowerCase().replace(/[\s-]+/g, "_");
  if (normalizedName === "web_search") return <Globe2 className="tool-kind-icon is-web-search" size={size} aria-hidden="true" />;
  if (normalizedName === "web_fetch") return <FileCheck2 className="tool-kind-icon is-web-fetch" size={size} aria-hidden="true" />;
  if (["glob", "grep", "list_dir"].includes(normalizedName)) return <FolderSearch className="tool-kind-icon is-file-browse" size={size} aria-hidden="true" />;
  if (normalizedName === "read_file") return <FileText className="tool-kind-icon is-read-file" size={size} aria-hidden="true" />;
  if (normalizedName === "write_file") return <FilePenLine className="tool-kind-icon is-write-file" size={size} aria-hidden="true" />;
  if (normalizedName.includes("report")) return <FileCode2 className="tool-kind-icon is-report" size={size} aria-hidden="true" />;
  if (normalizedName === "generate_image") return <ImageIcon className="tool-kind-icon is-image" size={size} aria-hidden="true" />;
  return <FileText className="tool-kind-icon" size={size} aria-hidden="true" />;
}

function formatDuration(durationMs: number | null) {
  if (durationMs === null) return "—";
  return `${(durationMs / 1000).toFixed(2)}초`;
}

function formatWorkDuration(durationMs: number) {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  if (totalSeconds < 60) return `${totalSeconds}초`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}분 ${seconds}초`;
}

function formatCompletedAt(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ko-KR", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date).replace(/\. /g, "-").replace(". ", " ").replace(".", "");
}

function usageNumber(usage: Record<string, unknown> | undefined, key: string) {
  const value = Number(usage?.[key]);
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

function optionalUsageNumber(usage: Record<string, unknown> | undefined, key: string) {
  if (usage?.[key] === undefined || usage?.[key] === null) return undefined;
  const value = Number(usage[key]);
  return Number.isFinite(value) && value >= 0 ? value : undefined;
}

function usageHasData(usage: Record<string, unknown> | undefined) {
  return Boolean(usage && (
    usageNumber(usage, "input_tokens")
    || usageNumber(usage, "output_tokens")
    || usageNumber(usage, "cached_input_tokens")
    || optionalUsageNumber(usage, "cost_usd") !== undefined
    || usage.estimated_cost_breakdown_usd
  ));
}

function normalizedUsage(usage: Record<string, unknown>): Record<string, unknown> {
  const input = usageNumber(usage, "input_tokens");
  const cached = usageNumber(usage, "cached_input_tokens");
  return {
    ...usage,
    input_tokens: input,
    cached_input_tokens: cached,
    uncached_input_tokens: usage.uncached_input_tokens === undefined
      ? Math.max(0, input - cached)
      : usageNumber(usage, "uncached_input_tokens"),
    output_tokens: usageNumber(usage, "output_tokens"),
  };
}

function addUsage(left: Record<string, unknown> | undefined, right: Record<string, unknown>) {
  const normalizedRight = normalizedUsage(right);
  if (!left) return normalizedRight;
  const normalizedLeft = normalizedUsage(left);
  const result: Record<string, unknown> = {
    ...normalizedRight,
    input_tokens: usageNumber(normalizedLeft, "input_tokens") + usageNumber(normalizedRight, "input_tokens"),
    cached_input_tokens: usageNumber(normalizedLeft, "cached_input_tokens") + usageNumber(normalizedRight, "cached_input_tokens"),
    uncached_input_tokens: usageNumber(normalizedLeft, "uncached_input_tokens") + usageNumber(normalizedRight, "uncached_input_tokens"),
    output_tokens: usageNumber(normalizedLeft, "output_tokens") + usageNumber(normalizedRight, "output_tokens"),
  };
  const leftCost = optionalUsageNumber(normalizedLeft, "cost_usd");
  const rightCost = optionalUsageNumber(normalizedRight, "cost_usd");
  if (leftCost !== undefined && rightCost !== undefined) result.cost_usd = leftCost + rightCost;
  else delete result.cost_usd;

  const leftBreakdown = estimatedModelCostParts(normalizedLeft);
  const rightBreakdown = estimatedModelCostParts(normalizedRight);
  if (leftBreakdown && rightBreakdown) {
    result.estimated_cost_breakdown_usd = {
      cached_input: leftBreakdown.cachedInput + rightBreakdown.cachedInput,
      input: leftBreakdown.input + rightBreakdown.input,
      output: leftBreakdown.output + rightBreakdown.output,
      total: leftBreakdown.total + rightBreakdown.total,
      uncached_input: leftBreakdown.uncachedInput + rightBreakdown.uncachedInput,
    };
  } else {
    delete result.estimated_cost_breakdown_usd;
  }
  result.cost_basis = normalizedLeft.cost_basis === normalizedRight.cost_basis
    ? normalizedRight.cost_basis
    : "mixed";
  return result;
}

function cacheRateTone(rate: number) {
  if (rate <= 50) return "cache-rate-critical";
  if (rate <= 70) return "cache-rate-low";
  if (rate <= 80) return "cache-rate-moderate";
  if (rate <= 90) return "cache-rate-good";
  return "cache-rate-excellent";
}

function estimatedModelCostParts(usage: Record<string, unknown> | undefined) {
  const raw = usage?.estimated_cost_breakdown_usd;
  if (typeof raw !== "object" || raw === null) return undefined;
  const costs = raw as Record<string, unknown>;
  return {
    cachedInput: usageNumber(costs, "cached_input"),
    input: usageNumber(costs, "input"),
    output: usageNumber(costs, "output"),
    total: usageNumber(costs, "total"),
    uncachedInput: usageNumber(costs, "uncached_input"),
  };
}

export function cumulativeSessionUsageByTurnSet(
  turnSets: TurnSet[],
  snapshots: Record<string, RunSnapshot>,
) {
  const usageByTurnSetId: Record<string, Record<string, unknown>> = {};
  let cumulativeUsage: Record<string, unknown> | undefined;
  for (const turnSet of turnSets) {
    const finalAssistantMessage = turnSet.messages.filter((message) => message.role === "assistant").at(-1);
    const snapshot = turnSet.runId ? snapshots[turnSet.runId] : undefined;
    const answerUsage = finalAssistantMessage?.metadata?.usage ?? snapshot?.usage;
    if (usageHasData(answerUsage)) cumulativeUsage = addUsage(cumulativeUsage, answerUsage!);
    if (cumulativeUsage) usageByTurnSetId[turnSet.id] = cumulativeUsage;
  }
  return usageByTurnSetId;
}

type UsageRow = {
  cost: string;
  label: string;
  tokens: string;
  tone?: string;
};

function UsageCostPopover({ usage, sessionUsage, model, provider }: {
  usage: Record<string, unknown> | undefined;
  sessionUsage: Record<string, unknown> | undefined;
  model?: string;
  provider?: string;
}) {
  const controlRef = useRef<HTMLSpanElement>(null);
  const popoverId = useId();
  const [popoverOpen, setPopoverOpen] = useState(false);
  const rawUsage = usage?.raw;
  const isSubscriptionUsage = provider === "codex"
    && typeof rawUsage === "object"
    && rawUsage !== null
    && (rawUsage as Record<string, unknown>).billing === "subscription_usage";
  const [usdKrwRate, setUsdKrwRate] = useState<number | null | undefined>(undefined);
  useEffect(() => {
    let active = true;
    void api.finance.getUsdKrwExchangeRate()
      .then((result) => {
        if (active) setUsdKrwRate(result.rate);
      })
      .catch(() => {
        if (active) setUsdKrwRate(null);
      });
    return () => { active = false; };
  }, []);
  const formatCost = (value: number | undefined) => {
    if (value === undefined) return "—";
    if (usdKrwRate === undefined) return "…";
    return usdKrwRate === null
      ? value.toFixed(3)
      : new Intl.NumberFormat("ko-KR").format(Math.round(value * usdKrwRate));
  };
  const currencySymbol = usdKrwRate === null ? "$" : "₩";
  const usageRows = (summary: Record<string, unknown> | undefined): UsageRow[] => {
    const input = usageNumber(summary, "input_tokens");
    const cached = usageNumber(summary, "cached_input_tokens");
    const uncached = summary?.uncached_input_tokens === undefined
      ? Math.max(0, input - cached)
      : usageNumber(summary, "uncached_input_tokens");
    const output = usageNumber(summary, "output_tokens");
    const cacheRatePercent = input > 0 ? (cached / input) * 100 : 0;
    const estimatedCosts = estimatedModelCostParts(summary);
    const reportedCost = optionalUsageNumber(summary, "cost_usd");
    return [
      { label: "Input", tokens: input.toLocaleString(), cost: formatCost(estimatedCosts?.input) },
      { label: "Cached", tokens: cached.toLocaleString(), cost: formatCost(estimatedCosts?.cachedInput) },
      { label: "Uncached", tokens: uncached.toLocaleString(), cost: formatCost(estimatedCosts?.uncachedInput) },
      { label: "Cache rate", tokens: `${cacheRatePercent.toFixed(1)}%`, cost: "-", tone: cacheRateTone(cacheRatePercent) },
      { label: "Output", tokens: output.toLocaleString(), cost: formatCost(estimatedCosts?.output) },
      { label: "Total", tokens: (input + output).toLocaleString(), cost: formatCost(reportedCost ?? estimatedCosts?.total) },
    ];
  };
  const answerRows = usageRows(usage);
  const cumulativeRows = usageRows(sessionUsage);
  const costHeading = `예상비용(${currencySymbol})`;
  return (
    <span
      className="answer-usage-control"
      ref={controlRef}
      onPointerEnter={() => setPopoverOpen(true)}
      onPointerLeave={() => setPopoverOpen(false)}
      onFocusCapture={() => setPopoverOpen(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setPopoverOpen(false);
      }}
    >
      <button className="answer-usage-button" type="button" aria-label={isSubscriptionUsage ? "토큰 및 예상 비용 확인" : "토큰 비용 확인"} aria-describedby={popoverOpen ? popoverId : undefined}><Coins size={16} /></button>
      <GlobalTooltipLayer anchor={controlRef.current} className="answer-usage-popover" id={popoverId} open={popoverOpen}>
        <table aria-label="이번 답변과 세션 누적 토큰 및 예상 비용">
          <colgroup>
            <col className="answer-usage-label-column" />
            <col /><col /><col /><col />
          </colgroup>
          <thead>
            <tr><th rowSpan={2}>{model || "사용량"}</th><th colSpan={2}>이번 답변</th><th colSpan={2}>세션 누적</th></tr>
            <tr><th>토큰</th><th>{costHeading}</th><th>토큰</th><th>{costHeading}</th></tr>
          </thead>
          <tbody>
            {answerRows.map((row, index) => (
              <tr className={row.label === "Total" ? "is-total" : row.label === "Cached" || row.label === "Uncached" || row.label === "Cache rate" ? "is-child" : ""} key={row.label}>
                <th scope="row">{row.label}</th>
                <td className={row.tone}>{row.tokens}</td><td>{row.cost}</td>
                <td className={cumulativeRows[index]?.tone}>{cumulativeRows[index]?.tokens ?? "0"}</td><td>{cumulativeRows[index]?.cost ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlobalTooltipLayer>
    </span>
  );
}

export function runStatusLabel(status: RunStatus | null | undefined) {
  if (status === "queued") return "대기 중";
  if (status === "preparing") return "준비 중";
  if (status === "model_streaming") return "응답 작성 중";
  if (status === "tools_running") return "도구 실행 중";
  if (status === "awaiting_approval") return "승인 대기";
  if (status === "paused") return "일시 정지";
  if (status === "completed") return "완료";
  if (status === "failed") return "실패";
  if (status === "cancelled") return "취소됨";
  if (status === "limit_reached") return "이전 버전에서 중단됨";
  if (status === "interrupted") return "중단됨";
  return "준비됨";
}

function toolStatusLabel(status: ToolExecution["status"]) {
  if (status === "streaming") return "작성 중";
  if (status === "running") return "실행 중";
  if (status === "queued") return "대기";
  if (status === "failed") return "실패";
  if (status === "cancelled") return "취소";
  return "완료";
}

function webSearchQuery(execution: ToolExecution) {
  if (!execution.toolName.toLocaleLowerCase().includes("web_search")) return null;
  const query = execution.input?.query;
  return typeof query === "string" && query.trim() ? query.trim() : null;
}

function webFetchSummary(execution: ToolExecution) {
  if (!execution.toolName.toLocaleLowerCase().includes("web_fetch")) return null;
  const source = execution.result?.source;
  if (source && typeof source === "object" && "title" in source) {
    const title = source.title;
    if (typeof title === "string" && title.trim()) return title.trim();
  }
  const rawUrl = execution.input?.url;
  if (typeof rawUrl !== "string" || !rawUrl.trim()) return null;
  let location = rawUrl.trim();
  try {
    const url = new URL(rawUrl);
    const lastPath = decodeURIComponent(url.pathname.split("/").filter(Boolean).at(-1) ?? "");
    location = lastPath ? `${url.hostname} · ${lastPath}` : url.hostname;
  } catch {
    // Keep the original URL when the tool input is not a standard absolute URL.
  }
  if (execution.status === "running") return `${location} · 페이지 불러오는 중`;
  if (execution.status === "queued") return `${location} · 가져오기 대기`;
  if (execution.status === "failed") return `${location} · 가져오기 실패`;
  if (execution.status === "cancelled") return `${location} · 가져오기 취소`;
  return location;
}

function createReportSummary(execution: ToolExecution) {
  if (!execution.toolName.toLocaleLowerCase().includes("create_report")) return null;
  const displayName = execution.result?.display_name;
  if (typeof displayName === "string" && displayName.trim()) return displayName.trim();
  const title = execution.input?.title;
  return typeof title === "string" && title.trim() ? title.trim() : null;
}

const TOKEN_PROGRESS_BUCKET_SIZE = 5_000;
const TOKEN_PROGRESS_STAGES = ["blue", "green", "orange", "red"] as const;

function writeFileName(execution: ToolExecution) {
  if (execution.toolName !== "write_file") return null;
  const candidates = [execution.progress?.fileName, execution.result?.path, execution.input?.path];
  for (const candidate of candidates) {
    if (typeof candidate !== "string" || !candidate.trim()) continue;
    return candidate.trim().replaceAll("\\", "/").split("/").filter(Boolean).at(-1) ?? null;
  }
  return null;
}

function tokenBucketProgress(tokens: number, targetTokens?: number) {
  const totalTokens = Math.max(0, Math.floor(tokens));
  const bucketIndex = totalTokens === 0
    ? 0
    : Math.floor((totalTokens - 1) / TOKEN_PROGRESS_BUCKET_SIZE);
  const bucketTokens = totalTokens === 0
    ? 0
    : ((totalTokens - 1) % TOKEN_PROGRESS_BUCKET_SIZE) + 1;
  const normalizedTarget = targetTokens && targetTokens > 0
    ? Math.floor(targetTokens)
    : null;
  return {
    stage: TOKEN_PROGRESS_STAGES[Math.min(bucketIndex, TOKEN_PROGRESS_STAGES.length - 1)],
    bucketTokens: normalizedTarget ? Math.min(totalTokens, normalizedTarget) : bucketTokens,
    maxTokens: normalizedTarget ?? TOKEN_PROGRESS_BUCKET_SIZE,
    percent: normalizedTarget
      ? Math.min(100, (totalTokens / normalizedTarget) * 100)
      : (bucketTokens / TOKEN_PROGRESS_BUCKET_SIZE) * 100,
  };
}

const httpStatusDescriptions: Record<number, string> = {
  200: "요청이 성공적으로 처리되었습니다.",
  201: "요청이 성공하여 새 리소스가 생성되었습니다.",
  202: "요청을 접수했으며 처리가 아직 진행 중일 수 있습니다.",
  204: "요청은 성공했지만 반환할 내용이 없습니다.",
  400: "요청 형식이나 전달한 값이 올바르지 않습니다.",
  401: "인증 정보가 없거나 올바르지 않아 요청을 처리할 수 없습니다.",
  402: "결제, 사용 한도 또는 서비스 정책 때문에 요청이 거부되었습니다.",
  403: "서버가 요청을 이해했지만 접근을 허용하지 않았습니다.",
  404: "요청한 페이지나 리소스를 찾을 수 없습니다.",
  405: "해당 주소에서 이 요청 방식은 허용되지 않습니다.",
  408: "서버가 요청을 기다리다가 제한 시간을 초과했습니다.",
  409: "현재 리소스 상태와 요청이 충돌했습니다.",
  410: "요청한 리소스가 영구적으로 삭제되었습니다.",
  413: "전송한 요청이나 파일의 크기가 너무 큽니다.",
  415: "서버가 요청 데이터 형식을 지원하지 않습니다.",
  422: "요청 형식은 맞지만 내용의 일부를 처리할 수 없습니다.",
  429: "짧은 시간에 요청이 너무 많아 일시적으로 제한되었습니다.",
  451: "법적 또는 정책상 이유로 접근할 수 없습니다.",
  500: "외부 서버 내부에서 예상하지 못한 오류가 발생했습니다.",
  501: "외부 서버가 요청한 기능을 지원하지 않습니다.",
  502: "중간 서버가 상위 서버에서 잘못된 응답을 받았습니다.",
  503: "외부 서버가 과부하 또는 점검으로 일시적으로 사용할 수 없습니다.",
  504: "중간 서버가 상위 서버의 응답을 기다리다가 제한 시간을 초과했습니다.",
};

function httpStatusExplanation(text: string) {
  const match = text.match(/\bHTTP\s+(\d{3})\b/i);
  if (!match) return null;
  const status = Number(match[1]);
  const description = httpStatusDescriptions[status]
    ?? (status >= 500 ? "외부 서버 측 문제로 요청을 정상 처리하지 못했습니다."
      : status >= 400 ? "요청 또는 접근 권한 문제로 서버가 요청을 처리하지 못했습니다."
        : status >= 300 ? "요청한 리소스가 다른 위치로 이동되었거나 추가 이동이 필요합니다."
          : status >= 200 ? "요청이 정상적으로 처리되었습니다."
            : "서버가 요청을 처리 중임을 알리는 응답입니다.");
  return `HTTP ${status}: ${description}`;
}

function ToolCallRow({
  execution,
  isOpen,
  summaryText,
  onToggle,
  onCopy,
}: {
  execution: ToolExecution;
  isOpen: boolean;
  summaryText?: string;
  onToggle: () => void;
  onCopy: (execution: ToolExecution) => void;
}) {
  const [overlayStyle, setOverlayStyle] = useState<CSSProperties | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!isOpen) {
      setOverlayStyle(null);
      return;
    }
    const updateOverlayPosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const top = rect.bottom + 2;
      setOverlayStyle({
        top,
        left: rect.left,
        width: rect.width,
        maxHeight: Math.max(160, window.innerHeight - top - 12),
      });
    };
    updateOverlayPosition();
    window.addEventListener("resize", updateOverlayPosition);
    window.addEventListener("scroll", updateOverlayPosition, true);
    return () => {
      window.removeEventListener("resize", updateOverlayPosition);
      window.removeEventListener("scroll", updateOverlayPosition, true);
    };
  }, [isOpen]);
  useEffect(() => {
    if (!isOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (triggerRef.current?.contains(target) || overlayRef.current?.contains(target)) return;
      onToggle();
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer, true);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer, true);
  }, [isOpen, onToggle]);
  const contentId = `tool-call-${execution.id}`;
  const complete = execution.status === "completed";
  const running = execution.status === "running" || execution.status === "streaming";
  const writeFileActive = execution.toolName === "write_file" && running;
  const [liveNow, setLiveNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running || !execution.startedAt) return;
    setLiveNow(Date.now());
    const timer = window.setInterval(() => setLiveNow(Date.now()), 100);
    return () => window.clearInterval(timer);
  }, [execution.startedAt, running]);
  const liveDurationMs = execution.durationMs ?? (
    running && execution.startedAt
      ? Math.max(0, liveNow - Date.parse(execution.startedAt))
      : null
  );
  const activeWriteFileName = writeFileName(execution);
  const headerDetail = activeWriteFileName ?? webSearchQuery(execution) ?? webFetchSummary(execution) ?? createReportSummary(execution);
  const writeProgress = tokenBucketProgress(execution.progress?.tokens ?? 0);
  const requestText = execution.input
    ? JSON.stringify(execution.input, null, 2)
    : execution.inputSummary.length
      ? execution.inputSummary.join("\n")
      : "입력 없음";
  const rawResultText = execution.result
    ? JSON.stringify(execution.result, null, 2)
    : execution.error || execution.resultSummary.join("\n") || (running ? "실행 중입니다." : "결과 요약 없음");
  const statusExplanation = httpStatusExplanation(rawResultText);
  const resultText = statusExplanation ? `${rawResultText}\n\n${statusExplanation}` : rawResultText;
  return (
    <div className={`tool-call ${isOpen ? "is-open" : ""}`}>
      <button ref={triggerRef} className={`tool-call-trigger ${summaryText ? "has-summary" : ""}`} type="button" aria-expanded={isOpen} aria-controls={contentId} onClick={onToggle}>
        {summaryText && <span className="tool-call-summary-text">{summaryText}</span>}
        {toolCallIcon(execution.toolName)}
        <span className="tool-call-label-with-status">
          <span className="tool-call-label">{execution.label || execution.toolName}</span>
          {running ? (
            <LoaderCircle className="status-icon is-running" size={15} aria-hidden="true" />
          ) : complete ? null : execution.status === "failed" ? (
            <AlertCircle className="status-icon status-warning" size={15} aria-hidden="true" />
          ) : (
            <Circle className="status-icon is-waiting" size={15} aria-hidden="true" />
          )}
        </span>
        <span className="tool-call-detail" title={headerDetail ?? undefined}>{headerDetail}</span>
        <span className={`tool-call-status status-${running ? "running" : complete ? "complete" : "warning"}`}>{toolStatusLabel(execution.status)}</span>
        <span className="tool-call-duration" title={execution.toolName === "write_file" ? "파일 내용 생성 시작부터 디스크 저장 완료까지의 시간" : "도구 실행 시간"}>{formatDuration(liveDurationMs)}</span>
        {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
      {writeFileActive && execution.progress && (
        <div className={`write-file-stream-progress is-${writeProgress.stage}`} role="status" aria-live="polite" aria-label={`${activeWriteFileName ?? "파일"} 작성 중 ${execution.progress.tokens.toLocaleString()} 토큰 ${execution.progress.lines.toLocaleString()}줄`}>
          <div className="write-file-stream-heading">
            <strong title={activeWriteFileName ?? undefined}>WRITE FILE · {activeWriteFileName ?? "파일명 확인 중"}</strong>
            <span>{execution.progress.tokens.toLocaleString()} 토큰 · {execution.progress.lines.toLocaleString()}줄</span>
          </div>
          <div className="write-file-stream-meter" role="progressbar" aria-label="현재 5,000 토큰 구간의 생성량" aria-valuemin={0} aria-valuemax={TOKEN_PROGRESS_BUCKET_SIZE} aria-valuenow={writeProgress.bucketTokens}>
            <span style={{ width: `${writeProgress.percent}%` }} />
          </div>
        </div>
      )}
      {isOpen && overlayStyle && createPortal(
        <div ref={overlayRef} className="tool-message is-global" id={contentId} style={overlayStyle}>
          <section className="tool-message-section">
            <div className="tool-message-heading"><span>도구 요청</span><code>{execution.toolName}</code></div>
            <SyntaxCode value={requestText} language={execution.input ? "json" : "plaintext"} />
          </section>
          <section className="tool-message-section">
            <div className="tool-message-heading"><span>도구 결과</span><span className="tool-message-state">{toolStatusLabel(execution.status)} · {formatDuration(execution.durationMs)}</span></div>
            <SyntaxCode value={resultText} language={execution.result ? "json" : "plaintext"} />
          </section>
          <div className="tool-message-actions">
            <button type="button" onClick={() => onCopy(execution)}><Copy size={13} /> 복사</button>
          </div>
        </div>,
        triggerRef.current?.closest(".app-shell") ?? document.body,
      )}
    </div>
  );
}

type ModelExchangeItem = { label: string; value: unknown };

function modelExchangeText(value: unknown) {
  return formatModelExchangeValue(value);
}

function ModelProcessingRow({ durationMs, running, sent, received, model, provider }: {
  durationMs: number;
  running: boolean;
  sent: ModelExchangeItem[];
  received: ModelExchangeItem[];
  model?: string;
  provider?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const contentId = useId();
  const exchangeSections = [
    { title: "Provider로 보냄", items: sent, empty: "이 단계에서 별도로 전달된 도구 결과가 없습니다." },
    { title: "Provider에서 받음", items: received, empty: running ? "응답을 수신하고 있습니다." : "공개 가능한 응답 내용이 없습니다." },
  ];

  return (
    <div className={`tool-call model-processing-call ${isOpen ? "is-open" : ""}`}>
      <button
        className={`tool-call-trigger model-processing-row ${running ? "" : "without-status-icon"}`}
        type="button"
        aria-expanded={isOpen}
        aria-controls={contentId}
        onClick={(event) => preserveConversationScrollPosition(event.currentTarget, () => setIsOpen((open) => !open))}
      >
        <Brain className="tool-kind-icon is-model-processing" size={15} aria-hidden="true" />
        <span className="tool-call-label-with-status model-processing-label">
          <span className="tool-call-label">AI 내부 추론</span>
          {running ? <LoaderCircle className="status-icon is-running" size={15} aria-hidden="true" /> : null}
        </span>
        <span className="tool-call-detail">모델 판단 · 내부 실행 합계</span>
        <span className={`tool-call-status status-${running ? "running" : "complete"}`}>{running ? "처리 중" : "완료"}</span>
        <span className="tool-call-duration" title="여러 모델 호출과 Skill·계획 처리, 재시도 시간을 합산한 값(외부 도구 실행 제외)">{formatDuration(durationMs)}</span>
        {isOpen ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}
      </button>
      {isOpen && (
        <div className="model-exchange" id={contentId}>
          <div className="model-exchange-heading">
            <strong>실제 교환 정보</strong>
            <span>{[provider, model].filter(Boolean).join(" · ") || "Provider"}</span>
          </div>
          <div className="model-exchange-columns">
            {exchangeSections.map((section) => (
              <section key={section.title}>
                <h4>{section.title}</h4>
                {section.items.length > 0 ? section.items.map((item, index) => (
                  <div className="model-exchange-item" key={`${item.label}-${index}`}>
                    <strong>{item.label}</strong>
                    <SyntaxCode value={modelExchangeText(item.value)} language={typeof item.value === "object" ? "json" : "plaintext"} />
                  </div>
                )) : <p>{section.empty}</p>}
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function toolCallGroupSummary(activities: RunActivity[]) {
  const counts = new Map<string, number>();
  for (const activity of activities) {
    if (activity.type !== "tool") continue;
    const name = activity.execution.toolName;
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts]
    .map(([name, count]) => `${name} ${count}회`)
    .join(" · ");
}

function toolCallGroupDuration(activities: RunActivity[]) {
  const durations = activities.flatMap((activity) => (
    activity.type === "tool" && activity.execution.durationMs !== null
      ? [activity.execution.durationMs]
      : []
  ));
  return durations.length === activities.length
    ? durations.reduce((total, duration) => total + duration, 0)
    : null;
}

function preserveConversationScrollPosition(target: HTMLElement, update: () => void) {
  const container = target.closest<HTMLElement>(".conversation-scroll");
  const scrollTop = container?.scrollTop;
  update();
  if (!container || scrollTop === undefined) return;
  window.requestAnimationFrame(() => {
    container.scrollTop = scrollTop;
  });
}

const runActivityRevealDelayMs = 85;

function useStaggeredRunActivities(activities: RunActivity[], enabled: boolean) {
  const [visibleCount, setVisibleCount] = useState(activities.length);
  const visibleCountRef = useRef(visibleCount);
  const firstActivityIdRef = useRef(activities[0]?.id ?? "");

  useEffect(() => {
    visibleCountRef.current = visibleCount;
  }, [visibleCount]);

  useEffect(() => {
    const firstActivityId = activities[0]?.id ?? "";
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (!enabled || reduceMotion || firstActivityIdRef.current !== firstActivityId || visibleCountRef.current > activities.length) {
      firstActivityIdRef.current = firstActivityId;
      visibleCountRef.current = activities.length;
      setVisibleCount(activities.length);
      return undefined;
    }
    if (visibleCountRef.current >= activities.length) return undefined;
    const timer = window.setTimeout(() => {
      setVisibleCount((current) => {
        const next = Math.min(activities.length, current + 1);
        visibleCountRef.current = next;
        return next;
      });
    }, runActivityRevealDelayMs);
    return () => window.clearTimeout(timer);
  }, [activities.length, activities[0]?.id, enabled, visibleCount]);

  return activities.slice(0, visibleCount);
}

function RunActivityTimeline({
  activities,
  timelineStartedAtMs,
  timelineFinishedAtMs,
  timelineRunning,
  keepLatestToolGroupOpen,
  userRequest,
  assistantResponse,
  model,
  provider,
  openCalls,
  onToggleCall,
  onCopy,
  onVisibleGrowth,
}: {
  activities: RunActivity[];
  timelineStartedAtMs: number;
  timelineFinishedAtMs: number;
  timelineRunning: boolean;
  keepLatestToolGroupOpen: boolean;
  userRequest: string;
  assistantResponse: string;
  model?: string;
  provider?: string;
  openCalls: Set<string>;
  onToggleCall: (id: string) => void;
  onCopy: (execution: ToolExecution) => void;
  onVisibleGrowth?: () => void;
}) {
  const [openSummaryIds, setOpenSummaryIds] = useState<Set<string>>(new Set());
  const previousAutoOpenSummaryIds = useRef<Set<string>>(new Set());
  const visibleActivities = useStaggeredRunActivities(activities, timelineRunning);
  const latestVisibleActivityId = visibleActivities.at(-1)?.id ?? "";
  const activityGroups = visibleActivities.reduce<RunActivity[][]>((groups, activity) => {
    if (activity.type === "progress_summary" || activity.type === "skill" || groups.length === 0) groups.push([]);
    groups.at(-1)?.push(activity);
    return groups;
  }, []);
  const progressStageTimings = progressStageTimingById(
    activityGroups.flatMap((group) => {
      const summary = group[0]?.type === "progress_summary" ? group[0] : null;
      return summary ? [{ id: summary.id, createdAt: summary.createdAt }] : [];
    }),
    timelineStartedAtMs,
    timelineFinishedAtMs,
  );
  const activeSummaryIds = new Set(activityGroups.flatMap((group) => {
    const summary = group[0]?.type === "progress_summary" ? group[0] : null;
    const toolCount = group.filter((activity) => activity.type === "tool").length;
    const hasActiveTools = group.some((activity) => activity.type === "tool"
      && (activity.execution.status === "queued" || activity.execution.status === "running"));
    return summary && toolCount > 1 && hasActiveTools ? [summary.id] : [];
  }));
  const latestToolGroupSummaryId = activityGroups.reduce<string | null>((latestId, group) => {
    const summary = group[0]?.type === "progress_summary" ? group[0] : null;
    const toolCount = group.filter((activity) => activity.type === "tool").length;
    return summary && toolCount > 1 ? summary.id : latestId;
  }, null);
  const latestProgressSummaryId = activityGroups.reduce<string | null>((latestId, group) => {
    const summary = group[0]?.type === "progress_summary" ? group[0] : null;
    return summary?.id ?? latestId;
  }, null);
  const autoOpenSummaryIds = new Set(activeSummaryIds);
  if (keepLatestToolGroupOpen && latestToolGroupSummaryId) autoOpenSummaryIds.add(latestToolGroupSummaryId);
  const autoOpenSummaryKey = [...autoOpenSummaryIds].sort().join("|");

  useEffect(() => {
    const previous = previousAutoOpenSummaryIds.current;
    setOpenSummaryIds((current) => {
      const next = new Set(current);
      previous.forEach((id) => {
        if (!autoOpenSummaryIds.has(id)) next.delete(id);
      });
      autoOpenSummaryIds.forEach((id) => {
        if (!previous.has(id)) next.add(id);
      });
      return next;
    });
    previousAutoOpenSummaryIds.current = autoOpenSummaryIds;
  }, [autoOpenSummaryKey]);

  useEffect(() => {
    if (timelineRunning && latestVisibleActivityId) onVisibleGrowth?.();
  }, [latestVisibleActivityId, onVisibleGrowth, timelineRunning]);

  return (
    <section className="run-activity-timeline" aria-label="실행 과정">
      {activityGroups.map((group, groupIndex) => {
        const summary = group[0]?.type === "progress_summary" ? group[0] : null;
        const skill = group[0]?.type === "skill" ? group[0] : null;
        const toolActivities = group.filter((activity) => activity.type === "tool");
        const nextGroup = activityGroups[groupIndex + 1] ?? null;
        const nextSummary = nextGroup?.[0]?.type === "progress_summary" ? nextGroup[0] : null;
        const nextToolActivities = nextGroup?.filter((activity) => activity.type === "tool") ?? [];
        const sent: ModelExchangeItem[] = toolActivities.length > 0
          ? toolActivities.map((activity) => ({
              label: `${activity.execution.label || activity.execution.toolName} 결과`,
              value: activity.execution.result ?? activity.execution.error ?? activity.execution.resultSummary,
            }))
          : groupIndex === 0 && userRequest
            ? [{ label: "사용자 요청", value: userRequest }]
            : [];
        const received: ModelExchangeItem[] = [
          ...(nextSummary ? [{ label: "다음 단계", value: nextSummary.text }] : []),
          ...nextToolActivities.map((activity) => ({
            label: `${activity.execution.label || activity.execution.toolName} 호출`,
            value: activity.execution.input ?? activity.execution.inputSummary,
          })),
          ...(groupIndex === activityGroups.length - 1 && assistantResponse
            ? [{ label: "답변", value: assistantResponse }]
            : []),
        ];
        const hasToolGroup = toolActivities.length > 1;
        const toolsOpen = !hasToolGroup || (summary ? openSummaryIds.has(summary.id) : true);
        const stageTiming = summary ? progressStageTimings.get(summary.id) ?? null : null;
        const stageDurationMs = stageTiming?.durationMs ?? null;
        const toolActiveDurationMs = stageTiming
          ? mergedToolActiveDurationMs(
              toolActivities.map((activity) => activity.execution),
              stageTiming.startedAtMs,
              stageTiming.finishedAtMs,
            )
          : 0;
        const modelProcessingDurationMs = stageTiming
          ? Math.max(0, stageTiming.durationMs - toolActiveDurationMs)
          : null;
        const hasModelProcessingRow = modelProcessingDurationMs !== null && modelProcessingDurationMs >= 10;
        const timedChildCount = toolActivities.length + (hasModelProcessingRow ? 1 : 0);
        const showStageDuration = timedChildCount !== 1;
        const modelProcessingRunning = timelineRunning && summary?.id === latestProgressSummaryId;
        const toolGroupId = summary ? `progress-tools-${summary.id}` : undefined;
        const toggleTools = (event: ReactMouseEvent<HTMLButtonElement>) => {
          preserveConversationScrollPosition(event.currentTarget, () => {
            setOpenSummaryIds((current) => {
              if (!summary) return current;
              const next = new Set(current);
              if (next.has(summary.id)) next.delete(summary.id);
              else next.add(summary.id);
              return next;
            });
          });
        };
        return (
          <div className="progress-group" key={summary?.id ?? group[0]?.id}>
            {skill && (
              <div className="skill-activity" aria-label={`사용 Skill ${skill.slug}`}>
                <Sparkles size={14} aria-hidden="true" />
                <span className="skill-activity-kind">Skill</span>
                <strong>{skill.slug}</strong>
                <span className="skill-activity-detail">
                  {skill.reason} · {skill.appliedBy === "auto" ? "AI 선택" : skill.appliedBy === "explicit" ? "$Skill 호출" : "예약 적용"}
                </span>
              </div>
            )}
            {summary && (hasToolGroup ? (
              <button className="progress-group-toggle" type="button" aria-controls={toolGroupId} aria-expanded={toolsOpen} onClick={toggleTools}>
                <div className={`progress-summary phase-${summary.phase}`}>
                  <div className="progress-summary-text">
                    <span>{summary.text}</span>
                  </div>
                </div>
                <div className="tool-call-group-summary">
                  {toolCallIcon(toolActivities[0].execution.toolName, 14)}
                  <span>{toolCallGroupSummary(toolActivities)}</span>
                  <span className="tool-call-group-duration" title="단계 전체 소요 시간">{formatDuration(stageDurationMs ?? toolCallGroupDuration(toolActivities))}</span>
                  {toolsOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                </div>
              </button>
            ) : (
              <div className={`progress-summary phase-${summary.phase}`}><div className="progress-summary-text"><span>{summary.text}</span>{showStageDuration && <span className="progress-summary-duration" title="단계 전체 소요 시간">{formatDuration(stageDurationMs)}</span>}</div></div>
            ))}
            {toolsOpen && summary && (
              <div className="progress-tools" id={toolGroupId}>
                {toolActivities.map((activity) => (
                  <ToolCallRow
                    execution={activity.execution}
                    isOpen={openCalls.has(activity.execution.id)}
                    key={activity.id}
                    onCopy={onCopy}
                    onToggle={() => onToggleCall(activity.execution.id)}
                  />
                ))}
                {hasModelProcessingRow && (
                  <ModelProcessingRow
                    durationMs={modelProcessingDurationMs}
                    running={modelProcessingRunning}
                    sent={sent}
                    received={received}
                    model={model}
                    provider={provider}
                  />
                )}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

function messageDeliveryLabel(message: ChatMessage, commands: RunCommand[]) {
  const command = commands.find((item) => item.messageId === message.id);
  const commandType = command?.type ?? message.metadata?.command_type;
  const commandStatus = command?.status ?? message.metadata?.command_status;
  if (commandType === "queue_next") {
    if (commandStatus === "cancelled") return "Queue · 취소됨";
    if (command?.queuePosition) return `Queue · ${command.queuePosition}번 대기`;
    return message.status === "pending" ? "Queue · 대기 중" : "Queue · 실행됨";
  }
  if (commandType === "steer") {
    if (commandStatus === "cancelled") return "Steering · 취소됨";
    return commandStatus === "waiting_safe_boundary" || message.status === "pending"
      ? "Steering · 반영 대기"
      : "Steering · 반영됨";
  }
  return message.status === "pending" ? "접수 중" : null;
}

interface CitationTarget {
  source: SourceEvidence;
  markerNumber: number;
  cited: boolean;
  reviewed: boolean;
}

const circledCitationMarkers = [
  "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
  "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳",
] as const;

function citationMarkerLabel(markerNumber: number) {
  return circledCitationMarkers[markerNumber - 1] ?? `[${markerNumber}]`;
}

function citationTargets(text: string, sources: SourceEvidence[], citations: MessageCitation[]) {
  return sources.map((source, index): CitationTarget => {
    const citation = citations.find((item) => (item.sourceId ?? item.source_id) === source.sourceId);
    const explicitMarker = citation?.markerNumber ?? citation?.marker_number;
    const markerNumber = explicitMarker && explicitMarker > 0 ? explicitMarker : index + 1;
    const hasSourceToken = text.includes(`[${source.sourceId}]`) || text.includes(`[[${source.sourceId}]]`);
    const hasMarkerToken = text.includes(citationMarkerLabel(markerNumber)) || text.includes(`[${markerNumber}]`);
    return {
      source,
      markerNumber,
      cited: citation ? citation.status === "cited" || citation.status === "resolved" : hasSourceToken || hasMarkerToken,
      reviewed: source.evidenceKind === "fetched_content",
    };
  });
}

function citationLinkUrl(sourceId: string) {
  return `#lumina-source=${encodeURIComponent(sourceId)}`;
}

function splitCitationText(value: string, targets: CitationTarget[]): PhrasingContent[] | null {
  const citedTargets = targets.filter((target) => target.cited);
  if (citedTargets.length === 0) return null;
  const byToken = new Map<string, CitationTarget>();
  citedTargets.forEach((target) => {
    byToken.set(target.source.sourceId, target);
    byToken.set(String(target.markerNumber), target);
    byToken.set(citationMarkerLabel(target.markerNumber), target);
  });
  const parts: PhrasingContent[] = [];
  const pattern = /\[\[([^\]\n]+)\]\]|\[([^\]\n]+)\]|[①-⑳]/gu;
  let lastIndex = 0;
  for (const match of value.matchAll(pattern)) {
    const token = match[1] ?? match[2] ?? match[0];
    const target = byToken.get(token);
    if (!target || match.index === undefined) continue;
    if (match.index > lastIndex) {
      parts.push({ type: "text", value: value.slice(lastIndex, match.index) } satisfies Text);
    }
    parts.push({
      type: "link",
      url: citationLinkUrl(target.source.sourceId),
      children: [{ type: "text", value: citationMarkerLabel(target.markerNumber) }],
    } satisfies Link);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex === 0) return null;
  if (lastIndex < value.length) parts.push({ type: "text", value: value.slice(lastIndex) } satisfies Text);
  return parts;
}

function normalizeCitationPositions(text: string, targets: CitationTarget[]) {
  const byToken = new Map<string, CitationTarget>();
  targets.filter((target) => target.cited).forEach((target) => {
    byToken.set(target.source.sourceId, target);
    byToken.set(String(target.markerNumber), target);
    byToken.set(citationMarkerLabel(target.markerNumber), target);
  });
  if (byToken.size === 0) return text;

  const markerPattern = /\[\[([^\]\n]+)\]\]|\[([^\]\n]+)\]|[①-⑳]/gu;
  const sentenceEndPattern = /[.!?。！？]+(?=\s|$)/gu;
  let inFence = false;
  return text.split(/(\r?\n)/).map((line) => {
    if (/^\s*(`{3,}|~{3,})/.test(line)) {
      inFence = !inFence;
      return line;
    }
    if (inFence || /^\r?\n$/.test(line)) return line;

    const boundaries = [...line.matchAll(sentenceEndPattern)].map((match) => (match.index ?? 0) + match[0].length);
    boundaries.push(line.length);
    let start = 0;
    return boundaries.map((boundary) => {
      if (boundary <= start) return "";
      const sentence = line.slice(start, boundary);
      start = boundary;
      const matches = [...sentence.matchAll(markerPattern)].filter((match) => {
        const token = match[1] ?? match[2] ?? match[0];
        return byToken.has(token);
      });
      if (matches.length === 0) return sentence;
      let cleaned = sentence;
      [...matches].reverse().forEach((match) => {
        const index = match.index ?? 0;
        let removalStart = index;
        let removalEnd = index + match[0].length;
        const before = cleaned.slice(Math.max(0, removalStart - 2), removalStart);
        const after = cleaned.slice(removalEnd, removalEnd + 2);
        if ((before === "**" || before === "__") && /[ \t]/.test(cleaned[removalEnd] ?? "")) removalEnd += 1;
        if ((after === "**" || after === "__") && /[ \t]/.test(cleaned[removalStart - 1] ?? "")) removalStart -= 1;
        cleaned = cleaned.slice(0, removalStart) + cleaned.slice(removalEnd);
      });
      cleaned = cleaned.replace(/[ \t]{2,}/g, " ").trimEnd();
      return `${cleaned} ${matches.map((match) => match[0]).join(" ")}`;
    }).join("");
  }).join("");
}

function remarkCitationLinks(options: { targets: CitationTarget[] }) {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index: number | undefined, parent: Parent | undefined) => {
      if (index === undefined || !parent || parent.type === "link" || parent.type === "linkReference") return;
      const replacement = splitCitationText(node.value, options.targets);
      if (!replacement) return;
      parent.children.splice(index, 1, ...replacement);
      return index + replacement.length;
    });
  };
}

function CitationMarker({ target }: { target: CitationTarget }) {
  const tooltipId = useId();
  const markerRef = useRef<HTMLElement | null>(null);
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const marker = citationMarkerLabel(target.markerNumber);
  const rawUrl = target.source.normalizedUrl || target.source.originalUrl;
  const safeUrl = defaultUrlTransform(rawUrl);
  const tooltip = (
    <GlobalTooltipLayer anchor={markerRef.current} className="citation-tooltip" id={tooltipId} open={tooltipOpen}>
      <strong>{target.source.title || target.source.domain || `출처 ${target.markerNumber}`}</strong>
      <span>{rawUrl || "URL 없음"}</span>
      <q>{target.source.verbatimExcerpt || "근거 문장 없음"}</q>
    </GlobalTooltipLayer>
  );
  if (!safeUrl) {
    return <span className="inline-citation" ref={(node) => { markerRef.current = node; }} tabIndex={0} aria-label={`출처 ${target.markerNumber}`} aria-describedby={tooltipOpen ? tooltipId : undefined} onMouseEnter={() => setTooltipOpen(true)} onMouseLeave={() => setTooltipOpen(false)} onFocus={() => setTooltipOpen(true)} onBlur={() => setTooltipOpen(false)}><span aria-hidden="true">{marker}</span>{tooltip}</span>;
  }
  return (
    <a className="inline-citation" ref={(node) => { markerRef.current = node; }} href={safeUrl} target="_blank" rel="noreferrer noopener" aria-label={`출처 ${target.markerNumber}: ${target.source.title || target.source.domain}`} aria-describedby={tooltipOpen ? tooltipId : undefined} onMouseEnter={() => setTooltipOpen(true)} onMouseLeave={() => setTooltipOpen(false)} onFocus={() => setTooltipOpen(true)} onBlur={() => setTooltipOpen(false)}>
      <span aria-hidden="true">{marker}</span>{tooltip}
    </a>
  );
}

const emptySources: SourceEvidence[] = [];
const emptyCitations: MessageCitation[] = [];

function normalizeKoreanMarkdownEmphasis(text: string) {
  return text.replace(/(\*\*[^*\n]+?\*\*)(?=[가-힣])/gu, "$1<!-- -->");
}

type StreamingPendingKind = "mermaid" | "chart" | "table" | null;

function splitStreamingMarkdown(text: string) {
  const source = text.replace(/\r\n/g, "\n");
  let stableBoundary = 0;
  let position = 0;
  let inFence = false;
  let fenceMarker = "";
  for (const match of source.matchAll(/[^\n]*(?:\n|$)/g)) {
    const rawLine = match[0];
    if (!rawLine) break;
    const lineEnd = position + rawLine.length;
    const line = rawLine.endsWith("\n") ? rawLine.slice(0, -1) : rawLine;
    const fence = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (fence) {
      const marker = fence[1];
      if (!inFence) {
        inFence = true;
        fenceMarker = marker;
      } else if (marker[0] === fenceMarker[0] && marker.length >= fenceMarker.length) {
        inFence = false;
        stableBoundary = lineEnd;
      }
    } else if (!inFence && line.trim() === "") {
      stableBoundary = lineEnd;
    }
    position = lineEnd;
  }
  return { prefix: source.slice(0, stableBoundary).trimEnd(), liveTail: source.slice(stableBoundary) };
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

function pendingStreamingKind(liveTail: string): StreamingPendingKind {
  const lines = liveTail.replace(/\r\n/g, "\n").trimStart().split("\n");
  const fence = lines[0]?.match(/^(`{3,}|~{3,})\s*([A-Za-z0-9_-]+)?/);
  if (fence) {
    const marker = fence[1];
    const closed = lines.slice(1).some((line) => {
      const close = line.match(/^ {0,3}(`{3,}|~{3,})\s*$/);
      return Boolean(close && close[1][0] === marker[0] && close[1].length >= marker.length);
    });
    const language = String(fence[2] || "").toLowerCase();
    if (!closed && (language === "mermaid" || language === "mmd")) return "mermaid";
    if (!closed && language === "lumina-chart") return "chart";
  }
  for (let index = 1; index < lines.length; index += 1) {
    if (isMarkdownTableRow(lines[index - 1]) && isMarkdownTableDivider(lines[index])) return "table";
  }
  return null;
}

function StreamingBlockPending({ kind }: { kind: Exclude<StreamingPendingKind, null> }) {
  const label = kind === "mermaid" ? "다이어그램 작성 중" : kind === "chart" ? "인터랙티브 차트 작성 중" : "표 작성 중";
  return (
    <div className={`stream-block-pending is-${kind}`} role="status">
      {kind === "mermaid" ? <GitBranch size={18} /> : <Table2 size={18} />}
      <span>{label}</span>
      <LoaderCircle className="is-running" size={15} />
    </div>
  );
}

export function pastedTextAttachmentLabel(attachment: AttachmentSummary, index: number) {
  const lineCount = Number(attachment.metadata?.lineCount ?? 0);
  return `[텍스트 첨부 #${index + 1}${lineCount > 0 ? ` +${lineCount}줄` : ""}]`;
}

export function MarkdownResponse({
  text,
  sources = emptySources,
  citations = emptyCitations,
  streaming = false,
  artifact = false,
}: {
  text: string;
  sources?: SourceEvidence[];
  citations?: MessageCitation[];
  streaming?: boolean;
  artifact?: boolean;
}) {
  const targets = useMemo(() => citationTargets(text, sources, citations), [citations, sources, text]);
  const renderedText = useMemo(() => streaming ? text : normalizeCitationPositions(text, targets), [streaming, targets, text]);
  const streamingParts = useMemo(() => streaming ? splitStreamingMarkdown(renderedText) : { prefix: renderedText, liveTail: "" }, [renderedText, streaming]);
  const pendingKind = useMemo(() => streaming ? pendingStreamingKind(streamingParts.liveTail) : null, [streaming, streamingParts.liveTail]);
  const prefixText = useMemo(() => normalizeKoreanMarkdownEmphasis(streamingParts.prefix), [streamingParts.prefix]);
  const tailText = useMemo(() => normalizeKoreanMarkdownEmphasis(streamingParts.liveTail), [streamingParts.liveTail]);
  const targetById = useMemo(() => new Map(targets.map((target) => [target.source.sourceId, target])), [targets]);
  const remarkPlugins = useMemo<NonNullable<ReactMarkdownOptions["remarkPlugins"]>>(
    () => [remarkGfm, [remarkCitationLinks, { targets }]],
    [targets],
  );
  const components = useMemo<Components>(() => ({
    a: ({ href, children }) => {
      const prefix = "#lumina-source=";
      if (href?.startsWith(prefix)) {
        try {
          const target = targetById.get(decodeURIComponent(href.slice(prefix.length)));
          if (target) return <CitationMarker target={target} />;
        } catch {
          return <span>{children}</span>;
        }
      }
      const safeHref = href ? defaultUrlTransform(href) : "";
      if (!safeHref) return <span>{children}</span>;
      if (safeHref.startsWith("#")) return <a href={safeHref}>{children}</a>;
      return <a href={safeHref} target="_blank" rel="noreferrer noopener">{children}</a>;
    },
    img: ({ src, alt }) => {
      const safeSrc = src ? defaultUrlTransform(src) : "";
      return safeSrc
        ? <InlineMarkdownImage src={safeSrc} alt={alt || ""} />
        : <span>{alt || "이미지"}</span>;
    },
    table: ({ children }) => <div className="markdown-table-scroll"><table>{children}</table></div>,
    code: ({ className, children }) => {
      const language = /language-([\w-]+)/.exec(className || "")?.[1]?.toLowerCase();
      const source = String(children).replace(/\n$/, "");
      return language === "mermaid" || language === "mmd"
        ? <MermaidDiagram source={source} />
        : language === "lumina-chart"
          ? <InteractiveChart source={source} />
        : language
          ? <SyntaxCodeContent value={source} language={language} className={className} />
          : <code className={className}>{children}</code>;
    },
  }), [targetById]);

  return (
    <div className={`markdown-response ${streaming ? "streaming-text" : ""} ${artifact ? "artifact-markdown-content" : ""}`}>
      {prefixText && <ReactMarkdown skipHtml remarkPlugins={remarkPlugins} components={components} urlTransform={defaultUrlTransform}>{prefixText}</ReactMarkdown>}
      {pendingKind
        ? <StreamingBlockPending kind={pendingKind} />
        : tailText && <ReactMarkdown skipHtml remarkPlugins={remarkPlugins} components={components} urlTransform={defaultUrlTransform}>{tailText}</ReactMarkdown>}
    </div>
  );
}

export function AssistantTurn({
  turnSet,
  snapshot,
  sessionUsage,
  openCalls,
  onToggleCall,
  onCopyTool,
  onOpenArtifact,
  onBranch,
  onShare,
  onToast,
  onVisibleGrowth,
}: {
  turnSet: TurnSet;
  snapshot: RunSnapshot | null;
  sessionUsage: Record<string, unknown> | undefined;
  openCalls: Set<string>;
  onToggleCall: (id: string) => void;
  onCopyTool: (execution: ToolExecution) => void;
  onOpenArtifact: (artifact: ArtifactSummary) => void;
  onBranch: (anchorMessageId: string) => Promise<void>;
  onShare: (anchorMessageId: string | null) => void;
  onToast: (message: string) => void;
  onVisibleGrowth: () => void;
}) {
  const userMessages = turnSet.messages.filter((message) => message.role === "user");
  const assistantMessages = turnSet.messages.filter((message) => message.role === "assistant");
  const finalMessage = assistantMessages.at(-1) ?? null;
  const sources = finalMessage?.metadata?.sources ?? [];
  const citations = finalMessage?.metadata?.citations ?? [];
  const searches = finalMessage?.metadata?.searchInvocations ?? [];
  const artifacts = snapshot?.artifacts ?? turnSet.artifacts;
  const assistantText = finalMessage?.text || snapshot?.assistantDraft?.text || "";
  const sanitizedAssistantText = sanitizeAssistantResponse(assistantText, artifacts.length > 0);
  const sourceTargets = citationTargets(sanitizedAssistantText, sources, citations);
  const citedSourceCount = sourceTargets.filter((target) => target.cited).length;
  const reviewedSourceCount = sourceTargets.filter((target) => !target.cited && target.reviewed).length;
  const referenceSourceCount = sources.length - citedSourceCount - reviewedSourceCount;
  const sourceCountLabels = [
    citedSourceCount > 0 ? `인용 ${citedSourceCount}` : null,
    reviewedSourceCount > 0 ? `본문 확인 ${reviewedSourceCount}` : null,
    referenceSourceCount > 0 ? `검색 참고 ${referenceSourceCount}` : null,
  ].filter((label): label is string => label !== null);
  const tools = snapshot?.toolExecutions ?? turnSet.toolExecutions;
  const activities: RunActivity[] = snapshot?.activities?.length
    ? snapshot.activities
    : tools.map((execution, index) => ({
        id: `tool:${execution.id}`,
        type: "tool" as const,
        sequence: index,
        execution,
      }));
  const pendingCommands = snapshot?.pendingCommands ?? [];
  const status = snapshot?.status ?? (finalMessage ? "completed" : null);
  const terminal = isTerminalRunStatus(status);
  const terminalReason = status && status !== "completed"
    ? snapshot?.errorMessage?.trim() || (status === "cancelled" ? "요청에 따라 작업을 취소했습니다." : "작업을 완료하지 못했습니다. 다시 실행해 주세요.")
    : "";
  const copyableAnswerText = sanitizedAssistantText || terminalReason;
  const streaming = !finalMessage && Boolean(snapshot?.assistantDraft);
  const { visibleText: displayedText, revealing } = useStreamingText(sanitizedAssistantText, streaming);
  const [reportOpen, setReportOpen] = useState(false);
  const [markdownSaving, setMarkdownSaving] = useState(false);
  const [branching, setBranching] = useState(false);
  const [reportText, setReportText] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [answerRating, setAnswerRating] = useState<"like" | "dislike" | null>(null);
  const [ratingSubmitting, setRatingSubmitting] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [expandedSourceId, setExpandedSourceId] = useState<string | null>(null);
  const [previewAttachment, setPreviewAttachment] = useState<AttachmentSummary | null>(null);
  const [textPreviewAttachment, setTextPreviewAttachment] = useState<AttachmentSummary | null>(null);
  const [textPreviewContent, setTextPreviewContent] = useState("");
  const [textPreviewError, setTextPreviewError] = useState<string | null>(null);
  const [workDetailsOpen, setWorkDetailsOpen] = useState(!terminal);
  const [workClock, setWorkClock] = useState(() => Date.now());
  const expandedSourceTarget = sourceTargets.find(({ source }) => source.sourceId === expandedSourceId) ?? null;
  const workStartedAt = snapshot?.startedAt ?? turnSet.createdAt;
  const workFinishedAt = snapshot?.finishedAt ?? turnSet.completedAt;
  const workStartedAtMs = new Date(workStartedAt).getTime();
  const workFinishedAtMs = workFinishedAt ? new Date(workFinishedAt).getTime() : workClock;
  const workDuration = Number.isFinite(workStartedAtMs) && Number.isFinite(workFinishedAtMs)
    ? formatWorkDuration(workFinishedAtMs - workStartedAtMs)
    : "0초";
  const hasWorkDetails = activities.length > 0;

  useEffect(() => {
    setWorkDetailsOpen(!terminal);
  }, [snapshot?.runId, terminal]);

  useEffect(() => {
    setAnswerRating(null);
  }, [finalMessage?.id]);

  useEffect(() => {
    if (terminal || !hasWorkDetails) return;
    setWorkClock(Date.now());
    const timer = window.setInterval(() => setWorkClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [hasWorkDetails, terminal]);

  const openSourceDetail = useCallback((sourceId: string) => {
    const currentDetail = window.history.state?.luminaSourceDetail;
    const nextState = { ...window.history.state, luminaSourceDetail: { turnSetId: turnSet.id, sourceId } };
    if (currentDetail?.turnSetId === turnSet.id) window.history.replaceState(nextState, "");
    else window.history.pushState(nextState, "");
    setExpandedSourceId(sourceId);
  }, [turnSet.id]);

  const returnToSourceList = useCallback(() => {
    if (window.history.state?.luminaSourceDetail?.turnSetId === turnSet.id) window.history.back();
    else setExpandedSourceId(null);
  }, [turnSet.id]);

  const closeSources = useCallback(() => {
    setSourcesOpen(false);
    setExpandedSourceId(null);
    if (window.history.state?.luminaSourceDetail?.turnSetId === turnSet.id) window.history.back();
  }, [turnSet.id]);

  useEffect(() => {
    const handlePopState = (event: PopStateEvent) => {
      const detail = event.state?.luminaSourceDetail;
      if (detail?.turnSetId === turnSet.id && typeof detail.sourceId === "string") {
        setSourcesOpen(true);
        setExpandedSourceId(detail.sourceId);
      } else {
        setExpandedSourceId(null);
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [turnSet.id]);

  useEffect(() => {
    if (!textPreviewAttachment) return;
    const controller = new AbortController();
    setTextPreviewContent("");
    setTextPreviewError(null);
    void fetch(attachmentContentUrl(textPreviewAttachment.id), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then(setTextPreviewContent)
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setTextPreviewError("텍스트 첨부 내용을 불러오지 못했습니다.");
      });
    return () => controller.abort();
  }, [textPreviewAttachment]);

  useEffect(() => {
    if (revealing && displayedText) onVisibleGrowth();
  }, [displayedText, onVisibleGrowth, revealing]);

  const copyAnswer = async () => {
    if (!copyableAnswerText) {
      onToast("복사할 내용이 없습니다.");
      return;
    }
    try {
      if (sanitizedAssistantText) await copyText(sanitizedAssistantText);
      else await copyText(terminalReason);
      onToast(sanitizedAssistantText ? "답변을 복사했습니다." : "중단 사유를 복사했습니다.");
    } catch {
      onToast("답변을 복사하지 못했습니다.");
    }
  };
  const saveAnswerAsMarkdown = async () => {
    if (!finalMessage || !sanitizedAssistantText || markdownSaving) {
      onToast("Markdown으로 저장할 답변이 없습니다.");
      return;
    }
    setMarkdownSaving(true);
    try {
      const artifact = await api.artifacts.createFromMessage(finalMessage.id);
      onToast("답변을 Markdown Artifact로 저장했습니다.");
      onOpenArtifact(artifact);
    } catch {
      onToast("답변을 Markdown Artifact로 저장하지 못했습니다.");
    } finally {
      setMarkdownSaving(false);
    }
  };
  const branchAnswer = async () => {
    if (!finalMessage || branching) return;
    setBranching(true);
    try {
      await onBranch(finalMessage.id);
    } finally {
      setBranching(false);
    }
  };
  const rateAnswer = async (value: "like" | "dislike") => {
    if (!finalMessage || ratingSubmitting) return;
    const previousRating = answerRating;
    const nextRating = answerRating === value ? null : value;
    setAnswerRating(nextRating);
    setRatingSubmitting(true);
    try {
      if (nextRating === null) {
        await api.messages.deleteRating(finalMessage.id);
      } else {
        await api.messages.putRating(finalMessage.id, nextRating);
      }
    } catch {
      setAnswerRating(previousRating);
      onToast("평가를 기록하지 못했습니다.");
    } finally {
      setRatingSubmitting(false);
    }
  };
  const reportAnswer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!finalMessage || !reportText.trim() || reportSubmitting) return;
    setReportSubmitting(true);
    setReportError(null);
    try {
      await api.messages.report(finalMessage.id, reportText.trim());
      setReportText("");
      setReportOpen(false);
      onToast("의견을 게시했습니다.");
    } catch {
      setReportError("의견을 게시하지 못했습니다. 다시 시도해 주세요.");
    } finally {
      setReportSubmitting(false);
    }
  };
  const artifactUsage = snapshot?.artifactProgress
    ?? snapshot?.artifactUsage
    ?? finalMessage?.metadata?.artifactUsage
    ?? null;
  const artifactProgress = artifactUsage
    ? tokenBucketProgress(artifactUsage.tokens, artifactUsage.targetTokens)
    : null;
  const runUsage = finalMessage?.metadata?.usage ?? snapshot?.usage;
  const modelOutputTokens = usageNumber(runUsage, "output_tokens");
  return (
    <div className="turn-set" data-run-id={turnSet.runId ?? undefined}>
      {userMessages.map((message) => (
        <div className="user-message-group" data-question-anchor={message.id} key={message.id}>
          {message.attachments?.length > 0 && (
            <div className="user-message-attachments">
              {message.attachments.map((attachment, attachmentIndex) => attachment.kind === "image" ? (
                <button
                  className="user-image-attachment"
                  type="button"
                  aria-label={`${attachment.fileName} 이미지 크게 보기`}
                  onClick={() => setPreviewAttachment(attachment)}
                  key={attachment.id}
                >
                  <img src={attachmentContentUrl(attachment.id)} alt={attachment.fileName} />
                </button>
              ) : attachment.kind === "pasted_text" ? (
                <div className="user-pasted-attachment-wrap" key={attachment.id}>
                  <button
                    className="user-pasted-attachment"
                    type="button"
                    aria-expanded={textPreviewAttachment?.id === attachment.id}
                    onClick={() => setTextPreviewAttachment((current) => current?.id === attachment.id ? null : attachment)}
                  >
                    <FileText size={14} />
                    <span>{pastedTextAttachmentLabel(attachment, message.attachments.slice(0, attachmentIndex).filter((item) => item.kind === "pasted_text").length)}</span>
                  </button>
                  {textPreviewAttachment?.id === attachment.id && (
                    <>
                      <button className="text-attachment-backdrop" type="button" aria-label="텍스트 첨부 닫기" onClick={() => setTextPreviewAttachment(null)} />
                      <div className="text-attachment-popover" role="dialog" aria-label={`${attachment.fileName} 내용`}>
                        <button className="text-attachment-close" type="button" aria-label="텍스트 첨부 닫기" onClick={() => setTextPreviewAttachment(null)}><X size={18} /></button>
                        {textPreviewError
                          ? <p role="alert">{textPreviewError}</p>
                          : textPreviewContent
                            ? <SyntaxCode value={textPreviewContent} fileName={attachment.fileName} mimeType={attachment.mimeType} />
                            : <p>내용을 불러오는 중...</p>}
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <a className="user-file-attachment" href={attachmentContentUrl(attachment.id)} target="_blank" rel="noreferrer noopener" key={attachment.id}>
                  <FileText size={15} /> {attachment.fileName}
                </a>
              ))}
            </div>
          )}
          <div className="user-message">
            {message.text && <div className="user-message-text">{message.text}</div>}
          </div>
          {messageDeliveryLabel(message, pendingCommands) && <small className="message-state">{messageDeliveryLabel(message, pendingCommands)}</small>}
        </div>
      ))}
      {hasWorkDetails && (
        <section className={`turn-work-details ${workDetailsOpen ? "is-open" : ""}`} aria-label="답변 작업 과정">
          <button
            className="turn-work-trigger"
            type="button"
            aria-controls={`turn-work-details-${turnSet.id}`}
            aria-expanded={workDetailsOpen}
            onClick={(event) => preserveConversationScrollPosition(event.currentTarget, () => setWorkDetailsOpen((open) => !open))}
          >
            <span>{workDuration} 동안 작업</span>
            <ChevronRight size={15} aria-hidden="true" />
          </button>
          {workDetailsOpen && (
            <div className="turn-tool-activity" id={`turn-work-details-${turnSet.id}`}>
              <RunActivityTimeline
                activities={activities}
                timelineStartedAtMs={workStartedAtMs}
                timelineFinishedAtMs={workFinishedAtMs}
                timelineRunning={!terminal}
                keepLatestToolGroupOpen={status === "model_streaming"}
                userRequest={userMessages.at(-1)?.text ?? ""}
                assistantResponse={sanitizedAssistantText}
                model={snapshot?.execution.runtimeModelId}
                provider={snapshot?.execution.providerId}
                openCalls={openCalls}
                onCopy={onCopyTool}
                onToggleCall={onToggleCall}
                onVisibleGrowth={onVisibleGrowth}
              />
            </div>
          )}
        </section>
      )}
      {previewAttachment && (
        <div className="image-attachment-viewer" role="dialog" aria-modal="true" aria-label={`${previewAttachment.fileName} 이미지 보기`} onClick={(event) => { if (event.target === event.currentTarget) setPreviewAttachment(null); }}>
          <button type="button" aria-label="이미지 닫기" onClick={() => setPreviewAttachment(null)}><X size={18} /></button>
          <img src={attachmentContentUrl(previewAttachment.id)} alt={previewAttachment.fileName} />
        </div>
      )}
      {(assistantText || tools.length > 0 || artifacts.length > 0 || snapshot) && (
        <section className="assistant-turn">
          <div className="assistant-content">
            {assistantText && <MarkdownResponse text={displayedText} sources={sources} citations={citations} streaming={revealing} />}
            {artifactUsage && artifactProgress && (
              <div className={`artifact-progress-count is-${artifactProgress.stage}`} role="status" aria-live={terminal ? undefined : "polite"} aria-label={`문서 ${artifactUsage.estimated === false ? "완성 분량" : "작성 중 추정 분량"} ${artifactUsage.tokens.toLocaleString()} 토큰 ${artifactUsage.lines.toLocaleString()}줄${modelOutputTokens > 0 ? `, 모델 출력 누계 ${modelOutputTokens.toLocaleString()} 토큰` : ""}`}>
                <div className="artifact-progress-heading">
                  <span>{artifactUsage.estimated === false ? "문서 약" : "작성 중 약"} {artifactUsage.tokens.toLocaleString()}토큰 · {artifactUsage.lines.toLocaleString()}줄{artifactUsage.targetTokens ? ` · 목표 ${artifactUsage.targetTokens.toLocaleString()}토큰` : ""}</span>
                  {modelOutputTokens > 0 && (
                    <span className="artifact-model-output">
                      모델 출력 누계 {modelOutputTokens.toLocaleString()}토큰
                      <button
                        className="artifact-model-output-help"
                        type="button"
                        aria-label="작성 중 토큰과 모델 출력 누계의 차이"
                        data-tooltip="작성 중은 현재 문서 본문의 추정량이고, 모델 출력 누계는 이번 작업의 모든 모델 응답을 합산한 값입니다."
                      >
                        ⓘ
                      </button>
                    </span>
                  )}
                </div>
                <div className="artifact-progress-meter" role="progressbar" aria-label={artifactUsage.targetTokens ? "선택한 문서 목표 분량 대비 작성량" : "현재 5,000 토큰 구간의 생성량"} aria-valuemin={0} aria-valuemax={artifactProgress.maxTokens} aria-valuenow={artifactProgress.bucketTokens}>
                  <span className="artifact-progress-fill" style={{ width: `${artifactProgress.percent}%` }} />
                </div>
              </div>
            )}
            {artifacts.map((artifact) => (
              <button className="artifact-result" type="button" key={artifact.id} onClick={() => onOpenArtifact(artifact)}>
                <FileCode2 size={18} />
                <span className="artifact-result-title">{artifact.currentVersion > 1 && <small>(v{artifact.currentVersion})</small>}<strong>{artifact.displayName}</strong></span>
                <span className="artifact-result-action">문서 열기 <ChevronRight size={14} /></span>
              </button>
            ))}
            {terminal && (
              <div className="final-answer">
                <div className="final-answer-meta">
                  <div className={`final-answer-status ${status !== "completed" ? "is-error" : ""}`}>
                    {status === "completed" ? <CheckCircle2 size={17} /> : <AlertCircle size={17} />}
                    {status === "completed" ? "작성 완료" : runStatusLabel(status)}
                  </div>
                  <div className="answer-actions" role="group" aria-label="답변 작업">
                    <UsageCostPopover
                      usage={runUsage}
                      sessionUsage={sessionUsage}
                      model={snapshot?.execution.runtimeModelId}
                      provider={snapshot?.execution.providerId}
                    />
                    <button className="tooltip-control" type="button" aria-label="답변 복사" data-tooltip="복사" disabled={!copyableAnswerText} onClick={() => void copyAnswer()}><Copy size={16} /></button>
                    <button className="tooltip-control" type="button" aria-label="답변 저장" data-tooltip="저장" disabled={!finalMessage || !sanitizedAssistantText || markdownSaving} onClick={() => void saveAnswerAsMarkdown()}>{markdownSaving ? <LoaderCircle className="is-running" size={16} /> : <Download size={16} />}</button>
                    <button className="tooltip-control" type="button" aria-label="이 답변까지 새 채팅으로 분기" data-tooltip="여기서 분기" disabled={!finalMessage || branching} onClick={() => void branchAnswer()}>{branching ? <LoaderCircle className="is-running" size={16} /> : <BranchFromHereIcon size={16} />}</button>
                    <button className="tooltip-control" type="button" aria-label="답변 공유" data-tooltip="공유" disabled={!assistantText} onClick={() => onShare(finalMessage?.id ?? null)}><ShareActionIcon size={16} /></button>
                    <button className={`tooltip-control answer-rating-control ${answerRating === "like" ? "is-like" : ""}`} type="button" aria-label="좋아요" aria-pressed={answerRating === "like"} data-tooltip="좋아요" disabled={!finalMessage || ratingSubmitting} onClick={() => void rateAnswer("like")}><ThumbsUp size={16} /></button>
                    <button className={`tooltip-control answer-rating-control ${answerRating === "dislike" ? "is-dislike" : ""}`} type="button" aria-label="싫어요" aria-pressed={answerRating === "dislike"} data-tooltip="싫어요" disabled={!finalMessage || ratingSubmitting} onClick={() => void rateAnswer("dislike")}><ThumbsDown size={16} /></button>
                    <button className={`tooltip-control ${reportOpen ? "is-active" : ""}`} type="button" aria-label="의견 게시" aria-expanded={reportOpen} data-tooltip="의견 게시" disabled={!finalMessage} onClick={() => { setReportOpen((open) => !open); setReportError(null); }}><MessageSquarePlus size={16} /></button>
                  </div>
                  <time className="answer-completed-time" dateTime={snapshot?.finishedAt ?? finalMessage?.completedAt ?? undefined}>{formatCompletedAt(snapshot?.finishedAt ?? finalMessage?.completedAt)}</time>
                  {sourceCountLabels.length > 0 && (
                    <div className="answer-sources">
                      <button
                        className="answer-sources-trigger"
                        type="button"
                        aria-label={`검색 및 참고 출처, ${sourceCountLabels.join(", ")}`}
                        aria-expanded={sourcesOpen}
                        onClick={() => { if (sourcesOpen) closeSources(); else setSourcesOpen(true); }}
                      >
                        <span>검색 및 참고 출처</span>
                        {citedSourceCount > 0 && <span className="answer-source-count is-cited"> · 인용 {citedSourceCount}</span>}
                        {reviewedSourceCount > 0 && <span className="answer-source-count is-reviewed"> · 본문 확인 {reviewedSourceCount}</span>}
                        {referenceSourceCount > 0 && <span className="answer-source-count is-reference-only"> · 검색 참고 {referenceSourceCount}</span>}
                      </button>
                      {sourcesOpen && (
                        <>
                          <button className="answer-sources-backdrop" type="button" aria-label="검색 및 참고 출처 닫기" onClick={closeSources} />
                          <div className="answer-sources-popover">
                            {expandedSourceTarget ? (
                              <div className="source-detail">
                                <div className="source-detail-navigation">
                                  <button className="source-detail-back" type="button" onClick={returnToSourceList}><ArrowLeft size={14} /> 출처 목록으로</button>
                                  <button className="source-detail-back is-icon" type="button" aria-label="출처 목록으로 돌아가기" onClick={returnToSourceList}><ArrowLeft size={15} /></button>
                                </div>
                                <div className="source-header">
                                  <span className={`source-kind${expandedSourceTarget.cited ? "" : expandedSourceTarget.reviewed ? " is-reviewed" : " is-reference-only"}`}>{expandedSourceTarget.cited ? `${citationMarkerLabel(expandedSourceTarget.markerNumber)} 본문 인용` : expandedSourceTarget.reviewed ? "본문 확인" : "검색 참고"}</span>
                                  {defaultUrlTransform(expandedSourceTarget.source.normalizedUrl || expandedSourceTarget.source.originalUrl)
                                    ? <a href={defaultUrlTransform(expandedSourceTarget.source.normalizedUrl || expandedSourceTarget.source.originalUrl)} target="_blank" rel="noreferrer noopener">{expandedSourceTarget.source.title || expandedSourceTarget.source.domain}</a>
                                    : <strong>{expandedSourceTarget.source.title || expandedSourceTarget.source.domain}</strong>}
                                  <small>{expandedSourceTarget.source.domain}</small>
                                </div>
                                <p className="source-detail-excerpt">{expandedSourceTarget.source.verbatimExcerpt}</p>
                              </div>
                            ) : (
                              <>
                                {searches.length > 0 && (
                                  <div className="source-queries">{searches.map((search) => <span key={search.invocationId}>{search.query}</span>)}</div>
                                )}
                                <ol>
                                  {sourceTargets.map(({ source, markerNumber, cited, reviewed }) => (
                                    <li className={cited ? "is-cited" : reviewed ? "is-reviewed" : "is-reference-only"} key={source.sourceId}>
                                      <div className="source-header">
                                        <span className="source-kind">{cited ? `${citationMarkerLabel(markerNumber)} 본문 인용` : reviewed ? "본문 확인" : "검색 참고"}</span>
                                        {defaultUrlTransform(source.normalizedUrl || source.originalUrl)
                                          ? <a href={defaultUrlTransform(source.normalizedUrl || source.originalUrl)} target="_blank" rel="noreferrer noopener">{source.title || source.domain}</a>
                                          : <strong>{source.title || source.domain}</strong>}
                                        <small>{source.domain}</small>
                                        </div>
                                      {source.verbatimExcerpt && (
                                        <div className="source-excerpt-row">
                                          <button className="source-excerpt" type="button" aria-label={`${source.title || source.domain} 확대해서 보기`} onClick={() => openSourceDetail(source.sourceId)}>{source.verbatimExcerpt}</button>
                                          <button type="button" aria-label={`${source.title || source.domain} 본문 복사`} onClick={() => {
                                            void copyText(source.verbatimExcerpt ?? "")
                                              .then(() => onToast("전체 내용을 복사했습니다. 메모장에 붙여넣어 확인하세요."))
                                              .catch(() => onToast("전체 내용을 복사하지 못했습니다."));
                                          }}><Copy size={12} /></button>
                                        </div>
                                      )}
                                    </li>
                                  ))}
                                </ol>
                              </>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
                {terminalReason && <p className="final-answer-error" role="alert">{terminalReason}</p>}
                {reportOpen && (
                  <form className="answer-feedback-form" onSubmit={(event) => void reportAnswer(event)}>
                    <label htmlFor={`feedback-${finalMessage?.id}`}>이 답변에서 개선이 필요한 점</label>
                    <textarea id={`feedback-${finalMessage?.id}`} autoFocus maxLength={4000} placeholder="부정확한 내용, 누락된 정보, UI·도구 문제 등을 적어 주세요." value={reportText} onChange={(event) => setReportText(event.currentTarget.value)} />
                    {reportError && <p role="alert">{reportError}</p>}
                    <div><span>{reportText.length.toLocaleString()} / 4,000</span><button type="button" onClick={() => { setReportOpen(false); setReportError(null); }}>취소</button><button className="is-primary lumina-primary-action" type="submit" disabled={!reportText.trim() || reportSubmitting}>{reportSubmitting && <LoaderCircle className="is-running" size={14} />}게시</button></div>
                  </form>
                )}
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

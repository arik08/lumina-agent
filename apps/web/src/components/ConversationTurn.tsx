import {
  AlertCircle,
  ArrowDown,
  ArrowLeft,
  Bot,
  BookPlus,
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
  Globe2,
  Image as ImageIcon,
  LoaderCircle,
  MessageCircleQuestion,
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
import { useSharedNow } from "../shared-clock";
import { isTerminalRunStatus, runActivityOutcome, shouldCollapseRunWorkDetails, type RunActivityOutcome } from "../run-status";
import type { Link, Parent, PhrasingContent, Root, Text } from "mdast";
import {
  Children,
  isValidElement,
  lazy,
  memo,
  Suspense,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  type UIEvent as ReactUIEvent,
} from "react";
import ReactMarkdown, {
  defaultUrlTransform,
  type Components,
  type Options as ReactMarkdownOptions,
} from "react-markdown";
import { createPortal, flushSync } from "react-dom";
import remarkGfm from "remark-gfm";
import { visit } from "unist-util-visit";
import { api, attachmentContentUrl, saveKnowledgeDocumentFromMessage, type UsdKrwExchangeRate } from "../api";
import { ImageAttachmentViewer } from "./ImageAttachmentViewer";
import { TextAttachmentViewer } from "./TextAttachmentViewer";
import type {
  ArtifactSummary,
  AttachmentSummary,
  ChatMessage,
  ClarificationMode,
  MessageCitation,
  RunActivity,
  RunCommand,
  RunSnapshot,
  RunStatus,
  SourceEvidence,
  ToolExecution,
  TurnSet,
  UserInputAnswer,
} from "../api-types";
import { sanitizeAssistantResponse } from "../assistant-response";
import { GlobalTooltipLayer } from "./GlobalTooltip";
import { formatModelExchangeValue } from "../model-exchange-format";
import {
  mergedToolActiveDurationMs,
  progressStageTimingById,
} from "../run-activity-duration";
import { useStreamingText } from "../streaming-ui";
import { useRunAssistantDraft } from "../run-assistant-draft-store";
import { useRunArtifactProgress } from "../run-artifact-progress-store";
import { useStreamingMarkdownParts, type StreamingPendingKind } from "../streaming-markdown";
import { SyntaxCode, SyntaxCodeContent } from "./SyntaxCode";
import { BranchFromHereIcon, ShareActionIcon } from "./ActionIcons";
import { UserInputRequestCard } from "./UserInputRequestCard";

const InlineMarkdownImage = lazy(() => import("./InteractiveResponse").then((module) => ({
  default: module.InlineMarkdownImage,
})));
const InteractiveChart = lazy(() => import("./InteractiveResponse").then((module) => ({
  default: module.InteractiveChart,
})));
const MermaidDiagram = lazy(() => import("./InteractiveResponse").then((module) => ({
  default: module.MermaidDiagram,
})));

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
  initialUsage: Record<string, unknown> | undefined,
  turnSets: TurnSet[],
  snapshots: Record<string, RunSnapshot>,
) {
  const usageByTurnSetId: Record<string, Record<string, unknown>> = {};
  let cumulativeUsage = usageHasData(initialUsage)
    ? normalizedUsage(initialUsage!)
    : undefined;
  for (const turnSet of turnSets) {
    const finalAssistantMessage = turnSet.messages.filter((message) => message.role === "assistant").at(-1);
    const snapshot = turnSet.runId ? snapshots[turnSet.runId] : undefined;
    const answerUsage = finalAssistantMessage?.metadata?.usage ?? snapshot?.usage;
    if (usageHasData(answerUsage)) cumulativeUsage = addUsage(cumulativeUsage, answerUsage!);
    if (cumulativeUsage) usageByTurnSetId[turnSet.id] = cumulativeUsage;
  }
  return usageByTurnSetId;
}

export function sessionUsageRevision(
  initialUsage: Record<string, unknown> | undefined,
  turnSets: TurnSet[],
  snapshots: Record<string, RunSnapshot>,
) {
  return `${JSON.stringify(initialUsage ?? null)}|${turnSets.map((turnSet) => {
    const finalAssistantMessage = turnSet.messages.filter((message) => message.role === "assistant").at(-1);
    const snapshot = turnSet.runId ? snapshots[turnSet.runId] : undefined;
    return `${turnSet.id}:${JSON.stringify(finalAssistantMessage?.metadata?.usage ?? snapshot?.usage ?? null)}`;
  }).join("|")}`;
}

type UsageRow = {
  cost: string;
  label: string;
  tokens: string;
  tone?: string;
};

function UsageCostPopover({ usage, sessionUsage, showSessionUsage, model, provider }: {
  usage: Record<string, unknown> | undefined;
  sessionUsage: Record<string, unknown> | undefined;
  showSessionUsage: boolean;
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
  const [exchangeRate, setExchangeRate] = useState<UsdKrwExchangeRate | undefined>(undefined);
  useEffect(() => {
    let active = true;
    void api.finance.getUsdKrwExchangeRate()
      .then((result) => {
        if (active) setExchangeRate(result);
      })
      .catch(() => {
        if (active) {
          setExchangeRate({
            base: "USD",
            quote: "KRW",
            rate: null,
            asOf: null,
            source: null,
            status: "unavailable",
          });
        }
      });
    return () => { active = false; };
  }, []);
  const usdKrwRate = exchangeRate?.rate;
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
  const cumulativeRows = showSessionUsage ? usageRows(sessionUsage) : [];
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
      <GlobalTooltipLayer anchor={controlRef.current} className={`answer-usage-popover ${showSessionUsage ? "" : "is-answer-only"}`} id={popoverId} open={popoverOpen}>
        <table aria-label={showSessionUsage ? "이번 답변과 세션 누적 토큰 및 예상 비용" : "이번 답변 토큰 및 예상 비용"}>
          <colgroup>
            <col className="answer-usage-label-column" />
            <col /><col />
            {showSessionUsage && <><col /><col /></>}
          </colgroup>
          <thead>
            <tr><th rowSpan={2}>{model || "사용량"}</th><th colSpan={2}>이번 답변</th>{showSessionUsage && <th colSpan={2}>세션 누적</th>}</tr>
            <tr><th>토큰</th><th>{costHeading}</th>{showSessionUsage && <><th>토큰</th><th>{costHeading}</th></>}</tr>
          </thead>
          <tbody>
            {answerRows.map((row, index) => (
              <tr className={row.label === "Total" ? "is-total" : row.label === "Cached" || row.label === "Uncached" || row.label === "Cache rate" ? "is-child" : ""} key={row.label}>
                <th scope="row">{row.label}</th>
                <td className={row.tone}>{row.tokens}</td><td>{row.cost}</td>
                {showSessionUsage && <><td className={cumulativeRows[index]?.tone}>{cumulativeRows[index]?.tokens ?? "0"}</td><td>{cumulativeRows[index]?.cost ?? "—"}</td></>}
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
  if (status === "awaiting_input") return "답변 대기";
  if (status === "paused") return "일시 정지";
  if (status === "completed") return "완료";
  if (status === "failed") return "실패";
  if (status === "cancelled") return "중지됨";
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
  runOutcome,
  terminalAtMs,
  summaryText,
  onToggle,
  onCopy,
}: {
  execution: ToolExecution;
  isOpen: boolean;
  runOutcome: RunActivityOutcome;
  terminalAtMs: number;
  summaryText?: string;
  onToggle: () => void;
  onCopy: (execution: ToolExecution) => void;
}) {
  const [overlayStyle, setOverlayStyle] = useState<CSSProperties | null>(null);
  const [copied, setCopied] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const copyFeedbackTimerRef = useRef<number | null>(null);
  useEffect(() => () => {
    if (copyFeedbackTimerRef.current !== null) window.clearTimeout(copyFeedbackTimerRef.current);
  }, []);
  useEffect(() => {
    if (!isOpen) setCopied(false);
  }, [isOpen]);
  useEffect(() => {
    if (!isOpen) {
      setOverlayStyle(null);
      return;
    }
    const updateOverlayPosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const top = rect.bottom + 2;
      const availableHeight = Math.max(160, window.innerHeight - top - 12);
      const preferredHeight = Math.max(160, Math.round(window.innerHeight * 0.6));
      setOverlayStyle({
        top,
        left: rect.left,
        width: rect.width,
        maxHeight: Math.min(520, preferredHeight, availableHeight),
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
  const executionActive = execution.status === "queued" || execution.status === "running" || execution.status === "streaming";
  const stoppedByRun = executionActive && (runOutcome === "stopped" || runOutcome === "failed");
  const running = executionActive && !stoppedByRun;
  const writeFileActive = execution.toolName === "write_file" && running;
  const liveNow = useSharedNow(running && Boolean(execution.startedAt), 100);
  const liveDurationMs = execution.durationMs ?? (
    (running || stoppedByRun) && execution.startedAt
      ? Math.max(0, (stoppedByRun ? terminalAtMs : liveNow) - Date.parse(execution.startedAt))
      : null
  );
  const activeWriteFileName = writeFileName(execution);
  const headerDetail = activeWriteFileName ?? webSearchQuery(execution) ?? webFetchSummary(execution) ?? createReportSummary(execution);
  const writeProgress = tokenBucketProgress(execution.progress?.tokens ?? 0);
  const toolDetailText = useMemo(() => {
    if (!isOpen) return null;
    const requestText = execution.input
      ? JSON.stringify(execution.input, null, 2)
      : execution.inputSummary.length
        ? execution.inputSummary.join("\n")
        : "입력 없음";
    const rawResultText = execution.result
      ? JSON.stringify(execution.result, null, 2)
      : execution.error || execution.resultSummary.join("\n") || (stoppedByRun ? "Run 중지로 도구 실행이 종료되었습니다." : running ? "실행 중입니다." : "결과 요약 없음");
    const statusExplanation = httpStatusExplanation(rawResultText);
    return {
      requestText,
      resultText: statusExplanation ? `${rawResultText}\n\n${statusExplanation}` : rawResultText,
    };
  }, [execution.error, execution.input, execution.inputSummary, execution.result, execution.resultSummary, isOpen, running, stoppedByRun]);
  const handleCopy = () => {
    onCopy(execution);
    setCopied(true);
    if (copyFeedbackTimerRef.current !== null) window.clearTimeout(copyFeedbackTimerRef.current);
    copyFeedbackTimerRef.current = window.setTimeout(() => {
      setCopied(false);
      copyFeedbackTimerRef.current = null;
    }, 1600);
  };
  return (
    <div className={`tool-call ${isOpen ? "is-open" : ""}`}>
      <button ref={triggerRef} className={`tool-call-trigger ${summaryText ? "has-summary" : ""}`} type="button" aria-expanded={isOpen} aria-controls={contentId} onClick={onToggle}>
        {summaryText && <span className="tool-call-summary-text">{summaryText}</span>}
        {toolCallIcon(execution.toolName)}
        <span className="tool-call-label-with-status">
          <span className="tool-call-label">{execution.label || execution.toolName}</span>
          {running ? (
            <LoaderCircle className="status-icon is-running" size={15} aria-hidden="true" />
          ) : stoppedByRun || execution.status === "failed" ? (
            <AlertCircle className="status-icon status-warning" size={15} aria-hidden="true" />
          ) : complete ? null : (
            <Circle className="status-icon is-waiting" size={15} aria-hidden="true" />
          )}
        </span>
        <span className="tool-call-detail" data-tooltip={headerDetail ?? undefined}>{headerDetail}</span>
        <span className={`tool-call-status status-${running ? "running" : complete ? "complete" : "warning"}`}>{stoppedByRun ? (runOutcome === "failed" ? "실패" : "중지됨") : toolStatusLabel(execution.status)}</span>
        <span className="tool-call-duration" data-tooltip={execution.toolName === "write_file" ? "파일 내용 생성 시작부터 디스크 저장 완료까지의 시간" : "도구 실행 시간"}>{formatDuration(liveDurationMs)}</span>
        {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
      {writeFileActive && execution.progress && (
        <div className={`write-file-stream-progress is-${writeProgress.stage}`} role="status" aria-live="polite" aria-label={`${activeWriteFileName ?? "파일"} 작성 중 ${execution.progress.tokens.toLocaleString()} 토큰 ${execution.progress.lines.toLocaleString()}줄`}>
          <div className="write-file-stream-heading">
            <strong data-tooltip={activeWriteFileName ?? undefined}>WRITE FILE · {activeWriteFileName ?? "파일명 확인 중"}</strong>
            <span>{execution.progress.tokens.toLocaleString()} 토큰 · {execution.progress.lines.toLocaleString()}줄</span>
          </div>
          <div className="write-file-stream-meter" role="progressbar" aria-label="현재 5,000 토큰 구간의 생성량" aria-valuemin={0} aria-valuemax={TOKEN_PROGRESS_BUCKET_SIZE} aria-valuenow={writeProgress.bucketTokens}>
            <span style={{ width: `${writeProgress.percent}%` }} />
          </div>
        </div>
      )}
      {isOpen && overlayStyle && toolDetailText && createPortal(
        <div ref={overlayRef} className="tool-message is-global" id={contentId} style={overlayStyle}>
          <div className="tool-message-actions">
            <button className={copied ? "is-copied" : undefined} type="button" aria-live="polite" onClick={handleCopy}>
              {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "복사됨" : "복사"}
            </button>
          </div>
          <section className="tool-message-section">
            <div className="tool-message-heading"><span>도구 요청</span><code>{execution.toolName}</code></div>
            <SyntaxCode value={toolDetailText.requestText} language={execution.input ? "json" : "plaintext"} />
          </section>
          <section className="tool-message-section">
            <div className="tool-message-heading"><span>도구 결과</span><span className="tool-message-state">{stoppedByRun ? (runOutcome === "failed" ? "실패" : "중지됨") : toolStatusLabel(execution.status)} · {formatDuration(liveDurationMs)}</span></div>
            <SyntaxCode value={toolDetailText.resultText} language={execution.result ? "json" : "plaintext"} />
          </section>
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

type ModelProcessingState = RunActivityOutcome | "awaiting_input";

function ModelProcessingRow({ durationMs, state, sent, received, model, provider, reasoningTokens }: {
  durationMs: number;
  state: ModelProcessingState;
  sent: ModelExchangeItem[];
  received: ModelExchangeItem[];
  model?: string;
  provider?: string;
  reasoningTokens?: number;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const contentId = useId();
  const running = state === "running";
  const awaitingInput = state === "awaiting_input";
  const statusLabel = running ? "처리 중" : awaitingInput ? "답변 대기" : state === "completed" ? "완료" : state === "failed" ? "실패" : "중지됨";
  const exchangeSections = [
    { title: "Provider로 보냄", items: sent, empty: "이 단계에서 별도로 전달된 도구 결과가 없습니다." },
    { title: "Provider에서 받음", items: received, empty: running ? "응답을 수신하고 있습니다." : state === "stopped" ? "모델 응답이 완료되기 전에 작업을 중지했습니다." : "공개 가능한 응답 내용이 없습니다." },
  ];

  useEffect(() => {
    if (!isOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        if (rootRef.current) preserveConversationScrollPosition(rootRef.current, () => setIsOpen(false));
      }
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [isOpen]);

  return (
    <div className={`tool-call model-processing-call ${isOpen ? "is-open" : ""}`} ref={rootRef}>
      <button
        className={`tool-call-trigger model-processing-row ${running ? "" : "without-status-icon"}`}
        type="button"
        aria-expanded={isOpen}
        aria-controls={contentId}
        onClick={(event) => preserveConversationScrollPosition(event.currentTarget, () => setIsOpen((open) => !open))}
      >
        {awaitingInput
          ? <MessageCircleQuestion className="tool-kind-icon is-model-processing" size={15} aria-hidden="true" />
          : <Brain className="tool-kind-icon is-model-processing" size={15} aria-hidden="true" />}
        <span className="tool-call-label-with-status model-processing-label">
          <span className="tool-call-label">{awaitingInput ? "Q&A" : "Thinking"}</span>
          {running ? <LoaderCircle className="status-icon is-running" size={15} aria-hidden="true" /> : null}
          {!running && !awaitingInput && state !== "completed" ? <AlertCircle className="status-icon status-warning" size={15} aria-hidden="true" /> : null}
        </span>
        <span className="tool-call-detail">{awaitingInput ? "확인 질문 · 사용자 답변 대기" : state === "stopped" ? "사용자 요청으로 모델 처리를 중지했습니다." : `모델 판단 · 내부 실행 합계${reasoningTokens === undefined ? "" : ` · 내부 추론 ${reasoningTokens.toLocaleString()} 토큰`}`}</span>
        <span className={`tool-call-status status-${running ? "running" : state === "completed" ? "complete" : "warning"}`}>{statusLabel}</span>
        <span className="tool-call-duration" data-tooltip="여러 모델 호출과 Skill·계획 처리, 재시도 시간을 합산한 값(외부 도구 실행 제외)">{formatDuration(durationMs)}</span>
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
const toolGroupMinimumVisibleMs = 700;
const toolGroupCompletionSettleMs = 500;
const toolGroupContentExitMs = 240;
const toolGroupReflowMs = 350;
const toolGroupReflowEasing = "cubic-bezier(0.22, 1, 0.36, 1)";

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

function WorkDurationLabel({
  startedAtMs,
  finishedAtMs,
  running,
  statusSuffix,
}: {
  startedAtMs: number;
  finishedAtMs: number | null;
  running: boolean;
  statusSuffix: string;
}) {
  const clockNow = useSharedNow(running);

  const effectiveFinishedAtMs = finishedAtMs ?? clockNow;
  const duration = Number.isFinite(startedAtMs) && Number.isFinite(effectiveFinishedAtMs)
    ? formatWorkDuration(effectiveFinishedAtMs - startedAtMs)
    : "0초";
  return <span>{duration} 동안 작업{statusSuffix}</span>;
}

function RunActivityTimeline({
  activities,
  timelineStartedAtMs,
  timelineFinishedAtMs,
  timelineRunning,
  awaitingInput,
  runOutcome,
  keepLatestToolGroupOpen,
  userRequest,
  assistantResponse,
  model,
  provider,
  reasoningTokens,
  openCalls,
  onToggleCall,
  onCopy,
  clarificationMode,
  inputBusy,
  onSubmitUserInput,
  onClarificationModeChange,
}: {
  activities: RunActivity[];
  timelineStartedAtMs: number;
  timelineFinishedAtMs: number | null;
  timelineRunning: boolean;
  awaitingInput: boolean;
  runOutcome: RunActivityOutcome;
  keepLatestToolGroupOpen: boolean;
  userRequest: string;
  assistantResponse: string;
  model?: string;
  provider?: string;
  reasoningTokens?: number;
  openCalls: Set<string>;
  onToggleCall: (id: string) => void;
  onCopy: (execution: ToolExecution) => void;
  clarificationMode: ClarificationMode;
  inputBusy: boolean;
  onSubmitUserInput: (
    runId: string,
    inputRequestId: string,
    answers: UserInputAnswer[],
  ) => Promise<boolean>;
  onClarificationModeChange: (mode: ClarificationMode) => Promise<unknown>;
}) {
  const timelineClock = useSharedNow(timelineRunning);
  const [openSummaryIds, setOpenSummaryIds] = useState<Set<string>>(new Set());
  const [collapsingSummaryIds, setCollapsingSummaryIds] = useState<Set<string>>(new Set());
  const previousAutoOpenSummaryIds = useRef<Set<string>>(new Set());
  const manuallyOpenSummaryIds = useRef<Set<string>>(new Set());
  const manuallyClosedSummaryIds = useRef<Set<string>>(new Set());
  const summaryGroupElements = useRef<Map<string, HTMLDivElement>>(new Map());
  const autoOpenedAtMs = useRef<Map<string, number>>(new Map());
  const settleTimers = useRef<Map<string, number>>(new Map());
  const collapseTimers = useRef<Map<string, number>>(new Map());
  const visibleActivities = useStaggeredRunActivities(activities, timelineRunning);
  const effectiveTimelineFinishedAtMs = timelineFinishedAtMs ?? timelineClock;
  const activityGroups = visibleActivities.reduce<RunActivity[][]>((groups, activity) => {
    if (activity.type === "progress_summary" || activity.type === "skill" || activity.type === "input_request" || groups.length === 0) groups.push([]);
    groups.at(-1)?.push(activity);
    return groups;
  }, []);
  const progressStageTimings = progressStageTimingById(
    activityGroups.flatMap((group) => {
      const summary = group[0]?.type === "progress_summary" ? group[0] : null;
      return summary ? [{ id: summary.id, createdAt: summary.createdAt }] : [];
    }),
    timelineStartedAtMs,
    effectiveTimelineFinishedAtMs,
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

  const cancelScheduledCollapse = useCallback((id: string) => {
    const settleTimer = settleTimers.current.get(id);
    if (settleTimer !== undefined) window.clearTimeout(settleTimer);
    settleTimers.current.delete(id);
    const collapseTimer = collapseTimers.current.get(id);
    if (collapseTimer !== undefined) window.clearTimeout(collapseTimer);
    collapseTimers.current.delete(id);
    setCollapsingSummaryIds((current) => {
      if (!current.has(id)) return current;
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }, []);

  const finishAutoCollapse = useCallback((id: string) => {
    if (manuallyOpenSummaryIds.current.has(id)) return;
    const group = summaryGroupElements.current.get(id);
    const followingGroups = group
      ? Array.from(group.parentElement?.children ?? []).slice(Array.from(group.parentElement?.children ?? []).indexOf(group) + 1)
          .filter((element): element is HTMLElement => element instanceof HTMLElement)
      : [];
    const previousTops = new Map(followingGroups.map((element) => [element, element.getBoundingClientRect().top]));
    flushSync(() => {
      setOpenSummaryIds((current) => {
        if (!current.has(id)) return current;
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setCollapsingSummaryIds((current) => {
        if (!current.has(id)) return current;
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    });
    autoOpenedAtMs.current.delete(id);
    collapseTimers.current.delete(id);
    followingGroups.forEach((element) => {
      const previousTop = previousTops.get(element);
      if (previousTop === undefined) return;
      const offset = previousTop - element.getBoundingClientRect().top;
      if (Math.abs(offset) < 1 || typeof element.animate !== "function") return;
      element.animate(
        [
          { transform: `translateY(${offset}px)`, opacity: 0.86 },
          { transform: "translateY(0)", opacity: 1 },
        ],
        { duration: toolGroupReflowMs, easing: toolGroupReflowEasing },
      );
    });
  }, []);

  useEffect(() => {
    const previous = previousAutoOpenSummaryIds.current;
    autoOpenSummaryIds.forEach((id) => {
      cancelScheduledCollapse(id);
      if (manuallyClosedSummaryIds.current.has(id)) return;
      if (!previous.has(id)) autoOpenedAtMs.current.set(id, performance.now());
      setOpenSummaryIds((current) => current.has(id) ? current : new Set(current).add(id));
    });
    previous.forEach((id) => {
      if (autoOpenSummaryIds.has(id) || manuallyOpenSummaryIds.current.has(id) || manuallyClosedSummaryIds.current.has(id)) return;
      if (settleTimers.current.has(id) || collapseTimers.current.has(id)) return;
      const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
      if (reduceMotion) {
        finishAutoCollapse(id);
        return;
      }
      const openedAtMs = autoOpenedAtMs.current.get(id) ?? performance.now();
      const minimumVisibleRemainingMs = Math.max(0, toolGroupMinimumVisibleMs - (performance.now() - openedAtMs));
      const settleTimer = window.setTimeout(() => {
        settleTimers.current.delete(id);
        if (manuallyOpenSummaryIds.current.has(id)) return;
        setCollapsingSummaryIds((current) => new Set(current).add(id));
        const collapseTimer = window.setTimeout(() => finishAutoCollapse(id), toolGroupContentExitMs);
        collapseTimers.current.set(id, collapseTimer);
      }, Math.max(toolGroupCompletionSettleMs, minimumVisibleRemainingMs));
      settleTimers.current.set(id, settleTimer);
    });
    previousAutoOpenSummaryIds.current = autoOpenSummaryIds;
  }, [autoOpenSummaryKey, cancelScheduledCollapse, finishAutoCollapse]);

  useEffect(() => () => {
    settleTimers.current.forEach((timer) => window.clearTimeout(timer));
    collapseTimers.current.forEach((timer) => window.clearTimeout(timer));
  }, []);

  return (
    <section className="run-activity-timeline" aria-label="실행 과정">
      {activityGroups.map((group, groupIndex) => {
        const summary = group[0]?.type === "progress_summary" ? group[0] : null;
        const skill = group[0]?.type === "skill" ? group[0] : null;
        const toolActivities = group.filter((activity) => activity.type === "tool");
        const inputRequestActivity = group.find((activity) => activity.type === "input_request") ?? null;
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
        const showStageDuration = timedChildCount === 0;
        const modelProcessingRunning = timelineRunning && summary?.id === latestProgressSummaryId;
        const modelProcessingState: ModelProcessingState = awaitingInput && summary?.id === latestProgressSummaryId
          ? "awaiting_input"
          : modelProcessingRunning
          ? "running"
          : summary?.id === latestProgressSummaryId
            ? runOutcome
            : "completed";
        const toolGroupDurationMs = stageTiming && toolActivities.some((activity) => activity.execution.startedAt)
          ? toolActiveDurationMs
          : toolCallGroupDuration(toolActivities);
        const toolGroupId = summary ? `progress-tools-${summary.id}` : undefined;
        const toggleTools = (event: ReactMouseEvent<HTMLButtonElement>) => {
          preserveConversationScrollPosition(event.currentTarget, () => {
            if (!summary) return;
            cancelScheduledCollapse(summary.id);
            setOpenSummaryIds((current) => {
              const next = new Set(current);
              if (toolsOpen) {
                next.delete(summary.id);
                autoOpenedAtMs.current.delete(summary.id);
                manuallyOpenSummaryIds.current.delete(summary.id);
                manuallyClosedSummaryIds.current.add(summary.id);
              } else {
                next.add(summary.id);
                manuallyClosedSummaryIds.current.delete(summary.id);
                manuallyOpenSummaryIds.current.add(summary.id);
              }
              return next;
            });
          });
        };
        return (
          <div
            className="progress-group"
            key={summary?.id ?? group[0]?.id}
            ref={(element) => {
              if (!summary) return;
              if (element) summaryGroupElements.current.set(summary.id, element);
              else summaryGroupElements.current.delete(summary.id);
            }}
          >
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
                  <span className="tool-call-group-duration" data-tooltip="도구 실행 시간">{formatDuration(toolGroupDurationMs)}</span>
                  {toolsOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                </div>
              </button>
            ) : (
              <div className={`progress-summary phase-${summary.phase}`}><div className="progress-summary-text"><span>{summary.text}</span>{showStageDuration && <span className="progress-summary-duration" data-tooltip="단계 전체 소요 시간">{formatDuration(stageDurationMs)}</span>}</div></div>
            ))}
            {toolsOpen && summary && (
              <div className={`progress-tools ${summary && collapsingSummaryIds.has(summary.id) ? "is-collapsing" : ""}`} id={toolGroupId}>
                {toolActivities.map((activity) => (
                  <ToolCallRow
                    execution={activity.execution}
                    isOpen={openCalls.has(activity.execution.id)}
                    key={activity.id}
                    runOutcome={runOutcome}
                    terminalAtMs={effectiveTimelineFinishedAtMs}
                    onCopy={onCopy}
                    onToggle={() => onToggleCall(activity.execution.id)}
                  />
                ))}
                {hasModelProcessingRow && (
                  <ModelProcessingRow
                    durationMs={modelProcessingDurationMs}
                    state={modelProcessingState}
                    sent={sent}
                    received={received}
                    model={model}
                    provider={provider}
                    reasoningTokens={!timelineRunning && groupIndex === activityGroups.length - 1 ? reasoningTokens : undefined}
                  />
                )}
              </div>
            )}
            {inputRequestActivity && (
              <UserInputRequestCard
                request={inputRequestActivity.request}
                clarificationMode={clarificationMode}
                busy={inputBusy}
                onSubmit={(answers) => onSubmitUserInput(
                  inputRequestActivity.request.runId,
                  inputRequestActivity.request.id,
                  answers,
                )}
                onModeChange={onClarificationModeChange}
              />
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

function searchPurposeLabel(purpose?: string) {
  return ({
    broad_discovery: "폭넓게 탐색",
    official_facts: "공식 정보 확인",
    latest_update: "최신 정보 확인",
    independent_evaluation: "외부 평가 확인",
    contradiction_check: "상충 근거 확인",
  } as Record<string, string>)[purpose ?? ""] ?? null;
}

function citationTargets(text: string, sources: SourceEvidence[], citations: MessageCitation[]) {
  return sources.map((source, index) => {
    const citationOrder = citations.findIndex((item) => (item.sourceId ?? item.source_id) === source.sourceId);
    const citation = citationOrder >= 0 ? citations[citationOrder] : undefined;
    const explicitMarker = citation?.markerNumber ?? citation?.marker_number;
    const markerNumber = explicitMarker && explicitMarker > 0 ? explicitMarker : index + 1;
    const hasSourceToken = text.includes(`[source:${source.sourceId}]`) || text.includes(`[${source.sourceId}]`) || text.includes(`[[${source.sourceId}]]`);
    const hasMarkerToken = text.includes(citationMarkerLabel(markerNumber)) || text.includes(`[${markerNumber}]`);
    return {
      source,
      markerNumber,
      cited: citation ? citation.status === "cited" || citation.status === "resolved" : hasSourceToken || hasMarkerToken,
      reviewed: source.evidenceKind === "fetched_content" || source.evidenceKind === "knowledge_document",
      citationOrder: citationOrder >= 0 ? citationOrder : Number.MAX_SAFE_INTEGER,
      sourceOrder: index,
    };
  }).sort((left, right) => {
    const leftRank = left.cited ? 0 : left.reviewed ? 1 : 2;
    const rightRank = right.cited ? 0 : right.reviewed ? 1 : 2;
    if (leftRank !== rightRank) return leftRank - rightRank;
    if (left.cited && left.citationOrder !== right.citationOrder) {
      return left.citationOrder - right.citationOrder;
    }
    return left.sourceOrder - right.sourceOrder;
  }).map((target): CitationTarget => ({
    source: target.source,
    markerNumber: target.markerNumber,
    cited: target.cited,
    reviewed: target.reviewed,
  }));
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
    byToken.set(`source:${target.source.sourceId}`, target);
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

const streamingLeadingEdgeLength = 24;
const streamingLeadingEdgeRankSize = 4;
const streamingLeadingEdgeRanks = 6;
const streamingLeadingEdgeExcludedParents = new Set(["link", "linkReference"]);
const graphemeSegmenter = typeof Intl.Segmenter === "function"
  ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
  : null;

function streamingGraphemes(value: string) {
  return graphemeSegmenter
    ? Array.from(graphemeSegmenter.segment(value), ({ segment }) => segment)
    : Array.from(value);
}

function isVisibleStreamingGrapheme(value: string) {
  return !/^\s+$/u.test(value);
}

function rankedStreamingText(value: string, rank: number): Text {
  return {
    type: "text",
    value,
    data: {
      hName: "span",
      hProperties: {
        className: ["streaming-leading-edge"],
        dataStreamRank: String(rank),
      },
    },
  };
}

function remarkStreamingLeadingEdge() {
  return (tree: Root) => {
    let visibleCount = 0;
    visit(tree, "text", (node: Text, _index: number | undefined, parent: Parent | undefined) => {
      if (!parent || streamingLeadingEdgeExcludedParents.has(parent.type)) return;
      visibleCount += streamingGraphemes(node.value).filter(isVisibleStreamingGrapheme).length;
    });
    const leadingEdgeStart = Math.max(0, visibleCount - streamingLeadingEdgeLength);
    let visibleIndex = 0;

    visit(tree, "text", (node: Text, index: number | undefined, parent: Parent | undefined) => {
      if (index === undefined || !parent || streamingLeadingEdgeExcludedParents.has(parent.type)) return;
      const parts: Array<{ value: string; rank: number | null }> = [];
      for (const grapheme of streamingGraphemes(node.value)) {
        let rank: number | null = null;
        if (isVisibleStreamingGrapheme(grapheme)) {
          if (visibleIndex >= leadingEdgeStart) {
            rank = Math.min(
              streamingLeadingEdgeRanks,
              Math.floor((visibleCount - visibleIndex - 1) / streamingLeadingEdgeRankSize) + 1,
            );
          }
          visibleIndex += 1;
        }
        const previous = parts.at(-1);
        if (previous?.rank === rank) previous.value += grapheme;
        else parts.push({ value: grapheme, rank });
      }
      if (!parts.some(({ rank }) => rank !== null)) return;
      const replacement = parts.map(({ value, rank }) => rank === null
        ? ({ type: "text", value } satisfies Text)
        : rankedStreamingText(value, rank));
      parent.children.splice(index, 1, ...replacement);
      return index + replacement.length;
    });
  };
}

function StreamingBlockPending({ kind }: { kind: Exclude<StreamingPendingKind, null> }) {
  const label = kind === "mermaid" ? "다이어그램 작성 중" : kind === "chart" ? "인터랙티브 차트 작성 중" : "표 작성 중";
  return (
    <div className={`stream-block-pending is-${kind}`} role="status">
      {kind === "mermaid" ? <BranchFromHereIcon size={18} /> : <Table2 size={18} />}
      <span>{label}</span>
      <LoaderCircle className="is-running" size={15} />
    </div>
  );
}

export function pastedTextAttachmentLabel(attachment: AttachmentSummary, index: number) {
  const lineCount = Number(attachment.metadata?.lineCount ?? 0);
  return `[텍스트 첨부 #${index + 1}${lineCount > 0 ? ` +${lineCount}줄` : ""}]`;
}

const markdownCodeComponent: NonNullable<Components["code"]> = ({ className, children }) => {
  const language = /language-([\w-]+)/.exec(className || "")?.[1]?.toLowerCase();
  const source = String(children).replace(/\n$/, "");
  return language === "mermaid" || language === "mmd"
    ? <Suspense fallback={<StreamingBlockPending kind="mermaid" />}><MermaidDiagram source={source} /></Suspense>
    : language === "lumina-chart"
      ? <Suspense fallback={<StreamingBlockPending kind="chart" />}><InteractiveChart source={source} /></Suspense>
      : language
        ? <SyntaxCodeContent value={source} language={language} className={className} />
        : <code className={className}>{children}</code>;
};

function MarkdownCodeBlock({ children }: { children?: ReactNode }) {
  const preRef = useRef<HTMLPreElement>(null);
  const feedbackTimerRef = useRef<number | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const child = Children.toArray(children)[0];
  const childClassName = isValidElement<{ className?: string }>(child)
    ? String(child.props.className || "")
    : "";
  const language = /language-([\w-]+)/.exec(childClassName)?.[1]?.toLowerCase();
  const interactive = language === "mermaid" || language === "mmd" || language === "lumina-chart";

  useEffect(() => () => {
    if (feedbackTimerRef.current !== null) window.clearTimeout(feedbackTimerRef.current);
  }, []);

  if (interactive) return <pre>{children}</pre>;

  const handleCopy = async () => {
    try {
      const source = preRef.current?.querySelector("code")?.textContent?.replace(/\n$/, "") ?? "";
      await copyText(source);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
    if (feedbackTimerRef.current !== null) window.clearTimeout(feedbackTimerRef.current);
    feedbackTimerRef.current = window.setTimeout(() => {
      setCopyState("idle");
      feedbackTimerRef.current = null;
    }, 1600);
  };
  const feedback = copyState === "copied" ? "코드를 복사했습니다." : copyState === "error" ? "코드를 복사하지 못했습니다." : "";

  return (
    <div className="markdown-code-block">
      <pre ref={preRef}>{children}</pre>
      <button
        className={`markdown-code-copy${copyState === "copied" ? " is-copied" : copyState === "error" ? " is-error" : ""}`}
        type="button"
        aria-label={copyState === "copied" ? "코드 복사됨" : copyState === "error" ? "코드 복사 실패" : "코드 복사"}
        data-tooltip={copyState === "copied" ? "복사됨" : copyState === "error" ? "복사 실패" : "코드 복사"}
        onClick={() => void handleCopy()}
      >
        {copyState === "copied" ? <Check size={14} aria-hidden="true" /> : copyState === "error" ? <AlertCircle size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      </button>
      <span className="visually-hidden" role="status" aria-live="polite">{feedback}</span>
    </div>
  );
}

function UserMessageCopyButton({ text }: { text: string }) {
  const feedbackTimerRef = useRef<number | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");

  useEffect(() => () => {
    if (feedbackTimerRef.current !== null) window.clearTimeout(feedbackTimerRef.current);
  }, []);

  const handleCopy = async () => {
    try {
      await copyText(text);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
    if (feedbackTimerRef.current !== null) window.clearTimeout(feedbackTimerRef.current);
    feedbackTimerRef.current = window.setTimeout(() => {
      setCopyState("idle");
      feedbackTimerRef.current = null;
    }, 1600);
  };
  const feedback = copyState === "copied" ? "메시지를 복사했습니다." : copyState === "error" ? "메시지를 복사하지 못했습니다." : "";

  return (
    <>
      <button
        className={`user-message-copy${copyState === "copied" ? " is-copied" : copyState === "error" ? " is-error" : ""}`}
        type="button"
        aria-label={copyState === "copied" ? "메시지 복사됨" : copyState === "error" ? "메시지 복사 실패" : "메시지 복사"}
        data-tooltip={copyState === "copied" ? "복사됨" : copyState === "error" ? "복사 실패" : "메시지 복사"}
        onClick={() => void handleCopy()}
      >
        {copyState === "copied" ? <Check size={14} aria-hidden="true" /> : copyState === "error" ? <AlertCircle size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      </button>
      <span className="visually-hidden" role="status" aria-live="polite">{feedback}</span>
    </>
  );
}

const markdownPreComponent: NonNullable<Components["pre"]> = ({ children }) => <MarkdownCodeBlock>{children}</MarkdownCodeBlock>;

const MemoizedMarkdownChunk = memo(function MarkdownChunk({
  text,
  sources,
  citations,
  leadingEdge,
}: {
  text: string;
  sources: SourceEvidence[];
  citations: MessageCitation[];
  leadingEdge: boolean;
}) {
  const targets = useMemo(() => citationTargets(text, sources, citations), [citations, sources, text]);
  const targetById = useMemo(() => new Map(targets.map((target) => [target.source.sourceId, target])), [targets]);
  const remarkPlugins = useMemo<NonNullable<ReactMarkdownOptions["remarkPlugins"]>>(
    () => leadingEdge
      ? [remarkGfm, [remarkCitationLinks, { targets }], remarkStreamingLeadingEdge]
      : [remarkGfm, [remarkCitationLinks, { targets }]],
    [leadingEdge, targets],
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
        ? <Suspense fallback={<span>{alt || "이미지 불러오는 중"}</span>}><InlineMarkdownImage src={safeSrc} alt={alt || ""} /></Suspense>
        : <span>{alt || "이미지"}</span>;
    },
    table: ({ children }) => <div className="markdown-table-scroll"><table>{children}</table></div>,
    code: markdownCodeComponent,
    pre: markdownPreComponent,
  }), [targetById]);

  return (
    <ReactMarkdown skipHtml remarkPlugins={remarkPlugins} components={components} urlTransform={defaultUrlTransform}>
      {text}
    </ReactMarkdown>
  );
});

export function MarkdownResponse({
  text,
  sources = emptySources,
  citations = emptyCitations,
  streaming = false,
  settling = false,
  artifact = false,
}: {
  text: string;
  sources?: SourceEvidence[];
  citations?: MessageCitation[];
  streaming?: boolean;
  settling?: boolean;
  artifact?: boolean;
}) {
  const streamingParts = useStreamingMarkdownParts(text, streaming);
  const pendingKind = streamingParts.pendingKind;
  const stableBlocks = useMemo(
    () => streamingParts.stableBlocks.map(normalizeKoreanMarkdownEmphasis),
    [streamingParts.stableBlocks],
  );
  const tailText = useMemo(() => normalizeKoreanMarkdownEmphasis(streamingParts.liveTail), [streamingParts.liveTail]);

  return (
    <div className={`markdown-response ${streaming ? "streaming-text" : ""} ${settling ? "streaming-text-settling" : ""} ${artifact ? "artifact-markdown-content" : ""}`}>
      {stableBlocks.map((block, index) => (
        <MemoizedMarkdownChunk key={index} text={block} sources={sources} citations={citations} leadingEdge={false} />
      ))}
      {pendingKind
        ? <StreamingBlockPending kind={pendingKind} />
        : tailText && <MemoizedMarkdownChunk text={tailText} sources={sources} citations={citations} leadingEdge />}
    </div>
  );
}

export const AssistantTurn = memo(function AssistantTurn({
  turnSet,
  snapshot,
  sessionUsage,
  showSessionUsage,
  onCopyTool,
  onOpenArtifact,
  onBranch,
  onShare,
  onToast,
  clarificationMode,
  inputBusy,
  onSubmitUserInput,
  onClarificationModeChange,
}: {
  turnSet: TurnSet;
  snapshot: RunSnapshot | null;
  sessionUsage: Record<string, unknown> | undefined;
  showSessionUsage: boolean;
  onCopyTool: (execution: ToolExecution) => void;
  onOpenArtifact: (artifact: ArtifactSummary) => void;
  onBranch: (anchorMessageId: string) => Promise<void>;
  onShare: (anchorMessageId: string | null) => void;
  onToast: (message: string) => void;
  clarificationMode: ClarificationMode;
  inputBusy: boolean;
  onSubmitUserInput: (
    runId: string,
    inputRequestId: string,
    answers: UserInputAnswer[],
  ) => Promise<boolean>;
  onClarificationModeChange: (mode: ClarificationMode) => Promise<unknown>;
}) {
  const userMessages = turnSet.messages.filter((message) => message.role === "user");
  const assistantMessages = turnSet.messages.filter((message) => message.role === "assistant");
  const finalMessage = assistantMessages.at(-1) ?? null;
  const liveAssistantDraft = useRunAssistantDraft(turnSet.runId, snapshot?.assistantDraft ?? null);
  const sources = finalMessage?.metadata?.sources ?? emptySources;
  const citations = finalMessage?.metadata?.citations ?? emptyCitations;
  const searches = finalMessage?.metadata?.searchInvocations ?? [];
  const researchVerification = finalMessage?.metadata?.researchVerification;
  const artifacts = snapshot?.artifacts ?? turnSet.artifacts;
  const assistantText = finalMessage?.text || liveAssistantDraft?.text || "";
  const sanitizedAssistantText = sanitizeAssistantResponse(assistantText, artifacts.length > 0);
  const sourceTargets = citationTargets(sanitizedAssistantText, sources, citations);
  const citedSourceCount = sourceTargets.filter((target) => target.cited).length;
  const reviewedSourceCount = sourceTargets.filter((target) => !target.cited && target.source.evidenceKind === "fetched_content").length;
  const referenceSourceCount = sourceTargets.filter((target) => !target.cited && target.source.evidenceKind === "search_snippet").length;
  const knowledgeSourceCount = sources.filter((source) => source.evidenceKind === "knowledge_document").length;
  const sourceCountLabels = [
    citedSourceCount > 0 ? `인용 ${citedSourceCount}` : null,
    reviewedSourceCount > 0 ? `본문 확인 ${reviewedSourceCount}` : null,
    referenceSourceCount > 0 ? `검색 참고 ${referenceSourceCount}` : null,
    knowledgeSourceCount > 0 ? `지식 문서 ${knowledgeSourceCount}` : null,
  ].filter((label): label is string => label !== null);
  const tools = snapshot?.toolExecutions ?? turnSet.toolExecutions;
  const hasArtifactWritingExecution = tools.some((execution) => (
    ["create_report", "write_file"].some((toolName) => (
      execution.toolName.toLocaleLowerCase().includes(toolName)
    ))
  ));
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
  const pendingInputRequest = (snapshot?.inputRequests ?? []).find((request) => request.status === "pending") ?? null;
  const awaitingInput = status === "awaiting_input" && pendingInputRequest !== null;
  const activityOutcome = runActivityOutcome(status);
  const collapseWorkDetails = shouldCollapseRunWorkDetails(status);
  const terminalReason = status && status !== "completed"
    ? snapshot?.errorMessage?.trim() || (status === "cancelled" ? "요청에 따라 작업을 중지했습니다." : "작업을 완료하지 못했습니다. 다시 실행해 주세요.")
    : "";
  const copyableAnswerText = sanitizedAssistantText || terminalReason;
  const streaming = !finalMessage && Boolean(liveAssistantDraft);
  const { visibleText: displayedText, revealing, settling } = useStreamingText(sanitizedAssistantText, streaming);
  const terminalPresentationReady = terminal && displayedText === sanitizedAssistantText;
  const [reportOpen, setReportOpen] = useState(false);
  const [markdownSaving, setMarkdownSaving] = useState(false);
  const [knowledgeSaving, setKnowledgeSaving] = useState(false);
  const [knowledgeSaved, setKnowledgeSaved] = useState(false);
  const [branching, setBranching] = useState(false);
  const [openCalls, setOpenCalls] = useState<Set<string>>(new Set());
  const toggleOpenCall = useCallback((id: string) => {
    setOpenCalls((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const [reportText, setReportText] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [answerRating, setAnswerRating] = useState<"like" | "dislike" | null>(null);
  const [ratingSubmitting, setRatingSubmitting] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [expandedSourceId, setExpandedSourceId] = useState<string | null>(null);
  const [sourceContent, setSourceContent] = useState<{
    sourceId: string;
    content: string;
    nextOffset: number;
    totalChars: number;
    llmTextChars: number;
    llmTextCharsEstimated: boolean;
    hasMore: boolean;
    loading: boolean;
    error: string | null;
  } | null>(null);
  const sourceContentLoadingRef = useRef(false);
  const [previewAttachment, setPreviewAttachment] = useState<AttachmentSummary | null>(null);
  const [textPreviewAttachment, setTextPreviewAttachment] = useState<AttachmentSummary | null>(null);
  const [workDetailsOpen, setWorkDetailsOpen] = useState(!collapseWorkDetails);
  const expandedSourceTarget = sourceTargets.find(({ source }) => source.sourceId === expandedSourceId) ?? null;
  const workStartedAt = snapshot?.startedAt ?? turnSet.createdAt;
  const workFinishedAt = snapshot?.finishedAt ?? turnSet.completedAt;
  const workStartedAtMs = new Date(workStartedAt).getTime();
  const inputWaitStartedAtMs = pendingInputRequest ? new Date(pendingInputRequest.createdAt).getTime() : Number.NaN;
  const workFinishedAtMs = workFinishedAt
    ? new Date(workFinishedAt).getTime()
    : awaitingInput && Number.isFinite(inputWaitStartedAtMs)
      ? inputWaitStartedAtMs
      : null;
  const hasWorkDetails = activities.length > 0;

  useEffect(() => {
    setWorkDetailsOpen(!collapseWorkDetails);
  }, [snapshot?.runId, collapseWorkDetails]);

  useEffect(() => {
    setAnswerRating(null);
    setKnowledgeSaved(false);
  }, [finalMessage?.id]);

  const openSourceDetail = useCallback((sourceId: string) => {
    const currentDetail = window.history.state?.luminaSourceDetail;
    const nextState = { ...window.history.state, luminaSourceDetail: { turnSetId: turnSet.id, sourceId } };
    if (currentDetail?.turnSetId === turnSet.id) window.history.replaceState(nextState, "");
    else window.history.pushState(nextState, "");
    setExpandedSourceId(sourceId);
  }, [turnSet.id]);

  useEffect(() => {
    const source = sources.find((item) => item.sourceId === expandedSourceId);
    const conversationId = finalMessage?.conversationId;
    const runId = finalMessage?.runId ?? turnSet.runId;
    if (!source || source.evidenceKind !== "fetched_content" || !conversationId || !runId) {
      setSourceContent(null);
      return;
    }
    const controller = new AbortController();
    sourceContentLoadingRef.current = true;
    setSourceContent({
      sourceId: source.sourceId,
      content: "",
      nextOffset: 0,
      totalChars: source.textChars ?? 0,
      llmTextChars: source.llmTextChars ?? 0,
      llmTextCharsEstimated: false,
      hasMore: true,
      loading: true,
      error: null,
    });
    void api.conversations.getSourceContent(conversationId, runId, source.sourceId, 0, 4_000, controller.signal)
      .then((page) => {
        setSourceContent({ ...page, sourceId: source.sourceId, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSourceContent((current) => current?.sourceId === source.sourceId
          ? { ...current, loading: false, error: "본문을 불러오지 못했습니다." }
          : current);
      })
      .finally(() => { sourceContentLoadingRef.current = false; });
    return () => controller.abort();
  }, [expandedSourceId, finalMessage?.conversationId, finalMessage?.runId, sources, turnSet.runId]);

  const loadMoreSourceContent = useCallback(() => {
    const conversationId = finalMessage?.conversationId;
    const runId = finalMessage?.runId ?? turnSet.runId;
    if (!sourceContent || !conversationId || !runId || !sourceContent.hasMore || sourceContentLoadingRef.current) return;
    sourceContentLoadingRef.current = true;
    setSourceContent((current) => current ? { ...current, loading: true, error: null } : current);
    void api.conversations.getSourceContent(conversationId, runId, sourceContent.sourceId, sourceContent.nextOffset)
      .then((page) => {
        setSourceContent((current) => current?.sourceId === page.sourceId
          ? {
              ...current,
              content: current.content + page.content,
              nextOffset: page.nextOffset,
              totalChars: page.totalChars,
              llmTextChars: page.llmTextChars,
              llmTextCharsEstimated: page.llmTextCharsEstimated,
              hasMore: page.hasMore,
              loading: false,
              error: null,
            }
          : current);
      })
      .catch(() => {
        setSourceContent((current) => current ? { ...current, loading: false, error: "다음 본문을 불러오지 못했습니다." } : current);
      })
      .finally(() => { sourceContentLoadingRef.current = false; });
  }, [finalMessage?.conversationId, finalMessage?.runId, sourceContent, turnSet.runId]);

  const handleSourcesScroll = useCallback((event: ReactUIEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    if (element.scrollHeight - element.scrollTop - element.clientHeight < 240) loadMoreSourceContent();
  }, [loadMoreSourceContent]);

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

  const copyAnswer = async () => {
    if (!copyableAnswerText) {
      onToast("복사할 내용이 없습니다.");
      return;
    }
    try {
      if (sanitizedAssistantText) await copyText(sanitizedAssistantText);
      else await copyText(terminalReason);
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
      onOpenArtifact(artifact);
    } catch {
      onToast("답변을 Markdown Artifact로 저장하지 못했습니다.");
    } finally {
      setMarkdownSaving(false);
    }
  };
  const saveAnswerToKnowledge = async () => {
    if (!finalMessage || knowledgeSaving || knowledgeSaved) return;
    setKnowledgeSaving(true);
    try {
      await saveKnowledgeDocumentFromMessage(finalMessage.id);
      setKnowledgeSaved(true);
    } catch {
      onToast("지식 그래프에 답변을 저장하지 못했습니다.");
    } finally {
      setKnowledgeSaving(false);
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
    } catch {
      setReportError("의견을 게시하지 못했습니다. 다시 시도해 주세요.");
    } finally {
      setReportSubmitting(false);
    }
  };
  const liveArtifactProgress = useRunArtifactProgress(
    turnSet.runId,
    snapshot?.artifactProgress ?? null,
  );
  const artifactUsage = liveArtifactProgress
    ?? snapshot?.artifactUsage
    ?? finalMessage?.metadata?.artifactUsage
    ?? null;
  const artifactProgress = artifactUsage
    ? tokenBucketProgress(artifactUsage.tokens, artifactUsage.targetTokens)
    : null;
  const runUsage = finalMessage?.metadata?.usage ?? snapshot?.usage;
  const reasoningTokens = optionalUsageNumber(runUsage, "reasoning_tokens");
  const modelOutputTokens = usageNumber(runUsage, "output_tokens");
  const liveModelOutputTokens = Math.max(
    modelOutputTokens,
    artifactUsage?.modelOutputTokens ?? 0,
  );
  return (
    <div className={`turn-set ${terminalPresentationReady ? "is-terminal" : "is-active"}`} data-run-id={turnSet.runId ?? undefined}>
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
                  <img src={attachmentContentUrl(attachment.id)} alt={attachment.fileName} loading="lazy" decoding="async" />
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
                    <TextAttachmentViewer attachment={attachment} onClose={() => setTextPreviewAttachment(null)} />
                  )}
                </div>
              ) : (
                <a className="user-file-attachment" href={attachmentContentUrl(attachment.id)} target="_blank" rel="noreferrer noopener" key={attachment.id}>
                  <FileText size={15} /> {attachment.fileName}
                </a>
              ))}
            </div>
          )}
          <div className="user-message-row">
            {message.text && <UserMessageCopyButton text={message.text} />}
            <div className="user-message">
              {message.text && <div className="user-message-text">{message.text}</div>}
            </div>
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
            <WorkDurationLabel
              startedAtMs={workStartedAtMs}
              finishedAtMs={workFinishedAtMs}
              running={!terminal && !awaitingInput}
              statusSuffix={awaitingInput ? " · 답변 대기" : terminal && status !== "completed" ? ` · ${runStatusLabel(status)}` : ""}
            />
            <ChevronRight size={15} aria-hidden="true" />
          </button>
          {workDetailsOpen && (
            <div className="turn-tool-activity" id={`turn-work-details-${turnSet.id}`}>
              <RunActivityTimeline
                activities={activities}
                timelineStartedAtMs={workStartedAtMs}
                timelineFinishedAtMs={workFinishedAtMs}
                timelineRunning={!terminal && !awaitingInput}
                awaitingInput={awaitingInput}
                runOutcome={activityOutcome}
                keepLatestToolGroupOpen={status === "model_streaming"}
                userRequest={userMessages.at(-1)?.text ?? ""}
                assistantResponse={sanitizedAssistantText}
                model={snapshot?.execution.runtimeModelId}
                provider={snapshot?.execution.providerId}
                reasoningTokens={reasoningTokens}
                openCalls={openCalls}
                onCopy={onCopyTool}
                onToggleCall={toggleOpenCall}
                clarificationMode={clarificationMode}
                inputBusy={inputBusy}
                onSubmitUserInput={onSubmitUserInput}
                onClarificationModeChange={onClarificationModeChange}
              />
            </div>
          )}
        </section>
      )}
      {previewAttachment && <ImageAttachmentViewer attachment={previewAttachment} onClose={() => setPreviewAttachment(null)} />}
      {(assistantText || tools.length > 0 || artifacts.length > 0 || snapshot) && (
        <section className="assistant-turn">
          <div className="assistant-content conversation-response-typography">
            {assistantText && <MarkdownResponse text={displayedText} sources={sources} citations={citations} streaming={revealing} settling={settling} />}
            {terminalPresentationReady && researchVerification === "unverified" && (
              <div className="research-verification-warning" role="status">
                최신성 또는 중요도가 높은 정보에 필요한 웹 본문을 확인하지 못했습니다. 답변의 관련 내용을 미검증 정보로 봐 주세요.
              </div>
            )}
            {hasArtifactWritingExecution && artifactUsage && artifactProgress && (
              <div className={`artifact-progress-count is-${artifactProgress.stage}`} role="status" aria-live={terminal ? undefined : "polite"} aria-label={`문서 ${artifactUsage.estimated === false ? "완성 분량" : "작성 중 추정 분량"} ${artifactUsage.tokens.toLocaleString()} 토큰 ${artifactUsage.lines.toLocaleString()}줄${liveModelOutputTokens > 0 ? `, 모델 출력 누계 ${liveModelOutputTokens.toLocaleString()} 토큰` : ""}`}>
                <div className="artifact-progress-heading">
                  <span>{artifactUsage.tokens === 0 && !terminal ? "문서 작성을 준비하고 있습니다." : <>{artifactUsage.estimated === false ? "문서 약" : "작성 중 약"} {artifactUsage.tokens.toLocaleString()}토큰 · {artifactUsage.lines.toLocaleString()}줄{artifactUsage.targetTokens ? <span className="artifact-progress-target"> · 목표 {artifactUsage.targetTokens.toLocaleString()}토큰</span> : null}</>}</span>
                  {liveModelOutputTokens > 0 && (
                    <span className="artifact-model-output">
                      모델 출력 누계 {liveModelOutputTokens.toLocaleString()}토큰
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
                <div className={`artifact-progress-meter ${artifactUsage.tokens === 0 && !terminal ? "is-indeterminate" : ""}`} role="progressbar" aria-label={artifactUsage.tokens === 0 && !terminal ? "문서 작성 준비 중" : artifactUsage.targetTokens ? "선택한 문서 목표 분량 대비 작성량" : "현재 5,000 토큰 구간의 생성량"} aria-valuemin={0} aria-valuemax={artifactProgress.maxTokens} aria-valuenow={artifactUsage.tokens === 0 && !terminal ? undefined : artifactProgress.bucketTokens}>
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
            {terminalPresentationReady && (
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
                      showSessionUsage={showSessionUsage}
                      model={snapshot?.execution.runtimeModelId}
                      provider={snapshot?.execution.providerId}
                    />
                    <button className="tooltip-control" type="button" aria-label="원문 복사" data-tooltip="원문 복사" disabled={!copyableAnswerText} onClick={() => void copyAnswer()}><Copy size={16} /></button>
                    <button className="tooltip-control" type="button" aria-label="라이브러리 저장" data-tooltip="라이브러리 저장" disabled={!finalMessage || !sanitizedAssistantText || markdownSaving} onClick={() => void saveAnswerAsMarkdown()}>{markdownSaving ? <LoaderCircle className="is-running" size={16} /> : <Download size={16} />}</button>
                    <button className={`tooltip-control knowledge-save-control ${knowledgeSaving ? "is-saving" : knowledgeSaved ? "is-saved" : ""}`} type="button" aria-label="지식 그래프 등록" data-tooltip="지식 그래프 등록" aria-pressed={knowledgeSaved} disabled={!finalMessage || !sanitizedAssistantText || knowledgeSaving || knowledgeSaved} onClick={() => void saveAnswerToKnowledge()}>{knowledgeSaving ? <LoaderCircle className="is-running" size={16} /> : <BookPlus size={16} />}</button>
                    <button className="tooltip-control" type="button" aria-label="이 답변까지 새 채팅으로 분기" data-tooltip="여기서 분기" disabled={!finalMessage || branching} onClick={() => void branchAnswer()}>{branching ? <LoaderCircle className="is-running" size={16} /> : <BranchFromHereIcon size={16} />}</button>
                    <button className="tooltip-control" type="button" aria-label="링크 공유" data-tooltip="링크 공유" disabled={!assistantText} onClick={() => onShare(finalMessage?.id ?? null)}><ShareActionIcon size={16} /></button>
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
                        {knowledgeSourceCount > 0 && <span className="answer-source-count is-knowledge"> · 지식 문서 {knowledgeSourceCount}</span>}
                        {reviewedSourceCount > 0 && <span className="answer-source-count is-reviewed"> · 본문 확인 {reviewedSourceCount}</span>}
                        {referenceSourceCount > 0 && <span className="answer-source-count is-reference-only"> · 검색 참고 {referenceSourceCount}</span>}
                      </button>
                      {sourcesOpen && createPortal((
                        <div className="answer-sources answer-sources-layer">
                          <button className="answer-sources-backdrop" type="button" aria-label="검색 및 참고 출처 닫기" onClick={closeSources} />
                          <div className="answer-sources-popover" onScroll={handleSourcesScroll}>
                            {expandedSourceTarget ? (
                              <div className="source-detail">
                                <div className="source-detail-navigation">
                                  <button className="source-detail-back" type="button" onClick={returnToSourceList}><ArrowLeft size={14} /> 출처 목록으로</button>
                                  <button className="source-detail-back is-icon" type="button" aria-label="출처 목록으로 돌아가기" onClick={returnToSourceList}><ArrowLeft size={15} /></button>
                                </div>
                                <div className="source-header">
                                  <span className={`source-kind${expandedSourceTarget.cited ? "" : expandedSourceTarget.reviewed ? " is-reviewed" : " is-reference-only"}`}>{expandedSourceTarget.source.evidenceKind === "knowledge_document" ? `${expandedSourceTarget.cited ? `${citationMarkerLabel(expandedSourceTarget.markerNumber)} ` : ""}지식 문서` : expandedSourceTarget.cited ? `${citationMarkerLabel(expandedSourceTarget.markerNumber)} 본문 인용` : expandedSourceTarget.reviewed ? "본문 확인" : "검색 참고"}</span>
                                  {defaultUrlTransform(expandedSourceTarget.source.normalizedUrl || expandedSourceTarget.source.originalUrl)
                                    ? <a href={defaultUrlTransform(expandedSourceTarget.source.normalizedUrl || expandedSourceTarget.source.originalUrl)} target="_blank" rel="noreferrer noopener">{expandedSourceTarget.source.title || expandedSourceTarget.source.domain}</a>
                                    : <strong>{expandedSourceTarget.source.title || expandedSourceTarget.source.domain}</strong>}
                                  <small>{expandedSourceTarget.source.domain}{expandedSourceTarget.source.selectionScore !== undefined ? ` · 선택 점수 ${expandedSourceTarget.source.selectionScore.toFixed(2)}` : ""}</small>
                                </div>
                                {sourceContent?.sourceId === expandedSourceTarget.source.sourceId ? (
                                  <>
                                    <div className="source-detail-stats" aria-label="출처 본문 글자 수">
                                      <span>LLM 전달 {sourceContent.llmTextChars.toLocaleString()}자{sourceContent.llmTextCharsEstimated ? " (기존 기록 기준 추정)" : ""}</span>
                                      <span>추출 본문 {sourceContent.totalChars.toLocaleString()}자</span>
                                      <span>현재 표시 {sourceContent.content.length.toLocaleString()}자</span>
                                    </div>
                                    <p className="source-detail-excerpt">{sourceContent.content || expandedSourceTarget.source.verbatimExcerpt}</p>
                                    {sourceContent.loading && <p className="source-detail-loading" role="status">본문을 이어서 불러오는 중…</p>}
                                    {sourceContent.error && <p className="source-detail-error" role="alert">{sourceContent.error}</p>}
                                    {!sourceContent.hasMore && sourceContent.content && <p className="source-detail-end">본문 끝 · {sourceContent.totalChars.toLocaleString()}자</p>}
                                  </>
                                ) : (
                                  <p className="source-detail-excerpt">{expandedSourceTarget.source.verbatimExcerpt}</p>
                                )}
                              </div>
                            ) : (
                              <>
                                {searches.length > 0 && (
                                  <div className="source-queries">{searches.map((search) => {
                                    const purposeLabel = searchPurposeLabel(search.purpose);
                                    return <span key={search.invocationId}>{purposeLabel && <small>{purposeLabel}</small>}{search.query}</span>;
                                  })}</div>
                                )}
                                <ol>
                                  {sourceTargets.map(({ source, markerNumber, cited, reviewed }) => (
                                    <li className={cited ? "is-cited" : reviewed ? "is-reviewed" : "is-reference-only"} key={source.sourceId}>
                                      <div className="source-header">
                                        <span className="source-kind">{source.evidenceKind === "knowledge_document" ? `${cited ? `${citationMarkerLabel(markerNumber)} ` : ""}지식 문서` : cited ? `${citationMarkerLabel(markerNumber)} 본문 인용` : reviewed ? "본문 확인" : "검색 참고"}</span>
                                        {defaultUrlTransform(source.normalizedUrl || source.originalUrl)
                                          ? <a href={defaultUrlTransform(source.normalizedUrl || source.originalUrl)} target="_blank" rel="noreferrer noopener">{source.title || source.domain}</a>
                                          : <strong>{source.title || source.domain}</strong>}
                                        <small>{source.domain}{source.selectionScore !== undefined ? ` · 선택 점수 ${source.selectionScore.toFixed(2)}` : ""}</small>
                                        </div>
                                      {source.verbatimExcerpt && (
                                        <div className="source-excerpt-row">
                                          <button className="source-excerpt" type="button" aria-label={`${source.title || source.domain} 확대해서 보기`} onClick={() => openSourceDetail(source.sourceId)}>{source.verbatimExcerpt}</button>
                                          <button type="button" aria-label={`${source.title || source.domain} 본문 복사`} onClick={() => {
                                            void copyText(source.verbatimExcerpt ?? "")
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
                        </div>
                      ), document.querySelector(".app-shell") ?? document.body)}
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
});

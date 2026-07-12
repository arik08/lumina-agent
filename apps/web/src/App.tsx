import {
  AlertCircle,
  ArrowLeft,
  AtSign,
  Bell,
  Bot,
  Brain,
  Check,
  CheckCircle2,
  CheckCheck,
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
  Folder,
  FolderOpen,
  FolderInput,
  FolderSearch,
  Globe2,
  Library,
  LoaderCircle,
  LogOut,
  Maximize2,
  Menu,
  MessageCircle,
  MessageSquarePlus,
  Minimize2,
  Moon,
  MoreVertical,
  Paperclip,
  PanelLeftClose,
  PanelLeftOpen,
  Pause,
  Pencil,
  Pin,
  PinOff,
  Play,
  RotateCcw,
  Save,
  Search,
  Send,
  Settings,
  Share2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  SquarePen,
  Store,
  Sun,
  Table2,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Undo2,
  GitBranch,
  Image as ImageIcon,
  Wrench,
  X,
} from "lucide-react";
import type { Link, Parent, PhrasingContent, Root, Text } from "mdast";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type CSSProperties, type FormEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import ReactMarkdown, { defaultUrlTransform, type Components, type Options as ReactMarkdownOptions } from "react-markdown";
import { createPortal } from "react-dom";
import remarkGfm from "remark-gfm";
import { visit } from "unist-util-visit";
import { api, ApiError, attachmentContentUrl } from "./api";
import { SyntaxCode, SyntaxCodeContent, SyntaxTextarea } from "./components/SyntaxCode";
import type {
  AdminProviderModel,
  ArtifactSummary,
  AttachmentSummary,
  ArtifactVersion,
  ChatMessage,
  ComposerSuggestion,
  MessageCitation,
  NotificationItem,
  PromptReference,
  ReferenceKind,
  RunCommand,
  RunActivity,
  RunSnapshot,
  RunStatus,
  SourceEvidence,
  ToolExecution,
  TurnSet,
} from "./api-types";
import LoginScreen from "./components/LoginScreen";
import { AdminView } from "./components/AdminView";
import { ArtifactLibraryView } from "./components/ArtifactLibraryView";
import { MarketplaceView } from "./components/MarketplaceView";
import { MemoryView } from "./components/MemoryView";
import { ProjectSettings } from "./components/ProjectSettings";
import { ProjectFilesView } from "./components/ProjectFilesView";
import { SchedulesView } from "./components/SchedulesView";
import { SharedSnapshotViewer } from "./components/SharedSnapshotViewer";
import { ConversationSearchDialog } from "./components/ConversationSearchDialog";
import { type RunControlAction, useLuminaWorkspace } from "./use-lumina-workspace";
import { useConversationAutoFollow, useStreamingText } from "./streaming-ui";

type ArtifactTab = "preview" | "source";

const artifactPreviewEditMessage = "lumina:artifact-preview-edit";
const artifactAiCommentMessage = "lumina:artifact-ai-comment";
const artifactAiCommentsMessage = "lumina:artifact-ai-comments";

type ArtifactAiComment = {
  id: string;
  text: string;
  before: string;
  after: string;
  instruction: string;
  scope: "selection" | "document";
};

function editableArtifactHtml(source: string) {
  const document = new DOMParser().parseFromString(source, "text/html");
  document.querySelectorAll("script, meta[http-equiv='Content-Security-Policy' i]").forEach((element) => element.remove());
  document.querySelectorAll<HTMLElement>("*").forEach((element) => {
    for (const attribute of [...element.attributes]) {
      if (attribute.name.toLowerCase().startsWith("on")) element.removeAttribute(attribute.name);
      if (["href", "src", "action", "formaction"].includes(attribute.name.toLowerCase()) && /^\s*javascript:/i.test(attribute.value)) {
        element.removeAttribute(attribute.name);
      }
    }
  });
  document.body.contentEditable = "true";
  document.body.dataset.luminaEditable = "true";
  const editStyle = document.createElement("style");
  editStyle.id = "lumina-artifact-edit-style";
  editStyle.textContent = `
    body[data-lumina-editable] { outline: none; }
    body[data-lumina-editable] ::selection { background: #ffe36a; color: #1f2328; }
    ::highlight(lumina-comment-pending) { background: #ffe36a; color: #1f2328; }
    .lumina-ai-comment-highlight { border-radius: 2px; background: #fff0a8; box-shadow: 0 0 0 1px #d6a91f; }
    .lumina-ai-comment-highlight::after { content: attr(data-index); display: inline-grid; width: 17px; height: 17px; margin-left: 3px; place-items: center; border-radius: 50%; background: #315fbd; color: white; font: 700 10px/1 Arial,sans-serif; vertical-align: super; }
    .lumina-ai-comment-popover { position: fixed; z-index: 2147483647; display: grid; width: min(286px, calc(100vw - 18px)); min-height: 36px; grid-template-columns: minmax(0,1fr) 27px; align-items: center; gap: 6px; padding: 4px 6px 4px 12px; border: 1px solid rgba(255,255,255,.1); border-radius: 16px; background: rgba(38,38,38,.98); color: white; box-shadow: 0 18px 46px rgba(0,0,0,.34), 0 2px 7px rgba(0,0,0,.2); }
    .lumina-ai-comment-popover.is-multiline { grid-template-rows: auto 30px; align-items: end; padding: 10px; }
    .lumina-ai-comment-popover textarea { width: 100%; min-width: 0; height: 22px; min-height: 22px; max-height: 118px; resize: none; overflow: hidden; border: 0; outline: 0; padding: 2px 0 0; background: transparent; color: white; font: 13px/1.3 system-ui,-apple-system,"Segoe UI",sans-serif; }
    .lumina-ai-comment-popover textarea::placeholder { color: rgba(255,255,255,.5); }
    .lumina-ai-comment-popover.is-multiline textarea { grid-column: 1/-1; height: auto; min-height: 58px; overflow-y: auto; padding: 0 2px; font-size: 13px; line-height: 1.4; }
    .lumina-ai-comment-popover button { display: inline-grid; min-width: 26px; height: 26px; place-items: center; border: 0; border-radius: 999px; background: rgba(255,255,255,.92); color: #1f1f1f; cursor: pointer; font: 800 13px/1 system-ui,sans-serif; }
    .lumina-ai-comment-popover .lumina-ai-comment-cancel { display: none; justify-self: start; min-width: 45px; padding: 0 10px; background: rgba(255,255,255,.12); color: rgba(255,255,255,.86); font-size: 12px; }
    .lumina-ai-comment-popover.is-multiline .lumina-ai-comment-cancel { display: inline-grid; }
    .lumina-ai-comment-popover button:disabled { cursor: not-allowed; opacity: .52; }
  `;
  document.head.appendChild(editStyle);
  const bridge = document.createElement("script");
  bridge.id = "lumina-artifact-edit-bridge";
  bridge.textContent = `
    window.__luminaArtifactEditBridgeReady = true;
    const publishArtifactEdit = () => {
      const clone = document.documentElement.cloneNode(true);
      clone.querySelector('#lumina-artifact-edit-bridge')?.remove();
      clone.querySelector('#lumina-artifact-edit-style')?.remove();
      clone.querySelectorAll('.lumina-ai-comment-highlight').forEach((mark) => mark.replaceWith(...mark.childNodes));
      clone.querySelectorAll('.lumina-ai-comment-popover').forEach((item) => item.remove());
      const body = clone.querySelector('body');
      body?.removeAttribute('contenteditable');
      body?.removeAttribute('data-lumina-editable');
      parent.postMessage({ type: '${artifactPreviewEditMessage}', html: '<!doctype html>\\n' + clone.outerHTML }, '*');
    };
    document.addEventListener('input', publishArtifactEdit);
    let pendingRange = null;
    let savedRange = null;
    const pendingHighlightName = 'lumina-comment-pending';
    const clearPendingHighlight = () => CSS.highlights?.delete(pendingHighlightName);
    const closePopover = () => {
      document.querySelector('.lumina-ai-comment-popover')?.remove();
      clearPendingHighlight();
      pendingRange = null;
    };
    const unwrapComment = (id) => {
      document.querySelectorAll('[data-lumina-comment-id="' + CSS.escape(id) + '"]').forEach((mark) => mark.replaceWith(...mark.childNodes));
    };
    window.addEventListener('message', (event) => {
      if (event.data?.type !== '${artifactAiCommentsMessage}') return;
      const comments = Array.isArray(event.data.comments) ? event.data.comments : [];
      document.querySelectorAll('.lumina-ai-comment-highlight').forEach((mark) => {
        if (!comments.some((comment) => comment.id === mark.dataset.luminaCommentId)) mark.replaceWith(...mark.childNodes);
      });
      comments.forEach((comment, index) => {
        const mark = document.querySelector('[data-lumina-comment-id="' + CSS.escape(comment.id) + '"]');
        if (mark) { mark.dataset.index = String(index + 1); mark.title = comment.instruction; }
      });
    });
    document.addEventListener('selectionchange', () => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed || selection.rangeCount === 0 || !selection.toString().trim()) return;
      const range = selection.getRangeAt(0);
      if (document.body.contains(range.commonAncestorContainer)) savedRange = range.cloneRange();
    });
    const openCommentPopover = (event) => {
      if (event.button !== 2) return;
      if (event.target?.closest?.('.lumina-ai-comment-popover')) return;
      const selection = window.getSelection();
      const liveRange = selection && !selection.isCollapsed && selection.rangeCount > 0 && selection.toString().trim()
        ? selection.getRangeAt(0).cloneRange()
        : null;
      const range = liveRange ?? savedRange?.cloneRange();
      event.preventDefault();
      event.stopPropagation();
      if (range && !document.body.contains(range.commonAncestorContainer)) return;
      const scope = range && range.toString().trim() ? 'selection' : 'document';
      const selectedText = scope === 'selection' ? range.toString().trim() : '전체 문서';
      const bodyText = document.body.innerText;
      const selectedOffset = scope === 'selection' ? Math.max(0, bodyText.indexOf(selectedText)) : 0;
      closePopover();
      pendingRange = scope === 'selection' ? range.cloneRange() : null;
      if (pendingRange && CSS.highlights && typeof Highlight === 'function') {
        CSS.highlights.set(pendingHighlightName, new Highlight(pendingRange));
      } else if (pendingRange) {
        selection?.removeAllRanges();
        selection?.addRange(pendingRange.cloneRange());
      }
      const popover = document.createElement('div');
      popover.className = 'lumina-ai-comment-popover';
      popover.setAttribute('role', 'dialog');
      popover.setAttribute('aria-label', 'AI 수정 의견 작성');
      popover.style.left = Math.min(event.clientX + 8, window.innerWidth - 318) + 'px';
      popover.style.top = Math.min(event.clientY + 8, window.innerHeight - 62) + 'px';
      const input = document.createElement('textarea');
      input.rows = 1;
      input.placeholder = scope === 'document' ? '전체 수정 요청...' : '댓글 추가...';
      input.setAttribute('aria-label', '수정 의견');
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'lumina-ai-comment-cancel';
      cancel.textContent = '취소';
      cancel.setAttribute('aria-label', '수정 의견 취소');
      cancel.addEventListener('click', closePopover);
      const submit = document.createElement('button');
      submit.type = 'button';
      submit.textContent = '✓';
      submit.setAttribute('aria-label', '수정 의견 추가');
      submit.disabled = true;
      const addComment = () => {
        const instruction = input.value.trim();
        if (!instruction) return;
        const id = crypto.randomUUID();
        if (pendingRange) {
          const mark = document.createElement('mark');
          mark.className = 'lumina-ai-comment-highlight';
          mark.dataset.luminaCommentId = id;
          mark.dataset.index = '?';
          mark.title = instruction;
          clearPendingHighlight();
          try {
            pendingRange.surroundContents(mark);
          } catch {
            const contents = pendingRange.extractContents();
            mark.append(contents);
            pendingRange.insertNode(mark);
          }
        }
        parent.postMessage({ type: '${artifactAiCommentMessage}', comment: { id, text: selectedText, before: scope === 'selection' ? bodyText.slice(Math.max(0, selectedOffset - 180), selectedOffset) : '', after: scope === 'selection' ? bodyText.slice(selectedOffset + selectedText.length, selectedOffset + selectedText.length + 180) : '', instruction, scope } }, '*');
        selection?.removeAllRanges();
        savedRange = null;
        pendingRange = null;
        closePopover();
      };
      submit.addEventListener('click', addComment);
      input.addEventListener('input', () => {
        submit.disabled = !input.value.trim();
        input.style.height = '22px';
        const multiline = input.value.includes('\\n') || input.scrollHeight > 38;
        popover.classList.toggle('is-multiline', multiline);
        if (multiline) input.style.height = Math.min(input.scrollHeight, 118) + 'px';
      });
      input.addEventListener('keydown', (keyEvent) => { if (keyEvent.key === 'Enter' && !keyEvent.shiftKey && !keyEvent.isComposing) { keyEvent.preventDefault(); addComment(); } });
      popover.addEventListener('mousedown', (popoverEvent) => popoverEvent.stopPropagation());
      popover.append(input, cancel, submit);
      document.body.appendChild(popover);
      input.focus();
    };
    document.addEventListener('pointerdown', openCommentPopover, true);
    document.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 || event.target?.closest?.('.lumina-ai-comment-popover')) return;
      savedRange = null;
      closePopover();
    }, true);
    document.addEventListener('contextmenu', (event) => {
      if (document.querySelector('.lumina-ai-comment-popover')) event.preventDefault();
    }, true);
    document.body.focus();
  `;
  document.body.appendChild(bridge);
  return `<!doctype html>\n${document.documentElement.outerHTML}`;
}

const starterPrompts = [
  { category: "보고서 작성", title: "주제 조사 보고서", prompt: "[포스코 관련 국내외 언론기사 동향]에 대해 최근 3개월의 자료를 조사하고, 보고서로 작성해줘", icon: FileText },
  { category: "경쟁사 분석", title: "경쟁사 이슈 비교", prompt: "(주)포스코의 해외 주요 경쟁사를 정의하고, 포스코를 포함한 각 회사별 올해 주요 이슈를 뉴스 기사 기반으로 분석해줘.", icon: Search },
  { category: "공시 분석", title: "DART 공시 분석", prompt: "[포스코]의 DART 공시정보를 기반으로 최근 실적, 주요 사업, 투자·리스크 요인을 분석해줘", icon: FileCheck2 },
  { category: "영상 분석", title: "유튜브 내용 분석", prompt: "[YouTube 링크]에서 설명하는 내용을 정리해줘", icon: Eye },
  { category: "데이터 분석", title: "표 데이터 보고서", prompt: "아래 숫자 데이터를 분석해서 주요 추세, 이상치, 원인 가설, 의사결정 포인트를 정리하고 HTML 보고서로 작성해줘.\n\n[표 데이터 붙여넣기]", icon: Table2 },
  { category: "엑셀 모델", title: "투자수익성 모델", prompt: "[포스코의 인도 일관제철소] 투자와 관련해 투자수익성 검토 모델을 엑셀로 만들어줘.", icon: Coins },
  { category: "Workflow", title: "업무 흐름 다이어그램", prompt: "[포스코 투자관리그룹]의 주요 업무를 조사하고, workflow diagram을 포함하여 전반적인 업무 흐름과 세부 사항을 정리해줘.", icon: GitBranch },
  { category: "프로그램", title: "AI 지렁이 게임", prompt: "최신 최적화 알고리즘이 반영된 인공지능 지렁이 게임을 HTML로 만들어줘. 먹이는 5개, 이동속도는 정상 수준의 5배, 죽으면 1초 뒤 자동 재시작되게 해줘, 벽은 통과할 수 없어.", icon: Code2 },
  { category: "3D 모델", title: "태양계 시뮬레이터", prompt: "태양계 행성 궤도 3D 시뮬레이터를 HTML로 만들어줘. 행성들이 태양 주변을 공전하고, 속도 조절·일시정지·행성 이름 표시 기능을 포함해줘.", icon: Brain },
] as const;

function StarterPrompts({ onSelect }: { onSelect: (prompt: string) => void }) {
  return (
    <div className="starter-prompts" aria-label="예시 질문">
      {starterPrompts.map((item) => {
        const Icon = item.icon;
        return (
          <button className="starter-prompt-button" type="button" key={`${item.category}-${item.title}`} aria-label={`${item.category}: ${item.title}`} onClick={() => onSelect(item.prompt)}>
            <span className="starter-prompt-icon" aria-hidden="true"><Icon size={18} /></span>
            <span className="starter-prompt-copy"><small>{item.category}</small><strong>{item.title}</strong></span>
          </button>
        );
      })}
    </div>
  );
}
type MainView = "chat" | "marketplace" | "library" | "files" | "schedules" | "memory" | "admin" | "settings" | "project-settings";

interface ComposerTriggerState {
  trigger: "@" | "$";
  query: string;
  start: number;
  end: number;
}

interface SelectedComposerReference {
  key: string;
  token: string;
  name: string;
  subtitle: string;
  reference: PromptReference;
}

const navigation = [
  { id: "chat", label: "에이전트", icon: Bot },
  { id: "marketplace", label: "마켓스토어", icon: Store },
  { id: "library", label: "라이브러리", icon: Library },
  { id: "files", label: "파일", icon: FolderOpen },
  { id: "schedules", label: "예약 작업", icon: Clock3 },
  { id: "memory", label: "Memory", icon: Brain },
] satisfies Array<{ id: MainView; label: string; icon: typeof Bot }>;

function isUntitledConversation(title: string) {
  return title === "제목 없음" || title === "새 작업";
}

function userAvatarText(displayName: string | null, loginName: string, email: string) {
  const source = displayName?.trim() || loginName.trim() || email.split("@", 1)[0] || "?";
  const korean = source.match(/[가-힣]/);
  if (korean) return korean[0];
  const latin = source.match(/[A-Za-z]/g)?.join("") ?? "";
  return (latin.slice(0, 2) || source.slice(0, 1)).toUpperCase();
}

const accountProviderOrder: Record<string, number> = {
  pgpt: 0,
  google: 1,
  codex: 2,
  anthropic: 3,
};

function findComposerTrigger(text: string, caret: number): ComposerTriggerState | null {
  const beforeCaret = text.slice(0, caret);
  const match = beforeCaret.match(/(?:^|\s)([@$])([^\s@$]*)$/);
  if (!match || match.index === undefined) return null;
  const leadingWhitespace = match[0].length - match[0].trimStart().length;
  const start = match.index + leadingWhitespace;
  return {
    trigger: match[1] as "@" | "$",
    query: match[2],
    start,
    end: caret,
  };
}

function suggestionIcon(kind: ReferenceKind) {
  if (kind === "artifact") return <FileCode2 size={15} aria-hidden="true" />;
  if (kind === "skill") return <Sparkles size={15} aria-hidden="true" />;
  if (kind === "mcp") return <Wrench size={15} aria-hidden="true" />;
  return <FileText size={15} aria-hidden="true" />;
}

function toolCallIcon(toolName: string, size = 15) {
  const normalizedName = toolName.toLowerCase().replace(/[\s-]+/g, "_");
  if (normalizedName === "web_search") return <Globe2 className="tool-kind-icon is-web-search" size={size} aria-hidden="true" />;
  if (normalizedName === "glob") return <FolderSearch className="tool-kind-icon is-glob" size={size} aria-hidden="true" />;
  if (normalizedName === "write_file") return <FilePenLine className="tool-kind-icon is-write-file" size={size} aria-hidden="true" />;
  if (normalizedName.includes("report")) return <FileCode2 className="tool-kind-icon is-report" size={size} aria-hidden="true" />;
  return <FileText className="tool-kind-icon" size={size} aria-hidden="true" />;
}

function referenceKindLabel(kind: ReferenceKind) {
  if (kind === "artifact") return "Artifact";
  if (kind === "skill") return "Skill";
  if (kind === "mcp") return "MCP";
  return "파일";
}

function sharedTokenFromPath(pathname: string) {
  const match = pathname.match(/^\/shared\/([^/]+)\/?$/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function sharedThemeFromLocation() {
  return new URLSearchParams(window.location.search).get("theme") === "dark" ? "dark" : "light";
}

function formatDuration(durationMs: number | null) {
  if (durationMs === null) return "—";
  return `${(durationMs / 1000).toFixed(2)}초`;
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

type TokenPricing = readonly [number, number, number, number, number?, number?, number?, number?, number?];

const MODEL_TOKEN_PRICING: Record<string, TokenPricing> = {
  "openai:gpt-5.6-sol": [5, 0.5, 6.25, 30, 272_000, 10, 1, 12.5, 45],
  "codex:gpt-5.6-sol": [5, 0.5, 6.25, 30, 272_000, 10, 1, 12.5, 45],
  "openai:gpt-5.6-terra": [2.5, 0.25, 3.125, 15, 272_000, 5, 0.5, 6.25, 22.5],
  "codex:gpt-5.6-terra": [2.5, 0.25, 3.125, 15, 272_000, 5, 0.5, 6.25, 22.5],
  "openai:gpt-5.6-luna": [1, 0.1, 1.25, 6, 272_000, 2, 0.2, 2.5, 9],
  "codex:gpt-5.6-luna": [1, 0.1, 1.25, 6, 272_000, 2, 0.2, 2.5, 9],
  "codex:gpt-5.5": [5, 0.5, 5, 30, 272_000, 10, 1, 10, 45],
  "codex:gpt-5.4": [2.5, 0.25, 2.5, 15, 272_000, 5, 0.5, 5, 22.5],
  "anthropic:claude-opus-4-8": [5, 0.5, 6.25, 25],
  "anthropic:claude-sonnet-5": [2, 0.2, 2.5, 10],
  "anthropic:claude-haiku-4-5": [1, 0.1, 1.25, 5],
  "google:gemini-3.1-pro": [2, 0.2, 2, 12, 200_000, 4, 0.4, 4, 18],
  "google:gemini-3.5-flash": [1.5, 0.15, 1.5, 9],
};

function estimatedModelCostParts(provider: string | undefined, model: string | undefined, usage: Record<string, unknown> | undefined) {
  const pricing = MODEL_TOKEN_PRICING[`${provider}:${model}`];
  if (!pricing) return undefined;
  const input = usageNumber(usage, "input_tokens");
  const cached = usageNumber(usage, "cached_input_tokens");
  const cacheWrite = usageNumber(usage, "cache_write_tokens");
  const uncached = usage?.uncached_input_tokens === undefined
    ? Math.max(0, input - cached - cacheWrite)
    : usageNumber(usage, "uncached_input_tokens");
  const output = usageNumber(usage, "output_tokens");
  const [baseInput, baseCached, baseWrite, baseOutput, threshold, highInput, highCached, highWrite, highOutput] = pricing;
  const high = threshold !== undefined && input > threshold;
  const uncachedInput = uncached * (high ? highInput! : baseInput) / 1_000_000;
  const cachedInput = cached * (high ? highCached! : baseCached) / 1_000_000;
  const cacheWriteInput = cacheWrite * (high ? highWrite! : baseWrite) / 1_000_000;
  const outputCost = output * (high ? highOutput! : baseOutput) / 1_000_000;
  return {
    cachedInput,
    input: uncachedInput + cachedInput + cacheWriteInput,
    output: outputCost,
    total: uncachedInput + cachedInput + cacheWriteInput + outputCost,
    uncachedInput,
  };
}

function UsageCostPopover({ usage, model, provider }: { usage: Record<string, unknown> | undefined; model?: string; provider?: string }) {
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
  const input = usageNumber(usage, "input_tokens");
  const cached = usageNumber(usage, "cached_input_tokens");
  const uncached = usage?.uncached_input_tokens === undefined
    ? Math.max(0, input - cached)
    : usageNumber(usage, "uncached_input_tokens");
  const output = usageNumber(usage, "output_tokens");
  const total = input + output;
  const cacheRate = input > 0 ? `${((cached / input) * 100).toFixed(1)}%` : "0.0%";
  const reportedCost = Number(usage?.cost_usd);
  const hasReportedCost = Number.isFinite(reportedCost) && reportedCost >= 0;
  const estimatedCosts = estimatedModelCostParts(provider, model, usage);
  const estimatedCost = estimatedCosts?.total;
  const cost = hasReportedCost ? reportedCost : estimatedCost;
  const formatCost = (value: number | undefined) => {
    if (value === undefined) return "—";
    if (usdKrwRate === undefined) return "…";
    return usdKrwRate === null
      ? value.toFixed(3)
      : new Intl.NumberFormat("ko-KR").format(Math.round(value * usdKrwRate));
  };
  const totalCost = formatCost(cost);
  const currencySymbol = usdKrwRate === null ? "$" : "₩";
  const costHeading = (!hasReportedCost && estimatedCost !== undefined) || usage?.cost_basis === "price_table_estimate"
    ? `예상비용(${currencySymbol})`
    : `비용(${currencySymbol})`;
  const rows = [
    ["Input", input.toLocaleString(), formatCost(estimatedCosts?.input)],
    ["Cached", cached.toLocaleString(), formatCost(estimatedCosts?.cachedInput)],
    ["Uncached", uncached.toLocaleString(), formatCost(estimatedCosts?.uncachedInput)],
    ["Cache rate", cacheRate, "-"],
    ["Output", output.toLocaleString(), formatCost(estimatedCosts?.output)],
    ["Total", total.toLocaleString(), totalCost],
  ];

  return (
    <span className="answer-usage-control">
      <button className="answer-usage-button" type="button" aria-label="토큰 비용 확인"><Coins size={16} /></button>
      <span className="answer-usage-popover" role="tooltip">
        <table aria-label="이번 답변 토큰 및 비용">
          <thead>
            <tr><th>{model || "사용량"}</th><th>토큰</th><th>{costHeading}</th></tr>
          </thead>
          <tbody>
            {rows.map(([label, tokens, cost]) => (
              <tr className={label === "Total" ? "is-total" : label === "Cached" || label === "Uncached" || label === "Cache rate" ? "is-child" : ""} key={label}>
                <th scope="row">{label}</th><td>{tokens}</td><td>{cost}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </span>
    </span>
  );
}

function runStatusLabel(status: RunStatus | null | undefined) {
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
  onToggle,
  onCopy,
}: {
  execution: ToolExecution;
  isOpen: boolean;
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
  const running = execution.status === "running";
  const headerDetail = webSearchQuery(execution) ?? webFetchSummary(execution) ?? createReportSummary(execution);
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
      <button ref={triggerRef} className="tool-call-trigger" type="button" aria-expanded={isOpen} aria-controls={contentId} onClick={onToggle}>
        {running ? (
          <LoaderCircle className="status-icon is-running" size={15} aria-hidden="true" />
        ) : complete ? (
          <Check className="status-icon is-complete" size={15} aria-hidden="true" />
        ) : execution.status === "failed" ? (
          <AlertCircle className="status-icon status-warning" size={15} aria-hidden="true" />
        ) : (
          <Circle className="status-icon is-waiting" size={15} aria-hidden="true" />
        )}
        {toolCallIcon(execution.toolName)}
        <span className="tool-call-label">{execution.label || execution.toolName}</span>
        <span className="tool-call-detail" title={headerDetail ?? undefined}>{headerDetail}</span>
        <span className={`tool-call-status status-${running ? "running" : complete ? "complete" : "warning"}`}>{toolStatusLabel(execution.status)}</span>
        <span className="tool-call-duration">{formatDuration(execution.durationMs)}</span>
        {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
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

function RunActivityTimeline({
  activities,
  openCalls,
  onToggleCall,
  onCopy,
}: {
  activities: RunActivity[];
  openCalls: Set<string>;
  onToggleCall: (id: string) => void;
  onCopy: (execution: ToolExecution) => void;
}) {
  const [openSummaryIds, setOpenSummaryIds] = useState<Set<string>>(new Set());
  const previousActiveSummaryIds = useRef<Set<string>>(new Set());
  const activityGroups = activities.reduce<RunActivity[][]>((groups, activity) => {
    if (activity.type === "progress_summary" || activity.type === "skill" || groups.length === 0) groups.push([]);
    groups.at(-1)?.push(activity);
    return groups;
  }, []);
  const activeSummaryIds = new Set(activityGroups.flatMap((group) => {
    const summary = group[0]?.type === "progress_summary" ? group[0] : null;
    const toolCount = group.filter((activity) => activity.type === "tool").length;
    const hasActiveTools = group.some((activity) => activity.type === "tool"
      && (activity.execution.status === "queued" || activity.execution.status === "running"));
    return summary && toolCount > 1 && hasActiveTools ? [summary.id] : [];
  }));
  const activeSummaryKey = [...activeSummaryIds].sort().join("|");

  useEffect(() => {
    const previous = previousActiveSummaryIds.current;
    setOpenSummaryIds((current) => {
      const next = new Set(current);
      previous.forEach((id) => {
        if (!activeSummaryIds.has(id)) next.delete(id);
      });
      activeSummaryIds.forEach((id) => {
        if (!previous.has(id)) next.add(id);
      });
      return next;
    });
    previousActiveSummaryIds.current = activeSummaryIds;
  }, [activeSummaryKey]);

  return (
    <section className="run-activity-timeline" aria-label="실행 과정">
      {activityGroups.map((group) => {
        const summary = group[0]?.type === "progress_summary" ? group[0] : null;
        const skill = group[0]?.type === "skill" ? group[0] : null;
        const toolActivities = group.filter((activity) => activity.type === "tool");
        const hasTools = toolActivities.length > 0;
        const hasToolGroup = toolActivities.length > 1;
        const toolsOpen = !hasToolGroup || (summary ? openSummaryIds.has(summary.id) : true);
        const toolGroupId = summary ? `progress-tools-${summary.id}` : undefined;
        const toggleTools = () => setOpenSummaryIds((current) => {
          if (!summary) return current;
          const next = new Set(current);
          if (next.has(summary.id)) next.delete(summary.id);
          else next.add(summary.id);
          return next;
        });
        return (
          <div className="progress-group" key={summary?.id ?? group[0]?.id}>
            {skill && (
              <div className="skill-activity" aria-label={`사용 Skill ${skill.slug}`}>
                <Sparkles size={14} aria-hidden="true" />
                <span className="skill-activity-kind">Skill</span>
                <strong>{skill.slug}</strong>
                <span className="skill-activity-detail">
                  {skill.reason} · {skill.appliedBy === "auto" ? "자동 적용" : skill.appliedBy === "explicit" ? "$Skill 호출" : "예약 적용"}
                  {skill.versionLabel ? ` · ${skill.versionLabel}` : ""}
                </span>
                <span className="skill-activity-status">적용됨</span>
              </div>
            )}
            {summary && (hasToolGroup ? (
              <button className="progress-group-toggle" type="button" aria-controls={toolGroupId} aria-expanded={toolsOpen} onClick={toggleTools}>
                <div className={`progress-summary phase-${summary.phase}`}>
                  <div className="progress-summary-text">
                    {progressSummaryIcon(summary.phase, summary.text)}
                    <span>{summary.text}</span>
                  </div>
                </div>
                <div className="tool-call-group-summary">
                  {toolCallIcon(toolActivities[0].execution.toolName, 14)}
                  <span>{toolCallGroupSummary(toolActivities)}</span>
                  <span className="tool-call-group-duration">{formatDuration(toolCallGroupDuration(toolActivities))}</span>
                  {toolsOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                </div>
              </button>
            ) : (
              <div className={`progress-summary phase-${summary.phase}`}><div className="progress-summary-text">{progressSummaryIcon(summary.phase, summary.text)}<span>{summary.text}</span></div></div>
            ))}
            {toolsOpen && hasTools && (
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
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

function progressSummaryIcon(phase: string, text: string) {
  if (text.includes("검색") || text.includes("근거를 수집")) return <Search size={14} aria-hidden="true" />;
  if (text.includes("원문")) return <Eye size={14} aria-hidden="true" />;
  if (text.includes("보고서") || text.includes("문서")) return <FileText size={14} aria-hidden="true" />;
  if (text.includes("이미지")) return <ImageIcon size={14} aria-hidden="true" />;
  if (phase === "planning") return <GitBranch size={14} aria-hidden="true" />;
  if (phase === "review") return <FileCheck2 size={14} aria-hidden="true" />;
  if (phase === "compacting" || phase === "compacted") return <Brain size={14} aria-hidden="true" />;
  if (phase === "tools") return <Wrench size={14} aria-hidden="true" />;
  return <Sparkles size={14} aria-hidden="true" />;
}

function pendingMessageLabel(message: ChatMessage, commands: RunCommand[]) {
  const command = commands.find((item) => item.messageId === message.id);
  if (!command) return message.status === "pending" ? "접수 중" : null;
  if (command.type === "queue_next") return command.queuePosition ? `Queue ${command.queuePosition}번` : "다음 요청으로 대기";
  if (command.status === "waiting_safe_boundary") return "현재 Run에 반영 대기";
  return "현재 Run에 반영됨";
}

interface CitationTarget {
  source: SourceEvidence;
  markerNumber: number;
  cited: boolean;
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
      cited: citation ? citation.status === "cited" : hasSourceToken || hasMarkerToken,
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
  const marker = citationMarkerLabel(target.markerNumber);
  const rawUrl = target.source.normalizedUrl || target.source.originalUrl;
  const safeUrl = defaultUrlTransform(rawUrl);
  const tooltip = (
    <span className="citation-tooltip" id={tooltipId} role="tooltip">
      <strong>{target.source.title || target.source.domain || `출처 ${target.markerNumber}`}</strong>
      <span>{rawUrl || "URL 없음"}</span>
      <q>{target.source.verbatimExcerpt || "근거 문장 없음"}</q>
    </span>
  );
  if (!safeUrl) {
    return <span className="inline-citation" tabIndex={0} aria-label={`출처 ${target.markerNumber}`} aria-describedby={tooltipId}><span aria-hidden="true">{marker}</span>{tooltip}</span>;
  }
  return (
    <a className="inline-citation" href={safeUrl} target="_blank" rel="noreferrer noopener" aria-label={`출처 ${target.markerNumber}: ${target.source.title || target.source.domain}`} aria-describedby={tooltipId}>
      <span aria-hidden="true">{marker}</span>{tooltip}
    </a>
  );
}

const emptySources: SourceEvidence[] = [];
const emptyCitations: MessageCitation[] = [];

function normalizeKoreanMarkdownEmphasis(text: string) {
  return text.replace(/(\*\*[^*\n]+?\*\*)(?=[가-힣])/gu, "$1<!-- -->");
}

type StreamingPendingKind = "mermaid" | "table" | null;

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
  }
  for (let index = 1; index < lines.length; index += 1) {
    if (isMarkdownTableRow(lines[index - 1]) && isMarkdownTableDivider(lines[index])) return "table";
  }
  return null;
}

let mermaidRenderSequence = 0;

function MermaidDiagram({ source }: { source: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    void import("mermaid").then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base" });
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
  return <div ref={containerRef} className="mermaid-diagram" role="img" aria-label="Mermaid 다이어그램"><span>다이어그램 렌더링 중…</span></div>;
}

function StreamingBlockPending({ kind }: { kind: Exclude<StreamingPendingKind, null> }) {
  return (
    <div className={`stream-block-pending is-${kind}`} role="status">
      {kind === "mermaid" ? <GitBranch size={18} /> : <Table2 size={18} />}
      <span>{kind === "mermaid" ? "다이어그램 작성 중" : "표 작성 중"}</span>
      <LoaderCircle className="is-running" size={15} />
    </div>
  );
}

function pastedTextAttachmentLabel(attachment: AttachmentSummary, index: number) {
  const lineCount = Number(attachment.metadata?.lineCount ?? 0);
  return `[텍스트 첨부 #${index + 1}${lineCount > 0 ? ` +${lineCount}줄` : ""}]`;
}

function hideRedundantArtifactOpenLine(text: string, hasArtifacts: boolean) {
  return hasArtifacts ? text.replace(/^[ \t]*보고서 열기[ \t]*\r?\n?/gm, "") : text;
}

function MarkdownResponse({
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
  const streamingParts = useMemo(() => streaming ? splitStreamingMarkdown(text) : { prefix: text, liveTail: "" }, [streaming, text]);
  const pendingKind = useMemo(() => streaming ? pendingStreamingKind(streamingParts.liveTail) : null, [streaming, streamingParts.liveTail]);
  const prefixText = useMemo(() => normalizeKoreanMarkdownEmphasis(streamingParts.prefix), [streamingParts.prefix]);
  const tailText = useMemo(() => normalizeKoreanMarkdownEmphasis(streamingParts.liveTail), [streamingParts.liveTail]);
  const targets = useMemo(() => citationTargets(text, sources, citations), [citations, sources, text]);
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
        ? <a className="markdown-image-link" href={safeSrc} target="_blank" rel="noreferrer noopener">이미지: {alt || safeSrc}</a>
        : <span>{alt || "이미지"}</span>;
    },
    table: ({ children }) => <div className="markdown-table-scroll"><table>{children}</table></div>,
    code: ({ className, children }) => {
      const language = /language-([\w-]+)/.exec(className || "")?.[1]?.toLowerCase();
      const source = String(children).replace(/\n$/, "");
      return language === "mermaid" || language === "mmd"
        ? <MermaidDiagram source={source} />
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

function AssistantTurn({
  turnSet,
  snapshot,
  openCalls,
  onToggleCall,
  onCopyTool,
  onOpenArtifact,
  onShare,
  onToast,
  onVisibleGrowth,
}: {
  turnSet: TurnSet;
  snapshot: RunSnapshot | null;
  openCalls: Set<string>;
  onToggleCall: (id: string) => void;
  onCopyTool: (execution: ToolExecution) => void;
  onOpenArtifact: (artifact: ArtifactSummary) => void;
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
  const assistantText = finalMessage?.text || snapshot?.assistantDraft?.text || "";
  const sourceTargets = citationTargets(assistantText, sources, citations);
  const citedSourceCount = sourceTargets.filter((target) => target.cited).length;
  const tools = snapshot?.toolExecutions ?? turnSet.toolExecutions;
  const activities: RunActivity[] = snapshot?.activities?.length
    ? snapshot.activities
    : tools.map((execution, index) => ({
        id: `tool:${execution.id}`,
        type: "tool" as const,
        sequence: index,
        execution,
      }));
  const artifacts = snapshot?.artifacts ?? turnSet.artifacts;
  const pendingCommands = snapshot?.pendingCommands ?? [];
  const status = snapshot?.status ?? (finalMessage ? "completed" : null);
  const terminal = status === "completed" || status === "failed" || status === "cancelled" || status === "interrupted" || status === "limit_reached";
  const streaming = !finalMessage && Boolean(snapshot?.assistantDraft);
  const { visibleText, revealing } = useStreamingText(assistantText, streaming);
  const displayedText = hideRedundantArtifactOpenLine(visibleText, artifacts.length > 0);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportText, setReportText] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [expandedSourceId, setExpandedSourceId] = useState<string | null>(null);
  const [previewAttachment, setPreviewAttachment] = useState<AttachmentSummary | null>(null);
  const [textPreviewAttachment, setTextPreviewAttachment] = useState<AttachmentSummary | null>(null);
  const [textPreviewContent, setTextPreviewContent] = useState("");
  const [textPreviewError, setTextPreviewError] = useState<string | null>(null);
  const expandedSourceTarget = sourceTargets.find(({ source }) => source.sourceId === expandedSourceId) ?? null;

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
    if (!assistantText) return;
    try {
      await navigator.clipboard.writeText(assistantText);
      onToast("답변을 복사했습니다.");
    } catch {
      onToast("답변을 복사하지 못했습니다.");
    }
  };
  const rateAnswer = async (value: "like" | "dislike") => {
    if (!finalMessage) return;
    try {
      await api.messages.putRating(finalMessage.id, value);
      onToast(value === "like" ? "좋아요를 기록했습니다." : "싫어요를 기록했습니다.");
    } catch {
      onToast("평가를 기록하지 못했습니다.");
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
  return (
    <div className="turn-set" data-run-id={turnSet.runId ?? undefined}>
      {userMessages.map((message) => (
        <div className="user-message-group" key={message.id}>
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
            {pendingMessageLabel(message, pendingCommands) && <small className="message-state">{pendingMessageLabel(message, pendingCommands)}</small>}
          </div>
        </div>
      ))}
      {activities.length > 0 && (
        <div className="turn-tool-activity">
          <RunActivityTimeline
            activities={activities}
            openCalls={openCalls}
            onCopy={onCopyTool}
            onToggleCall={onToggleCall}
          />
        </div>
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
            {snapshot?.artifactProgress && (
              <div className="artifact-progress-count" role="status" aria-label="Artifact 작성 진행률">
                <strong>{snapshot.artifactProgress.tokens.toLocaleString()} 토큰</strong>
                <span>({snapshot.artifactProgress.lines.toLocaleString()}줄)</span>
              </div>
            )}
            {!assistantText && snapshot && !terminal && <p className="assistant-placeholder"><LoaderCircle className="is-running" size={14} /> {runStatusLabel(snapshot.status)}</p>}
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
                    <button className="tooltip-control" type="button" aria-label="답변 복사" data-tooltip="복사" onClick={() => void copyAnswer()}><Copy size={16} /></button>
                    <button className="tooltip-control" type="button" aria-label="답변 공유" data-tooltip="공유" disabled={!assistantText} onClick={() => onShare(finalMessage?.id ?? null)}><Share2 size={16} /></button>
                    <UsageCostPopover
                      usage={finalMessage?.metadata?.usage ?? snapshot?.usage}
                      model={snapshot?.execution.runtimeModelId}
                      provider={snapshot?.execution.providerId}
                    />
                    <button className="tooltip-control" type="button" aria-label="좋아요" data-tooltip="좋아요" disabled={!finalMessage} onClick={() => void rateAnswer("like")}><ThumbsUp size={16} /></button>
                    <button className="tooltip-control" type="button" aria-label="싫어요" data-tooltip="싫어요" disabled={!finalMessage} onClick={() => void rateAnswer("dislike")}><ThumbsDown size={16} /></button>
                    <button className={`tooltip-control ${reportOpen ? "is-active" : ""}`} type="button" aria-label="의견 게시" aria-expanded={reportOpen} data-tooltip="의견 게시" disabled={!finalMessage} onClick={() => { setReportOpen((open) => !open); setReportError(null); }}><MessageSquarePlus size={16} /></button>
                  </div>
                  <time className="answer-completed-time" dateTime={snapshot?.finishedAt ?? finalMessage?.completedAt ?? undefined}>{formatCompletedAt(snapshot?.finishedAt ?? finalMessage?.completedAt)}</time>
                  {sources.length > 0 && (
                    <div className="answer-sources">
                      <button className="answer-sources-trigger" type="button" aria-expanded={sourcesOpen} onClick={() => { if (sourcesOpen) closeSources(); else setSourcesOpen(true); }}>검색 및 참고 출처 · 인용 {citedSourceCount} · 참고 {sources.length - citedSourceCount}</button>
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
                                  <span className="source-kind">{expandedSourceTarget.cited ? `${citationMarkerLabel(expandedSourceTarget.markerNumber)} 본문 인용` : "참고만 함"}</span>
                                  {defaultUrlTransform(expandedSourceTarget.source.normalizedUrl || expandedSourceTarget.source.originalUrl)
                                    ? <a href={defaultUrlTransform(expandedSourceTarget.source.normalizedUrl || expandedSourceTarget.source.originalUrl)} target="_blank" rel="noreferrer noopener">{expandedSourceTarget.source.title || expandedSourceTarget.source.domain}</a>
                                    : <strong>{expandedSourceTarget.source.title || expandedSourceTarget.source.domain}</strong>}
                                  <small>{expandedSourceTarget.source.domain}{expandedSourceTarget.source.evidenceKind === "fetched_content" ? " · 본문 확인" : ""}</small>
                                </div>
                                <p className="source-detail-excerpt">{expandedSourceTarget.source.verbatimExcerpt}</p>
                              </div>
                            ) : (
                              <>
                                {searches.length > 0 && (
                                  <div className="source-queries">{searches.map((search) => <span key={search.invocationId}>{search.query}</span>)}</div>
                                )}
                                <ol>
                                  {sourceTargets.map(({ source, markerNumber, cited }) => (
                                    <li className={cited ? "is-cited" : "is-reference-only"} key={source.sourceId}>
                                      <div className="source-header">
                                        <span className="source-kind">{cited ? `${citationMarkerLabel(markerNumber)} 본문 인용` : "참고만 함"}</span>
                                        {defaultUrlTransform(source.normalizedUrl || source.originalUrl)
                                          ? <a href={defaultUrlTransform(source.normalizedUrl || source.originalUrl)} target="_blank" rel="noreferrer noopener">{source.title || source.domain}</a>
                                          : <strong>{source.title || source.domain}</strong>}
                                        <small>{source.domain}{source.evidenceKind === "fetched_content" ? " · 본문 확인" : ""}</small>
                                        </div>
                                      {source.verbatimExcerpt && (
                                        <div className="source-excerpt-row">
                                          <button className="source-excerpt" type="button" aria-label={`${source.title || source.domain} 확대해서 보기`} onClick={() => openSourceDetail(source.sourceId)}>{source.verbatimExcerpt}</button>
                                          <button type="button" aria-label={`${source.title || source.domain} 본문 복사`} onClick={() => {
                                            void navigator.clipboard.writeText(source.verbatimExcerpt ?? "")
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

function derivedProgress(run: RunSnapshot) {
  if (run.plan?.steps.length) {
    return run.plan.steps.map((step) => ({
      id: step.id,
      label: step.label,
      status: step.status === "completed" ? "complete" : step.status === "running" ? "running" : step.status === "failed" ? "error" : "waiting",
      subtasks: [...(step.subtasks ?? [])].sort((left, right) => left.order - right.order),
    }));
  }
  const terminal = ["completed", "failed", "cancelled", "limit_reached", "interrupted"].includes(run.status);
  const hasTools = run.toolExecutions.length > 0;
  const toolsDone = hasTools && run.toolExecutions.every((item) => item.status === "completed");
  return [
    { id: "accepted", label: "요청 접수 및 실행 준비", status: "complete", subtasks: [] },
    { id: "analysis", label: "요청 분석 및 응답 구성", status: hasTools || terminal ? "complete" : "running", subtasks: [] },
    { id: "tools", label: "필요한 도구 실행", status: run.status === "tools_running" ? "running" : toolsDone || terminal ? "complete" : "waiting", subtasks: [] },
    { id: "answer", label: "결과 정리 및 사용자 전달", status: run.status === "completed" ? "complete" : terminal ? "error" : toolsDone || !hasTools && run.status === "model_streaming" ? "running" : "waiting", subtasks: [] },
  ];
}

function formatNotificationTime(value: string) {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const elapsed = Math.max(0, Date.now() - timestamp);
  if (elapsed < 60_000) return "방금 전";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)}분 전`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)}시간 전`;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(timestamp);
}

interface ComposerPickerOption {
  id: string;
  label: string;
  triggerLabel?: string;
}

function ComposerPicker({
  options,
  value,
  onChange,
  ariaLabel,
  menuLabel,
  controlClassName,
  placeholder,
}: {
  options: ComposerPickerOption[];
  value: string;
  onChange: (id: string) => void;
  ariaLabel: string;
  menuLabel: string;
  controlClassName: string;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const selectedIndex = options.findIndex((option) => option.id === value);
  const selected = options[selectedIndex];

  const openMenu = () => {
    setActiveIndex(Math.max(selectedIndex, 0));
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);

  const choose = (option: ComposerPickerOption) => {
    onChange(option.id);
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div className={`composer-picker ${open ? "is-open" : ""}`} ref={rootRef}>
      <button
        ref={triggerRef}
        className={`composer-picker-trigger ${controlClassName}`}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        disabled={options.length === 0}
        onClick={() => open ? setOpen(false) : openMenu()}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            if (!open) {
              openMenu();
              return;
            }
            const direction = event.key === "ArrowDown" ? 1 : -1;
            setActiveIndex((current) => (current + direction + options.length) % options.length);
          } else if (event.key === "Enter" && open) {
            event.preventDefault();
            const active = options[activeIndex];
            if (active) choose(active);
          } else if (event.key === "Escape" && open) {
            event.preventDefault();
            setOpen(false);
          }
        }}
      >
        <span>{selected?.triggerLabel ?? selected?.label ?? placeholder ?? ariaLabel}</span>
        <ChevronDown size={13} aria-hidden="true" />
      </button>
      {open && (
        <div className="composer-picker-menu" id={listId} role="listbox" aria-label={ariaLabel}>
          <div className="composer-picker-menu-label">{menuLabel}</div>
          {options.map((option, index) => (
            <button
              key={option.id}
              className={`${option.id === value ? "is-selected" : ""} ${index === activeIndex ? "is-active" : ""}`}
              type="button"
              role="option"
              aria-selected={option.id === value}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => choose(option)}
            >
              <span>{option.label}</span>
              <Check size={14} aria-hidden="true" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function App() {
  const workspace = useLuminaWorkspace();
  const [mainView, setMainView] = useState<MainView>("chat");
  const [settingsSection, setSettingsSection] = useState<"personal" | "admin">("personal");
  const [progressOpen, setProgressOpen] = useState(false);
  const progressRunIdRef = useRef<string | null>(null);
  const [openCalls, setOpenCalls] = useState<Set<string>>(new Set());
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const sidebarAutoCollapsedRef = useRef(false);
  const [sessionMenuId, setSessionMenuId] = useState<string | null>(null);
  const [sessionDeleteArmedId, setSessionDeleteArmedId] = useState<string | null>(null);
  const [sessionDeleteBusyId, setSessionDeleteBusyId] = useState<string | null>(null);
  const [moveMenuId, setMoveMenuId] = useState<string | null>(null);
  const [bulkSessionMode, setBulkSessionMode] = useState(false);
  const [bulkSessionIds, setBulkSessionIds] = useState<Set<string>>(new Set());
  const [bulkMoveOpen, setBulkMoveOpen] = useState(false);
  const [bulkSessionBusy, setBulkSessionBusy] = useState(false);
  const [bulkSessionDeleteArmed, setBulkSessionDeleteArmed] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [providerMenuOpen, setProviderMenuOpen] = useState(false);
  const [providerModelMenuId, setProviderModelMenuId] = useState<string | null>(null);
  const [modelNameTooltip, setModelNameTooltip] = useState<{ name: string; left: number; top: number } | null>(null);
  const [conversationSearchOpen, setConversationSearchOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [notificationUnreadCount, setNotificationUnreadCount] = useState(0);
  const [notificationLoading, setNotificationLoading] = useState(false);
  const [notificationError, setNotificationError] = useState<string | null>(null);
  const [notificationBusyId, setNotificationBusyId] = useState<string | null>(null);
  const [notificationDeleteArmedId, setNotificationDeleteArmedId] = useState<string | null>(null);
  const [sessionTitleEditing, setSessionTitleEditing] = useState(false);
  const [sessionTitleDraft, setSessionTitleDraft] = useState("");
  const [draft, setDraft] = useState("");
  const [composerTrigger, setComposerTrigger] = useState<ComposerTriggerState | null>(null);
  const [composerSuggestions, setComposerSuggestions] = useState<ComposerSuggestion[]>([]);
  const [selectedReferences, setSelectedReferences] = useState<SelectedComposerReference[]>([]);
  const [suggestionIndex, setSuggestionIndex] = useState(0);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [adminSettingsProviderId, setAdminSettingsProviderId] = useState("");
  const [adminSettingsModels, setAdminSettingsModels] = useState<AdminProviderModel[]>([]);
  const [adminSettingsModelKey, setAdminSettingsModelKey] = useState("");
  const [adminMaxTokens, setAdminMaxTokens] = useState("");
  const [adminSettingsBusy, setAdminSettingsBusy] = useState(false);
  const [adminSettingsError, setAdminSettingsError] = useState<string | null>(null);
  const [artifactOpen, setArtifactOpen] = useState(false);
  const [artifactPaneWidth, setArtifactPaneWidth] = useState(() => {
    const saved = Number(localStorage.getItem("lumina:artifactPaneWidth"));
    return Number.isFinite(saved) && saved >= 360 ? saved : Math.max(520, Math.round(window.innerWidth * 0.42));
  });
  const [artifactResizing, setArtifactResizing] = useState(false);
  const [artifactFullscreen, setArtifactFullscreen] = useState(false);
  const [artifactTab, setArtifactTab] = useState<ArtifactTab>("preview");
  const [artifactSummary, setArtifactSummary] = useState<ArtifactSummary | null>(null);
  const [artifactVersion, setArtifactVersion] = useState<ArtifactVersion | null>(null);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [artifactEditing, setArtifactEditing] = useState(false);
  const [artifactDraft, setArtifactDraft] = useState("");
  const [artifactDraftEtag, setArtifactDraftEtag] = useState<string | undefined>();
  const [artifactDraftSaved, setArtifactDraftSaved] = useState(false);
  const [artifactDraftStale, setArtifactDraftStale] = useState(false);
  const [artifactDraftNotice, setArtifactDraftNotice] = useState<string | null>(null);
  const [artifactEditablePreview, setArtifactEditablePreview] = useState("");
  const [artifactAiComments, setArtifactAiComments] = useState<ArtifactAiComment[]>([]);
  const [artifactAiSubmitting, setArtifactAiSubmitting] = useState(false);
  const [artifactAiStatus, setArtifactAiStatus] = useState<string | null>(null);
  const [artifactSaveBusy, setArtifactSaveBusy] = useState<"draft" | "version" | null>(null);
  const titleCommitRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerInputRef = useRef<HTMLTextAreaElement>(null);
  const previousConversationRef = useRef<string | null>(null);
  const artifactOpenRequestRef = useRef(0);
  const artifactHistoryOpenRef = useRef(false);
  const artifactPreviewFrameRef = useRef<HTMLIFrameElement>(null);
  const dockAreaRef = useRef<HTMLDivElement>(null);
  const notificationMenuRef = useRef<HTMLDivElement>(null);
  const modelNameTooltipTimerRef = useRef<number | null>(null);

  useEffect(() => {
    localStorage.setItem("lumina:artifactPaneWidth", String(artifactPaneWidth));
  }, [artifactPaneWidth]);

  function clampArtifactPaneWidth(value: number, collapsed: boolean) {
    const sidebarWidth = collapsed ? 48 : 278;
    const maximum = Math.max(360, window.innerWidth - sidebarWidth - 400);
    return Math.min(Math.max(value, 360), maximum);
  }

  function beginArtifactResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (artifactFullscreen || window.innerWidth < 1400) return;
    event.preventDefault();
    const handle = event.currentTarget;
    let currentCollapsed = sidebarCollapsed;
    setArtifactResizing(true);
    try { handle.setPointerCapture(event.pointerId); } catch { /* Pointer capture is not available in every browser path. */ }
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      setArtifactResizing(false);
      try {
        if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      } catch { /* The browser may already have released capture. */ }
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      window.removeEventListener("mouseup", finish);
      window.removeEventListener("blur", finish);
    };
    const move = (moveEvent: PointerEvent) => {
      if (moveEvent.buttons === 0) {
        finish();
        return;
      }
      const expandedChatWidth = moveEvent.clientX - 278;
      let nextCollapsed = currentCollapsed;
      if (!currentCollapsed && expandedChatWidth <= 400) {
        nextCollapsed = true;
        sidebarAutoCollapsedRef.current = true;
        setSidebarCollapsed(true);
      } else if (currentCollapsed && sidebarAutoCollapsedRef.current && expandedChatWidth > 400) {
        nextCollapsed = false;
        sidebarAutoCollapsedRef.current = false;
        setSidebarCollapsed(false);
      }
      currentCollapsed = nextCollapsed;
      setArtifactPaneWidth(Math.round(clampArtifactPaneWidth(window.innerWidth - moveEvent.clientX, nextCollapsed)));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    window.addEventListener("mouseup", finish);
    window.addEventListener("blur", finish);
  }

  function resizeArtifactByKeyboard(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (artifactFullscreen || window.innerWidth < 1400 || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? 24 : -24;
    const nextWidth = artifactPaneWidth + delta;
    const expandedChatWidth = window.innerWidth - 278 - nextWidth;
    let nextCollapsed = sidebarCollapsed;
    if (!sidebarCollapsed && expandedChatWidth <= 400) {
      nextCollapsed = true;
      sidebarAutoCollapsedRef.current = true;
      setSidebarCollapsed(true);
    } else if (sidebarCollapsed && sidebarAutoCollapsedRef.current && expandedChatWidth > 400) {
      nextCollapsed = false;
      sidebarAutoCollapsedRef.current = false;
      setSidebarCollapsed(false);
    }
    setArtifactPaneWidth(Math.round(clampArtifactPaneWidth(nextWidth, nextCollapsed)));
  }

  useEffect(() => {
    if (!artifactEditing || artifactVersion?.mimeType !== "text/html") return;
    const receivePreviewEdit = (event: MessageEvent) => {
      if (event.source !== artifactPreviewFrameRef.current?.contentWindow) return;
      if (event.data?.type === artifactPreviewEditMessage && typeof event.data.html === "string") {
        setArtifactDraft(event.data.html);
        setArtifactDraftSaved(false);
        setArtifactDraftNotice(null);
      }
      if (event.data?.type === artifactAiCommentMessage && event.data.comment) {
        const comment = event.data.comment as ArtifactAiComment;
        if (comment.id && comment.text && comment.instruction) {
          setArtifactAiComments((current) => [...current, { ...comment, scope: comment.scope === "document" ? "document" : "selection" }]);
          setArtifactAiStatus(null);
        }
      }
    };
    window.addEventListener("message", receivePreviewEdit);
    return () => window.removeEventListener("message", receivePreviewEdit);
  }, [artifactEditing, artifactVersion?.mimeType]);

  useEffect(() => {
    if (!artifactEditing || artifactVersion?.mimeType !== "text/html") return;
    artifactPreviewFrameRef.current?.contentWindow?.postMessage({
      type: artifactAiCommentsMessage,
      comments: artifactAiComments,
    }, "*");
  }, [artifactAiComments, artifactEditing, artifactVersion?.mimeType]);

  const finishCloseArtifact = useCallback(() => {
    artifactOpenRequestRef.current += 1;
    artifactHistoryOpenRef.current = false;
    setArtifactLoading(false);
    setArtifactOpen(false);
    setArtifactFullscreen(false);
  }, []);

  const closeArtifact = useCallback(() => {
    if (artifactSaveBusy) return;
    if (artifactHistoryOpenRef.current) {
      window.history.back();
      return;
    }
    finishCloseArtifact();
  }, [artifactSaveBusy, finishCloseArtifact]);

  useEffect(() => {
    const onPopState = () => {
      if (artifactHistoryOpenRef.current) finishCloseArtifact();
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [finishCloseArtifact]);

  const theme = workspace.settings?.theme ?? "light";
  const isAdmin = workspace.authSession?.user.role === "admin";
  const activeRuntime = workspace.activeRuntime;
  const activeRun = workspace.activeRun;
  const activeProject = workspace.projects.find((project) => project.id === workspace.activeProjectId) ?? null;

  useEffect(() => {
    if (!activeRun) {
      progressRunIdRef.current = null;
      return;
    }
    const terminal = ["completed", "failed", "cancelled", "limit_reached", "interrupted"].includes(activeRun.status);
    if (progressRunIdRef.current !== activeRun.runId) {
      progressRunIdRef.current = activeRun.runId;
      setProgressOpen(false);
      return;
    }
    if (terminal) {
      setProgressOpen(false);
    }
  }, [activeRun?.runId, activeRun?.status]);
  const accountProviders = workspace.providers
    .filter((provider) => provider.id !== "mock")
    .sort((left, right) => (accountProviderOrder[left.id] ?? Number.MAX_SAFE_INTEGER) - (accountProviderOrder[right.id] ?? Number.MAX_SAFE_INTEGER)
      || left.displayName.localeCompare(right.displayName));
  const selectedAdminSettingsModel = adminSettingsModels.find((model) => model.modelKey === adminSettingsModelKey) ?? null;

  useEffect(() => {
    if (mainView !== "settings" || !isAdmin) return;
    const providerId = adminSettingsProviderId || accountProviders[0]?.id;
    if (!providerId) return;
    if (providerId !== adminSettingsProviderId) setAdminSettingsProviderId(providerId);
    const controller = new AbortController();
    setAdminSettingsBusy(true);
    setAdminSettingsError(null);
    api.adminProviders.listModels(providerId, controller.signal)
      .then((models) => {
        setAdminSettingsModels(models);
        setAdminSettingsModelKey((current) => models.some((model) => model.modelKey === current) ? current : (models[0]?.modelKey ?? ""));
      })
      .catch((error) => {
        if (!controller.signal.aborted) setAdminSettingsError(error instanceof Error ? error.message : "모델 설정을 불러오지 못했습니다.");
      })
      .finally(() => { if (!controller.signal.aborted) setAdminSettingsBusy(false); });
    return () => controller.abort();
  }, [adminSettingsProviderId, isAdmin, mainView, workspace.providers]);

  useEffect(() => {
    const value = selectedAdminSettingsModel?.capabilities.context_window
      ?? selectedAdminSettingsModel?.capabilities.contextWindow
      ?? selectedAdminSettingsModel?.defaultContextWindow;
    setAdminMaxTokens(typeof value === "number" ? value.toLocaleString("en-US") : "");
  }, [selectedAdminSettingsModel]);

  const saveAdminMaxTokens = async () => {
    if (!selectedAdminSettingsModel) return;
    const contextWindow = Number(adminMaxTokens.replaceAll(",", ""));
    if (!Number.isSafeInteger(contextWindow) || contextWindow < 1) {
      setAdminSettingsError("최대 컨텍스트 토큰은 1 이상의 정수로 입력해 주세요.");
      return;
    }
    setAdminSettingsBusy(true);
    setAdminSettingsError(null);
    try {
      const capabilities: Record<string, unknown> = { ...selectedAdminSettingsModel.capabilities, context_window: contextWindow };
      delete capabilities.contextWindow;
      const updated = await api.adminProviders.updateModel(adminSettingsProviderId, selectedAdminSettingsModel.modelKey, capabilities);
      setAdminSettingsModels((models) => models.map((model) => model.modelKey === updated.modelKey ? updated : model));
      showToast(`${updated.displayName} 최대 토큰을 저장했습니다.`);
    } catch (error) {
      setAdminSettingsError(error instanceof Error ? error.message : "최대 토큰을 저장하지 못했습니다.");
    } finally {
      setAdminSettingsBusy(false);
    }
  };
  const resetAdminMaxTokens = async () => {
    if (!selectedAdminSettingsModel?.defaultContextWindow) return;
    setAdminSettingsBusy(true);
    setAdminSettingsError(null);
    try {
      const capabilities: Record<string, unknown> = {
        ...selectedAdminSettingsModel.capabilities,
        context_window: selectedAdminSettingsModel.defaultContextWindow,
      };
      delete capabilities.contextWindow;
      const updated = await api.adminProviders.updateModel(adminSettingsProviderId, selectedAdminSettingsModel.modelKey, capabilities);
      setAdminSettingsModels((models) => models.map((model) => model.modelKey === updated.modelKey ? updated : model));
      showToast(`${updated.displayName} 최대 토큰을 기본값으로 초기화했습니다.`);
    } catch (error) {
      setAdminSettingsError(error instanceof Error ? error.message : "최대 토큰을 초기화하지 못했습니다.");
    } finally {
      setAdminSettingsBusy(false);
    }
  };
  const candidateModelOptions = accountProviders.flatMap((provider) =>
    (workspace.providerModels[provider.id] ?? [])
      .filter((model) => workspace.settings?.modelCandidates[provider.id]?.includes(model.modelKey))
      .map((model) => ({
        id: `${provider.id}:${model.modelKey}`,
        label: `${model.displayName} · ${provider.displayName}`,
        triggerLabel: model.displayName,
        providerId: provider.id,
        modelKey: model.modelKey,
      })),
  );
  const selectedCandidateId = candidateModelOptions.find((option) =>
    option.providerId === workspace.settings?.execution.providerId
      && option.modelKey === workspace.settings?.execution.modelKey,
  )?.id ?? "";

  const hideModelNameTooltip = () => {
    if (modelNameTooltipTimerRef.current !== null) {
      window.clearTimeout(modelNameTooltipTimerRef.current);
      modelNameTooltipTimerRef.current = null;
    }
    setModelNameTooltip(null);
  };

  const scheduleModelNameTooltip = (event: ReactMouseEvent<HTMLButtonElement>, name: string) => {
    hideModelNameTooltip();
    const label = event.currentTarget.querySelector<HTMLElement>(".account-model-name");
    if (!label || label.scrollWidth <= label.clientWidth) return;
    const rect = label.getBoundingClientRect();
    modelNameTooltipTimerRef.current = window.setTimeout(() => {
      setModelNameTooltip({
        name,
        left: Math.max(8, Math.min(rect.left, window.innerWidth - 368)),
        top: rect.bottom + 5,
      });
      modelNameTooltipTimerRef.current = null;
    }, 900);
  };
  const completedProjectLearningRunId = [...activeRuntime.turnSets]
    .reverse()
    .find((turnSet) => turnSet.runId && activeRuntime.snapshots[turnSet.runId]?.status === "completed")
    ?.runId ?? null;
  const canReviewProjectLearning = Boolean(
    isAdmin || activeProject?.role === "owner" || activeProject?.role === "admin",
  );
  const progress = activeRun ? derivedProgress(activeRun) : [];
  const latestProgressSummary = activeRun
    ? [...activeRun.activities].reverse().find((activity) => activity.type === "progress_summary")
    : undefined;
  const retryableStepIds = new Set(activeRun?.plan?.steps.filter((step) => step.status === "failed").map((step) => step.id) ?? []);
  const runCanPause = Boolean(activeRun && !["paused", "awaiting_approval", "completed", "failed", "cancelled", "limit_reached", "interrupted"].includes(activeRun.status));
  const runCanCancel = Boolean(activeRun && !["completed", "failed", "cancelled", "limit_reached", "interrupted"].includes(activeRun.status));
  const runIsPaused = activeRun?.status === "paused";
  const conversationFollow = useConversationAutoFollow(
    Boolean(activeRun && !["completed", "failed", "cancelled", "limit_reached", "interrupted"].includes(activeRun.status)),
    workspace.activeConversationId,
  );
  useEffect(() => {
    setOpenCalls(new Set());
  }, [activeRun?.runId]);
  const effortOptions = workspace.selectedModel?.capabilities.effortOptions ?? [];
  const artifactHasTextSource = artifactVersion?.sourceText !== null && artifactVersion?.sourceText !== undefined;
  const artifactIsCurrentVersion = Boolean(artifactSummary && artifactVersion && artifactVersion.version === artifactSummary.currentVersion);
  const artifactVersionOptions = artifactSummary
    ? [...new Set(artifactSummary.versions?.length ? artifactSummary.versions : [artifactSummary.currentVersion])].sort((left, right) => right - left)
    : [];
  const artifactPreviewUrl = artifactVersion?.previewUrl
    ?? (artifactSummary && artifactVersion?.mimeType === "application/pdf"
      ? `/api/artifacts/${encodeURIComponent(artifactSummary.id)}/preview?version=${encodeURIComponent(String(artifactVersion.version))}`
      : null);
  const sharedViewerToken = sharedTokenFromPath(window.location.pathname);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const dock = dockAreaRef.current;
    const pane = dock?.parentElement;
    if (!dock || !pane) return;
    const updateDockHeight = () => pane.style.setProperty("--dock-height", `${Math.ceil(dock.getBoundingClientRect().height)}px`);
    updateDockHeight();
    const observer = new ResizeObserver(updateDockHeight);
    observer.observe(dock);
    return () => {
      observer.disconnect();
      pane.style.removeProperty("--dock-height");
    };
  }, []);

  useEffect(() => {
    if (!workspace.notice) return;
    setToast(workspace.notice);
    workspace.clearNotice();
  }, [workspace.clearNotice, workspace.notice]);

  useEffect(() => {
    if (!workspace.authSession) {
      setNotificationOpen(false);
      setNotifications([]);
      setNotificationUnreadCount(0);
      setNotificationError(null);
      return;
    }
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const count = await api.notifications.getUnreadCount(controller.signal);
        if (controller.signal.aborted) return;
        setNotificationUnreadCount(count.unreadCount);
        if (notificationOpen) {
          setNotificationLoading(true);
          const page = await api.notifications.list(false, 50, 0, controller.signal);
          if (controller.signal.aborted) return;
          setNotifications(page.items);
          setNotificationUnreadCount(page.unreadCount);
          setNotificationError(null);
        }
      } catch (error) {
        if (!controller.signal.aborted && notificationOpen) {
          setNotificationError(error instanceof Error ? error.message : "알림을 불러오지 못했습니다.");
        }
      } finally {
        if (!controller.signal.aborted) setNotificationLoading(false);
      }
    };
    const onFocus = () => void refresh();
    void refresh();
    const interval = window.setInterval(() => void refresh(), 30_000);
    window.addEventListener("focus", onFocus);
    return () => {
      controller.abort();
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [notificationOpen, workspace.authSession?.user.id]);

  useEffect(() => {
    if (!notificationOpen) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!notificationMenuRef.current?.contains(event.target as Node)) {
        setNotificationOpen(false);
      }
    };
    window.addEventListener("pointerdown", closeOnOutsideClick);
    return () => window.removeEventListener("pointerdown", closeOnOutsideClick);
  }, [notificationOpen]);

  useEffect(() => {
    if (!notificationOpen) setNotificationDeleteArmedId(null);
  }, [notificationOpen]);

  useEffect(() => {
    const projectId = workspace.activeProjectId;
    const trigger = composerTrigger?.trigger;
    if (!projectId || !trigger) {
      setComposerSuggestions([]);
      setSuggestionsLoading(false);
      return;
    }
    const controller = new AbortController();
    const rawQuery = composerTrigger?.query ?? "";
    const qualifier = rawQuery.match(/^(skill|mcp):/i)?.[1]?.toLowerCase();
    const query = rawQuery.replace(/^(?:skill|mcp):/i, "");
    setSuggestionsLoading(true);
    const timer = window.setTimeout(() => {
      api.composer.listSuggestions(projectId, trigger, query, controller.signal)
        .then((page) => {
          setComposerSuggestions(qualifier ? page.items.filter((item) => item.kind === qualifier) : page.items);
          setSuggestionIndex(0);
        })
        .catch((error) => {
          if (!controller.signal.aborted) showToast(error instanceof Error ? error.message : "후보를 불러오지 못했습니다.");
        })
        .finally(() => {
          if (!controller.signal.aborted) setSuggestionsLoading(false);
        });
    }, 120);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [composerTrigger?.query, composerTrigger?.trigger, workspace.activeProjectId]);

  useEffect(() => {
    const previousConversationId = previousConversationRef.current;
    const preservePendingComposer = previousConversationId === null && workspace.activeConversationId !== null;
    previousConversationRef.current = workspace.activeConversationId;
    setSessionTitleEditing(false);
    setSessionMenuId(null);
    setMoveMenuId(null);
    setOpenCalls(new Set());
    if (!preservePendingComposer) {
      setDraft("");
      setSelectedReferences([]);
      setComposerTrigger(null);
      setComposerSuggestions([]);
    }
  }, [workspace.activeConversationId]);

  useEffect(() => {
    if (!accountMenuOpen) {
      setProviderMenuOpen(false);
      setProviderModelMenuId(null);
      setModelNameTooltip(null);
      if (modelNameTooltipTimerRef.current !== null) {
        window.clearTimeout(modelNameTooltipTimerRef.current);
        modelNameTooltipTimerRef.current = null;
      }
    }
  }, [accountMenuOpen]);

  useEffect(() => () => {
    if (modelNameTooltipTimerRef.current !== null) {
      window.clearTimeout(modelNameTooltipTimerRef.current);
    }
  }, []);

  useEffect(() => {
    setSessionDeleteArmedId(null);
  }, [sessionMenuId]);

  useEffect(() => {
    setBulkSessionDeleteArmed(false);
  }, [bulkSessionIds, bulkSessionMode]);

  const startNewConversation = useCallback(async () => {
    setMainView("chat");
    setSidebarOpen(false);
    await workspace.createConversation();
    window.requestAnimationFrame(() => composerInputRef.current?.focus());
  }, [workspace.createConversation]);

  const openAdmin = useCallback(() => {
    setMainView("admin");
    setAccountMenuOpen(false);
    setSidebarOpen(false);
  }, []);

  const openSettings = useCallback(() => {
    setMainView("settings");
    setAccountMenuOpen(false);
    setSidebarOpen(false);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.repeat && (event.ctrlKey || event.metaKey) && event.shiftKey && !event.altKey && event.code === "KeyF") {
        event.preventDefault();
        setConversationSearchOpen((open) => !open);
        return;
      }
      if (!event.repeat && (event.ctrlKey || event.metaKey) && event.shiftKey && !event.altKey && event.code === "KeyT") {
        event.preventDefault();
        void workspace.toggleTheme();
        return;
      }
      if (!event.repeat && (event.ctrlKey || event.metaKey) && event.shiftKey && !event.altKey && event.code === "KeyO") {
        event.preventDefault();
        startNewConversation();
        return;
      }
      if (!event.repeat && (event.ctrlKey || event.metaKey) && event.shiftKey && !event.altKey && event.code === "KeyS") {
        event.preventDefault();
        openSettings();
        return;
      }
      if (!event.repeat && isAdmin && (event.ctrlKey || event.metaKey) && event.shiftKey && !event.altKey && event.code === "KeyX") {
        event.preventDefault();
        openAdmin();
        return;
      }
      if (event.key !== "Escape") return;
      if (artifactSaveBusy) return;
      if (notificationOpen) setNotificationOpen(false);
      else if (conversationSearchOpen) setConversationSearchOpen(false);
      else if (sessionTitleEditing) setSessionTitleEditing(false);
      else if (artifactEditing) setArtifactEditing(false);
      else if (sessionMenuId) setSessionMenuId(null);
      else if (providerModelMenuId) setProviderModelMenuId(null);
      else if (providerMenuOpen) setProviderMenuOpen(false);
      else if (accountMenuOpen) setAccountMenuOpen(false);
      else if (artifactFullscreen) setArtifactFullscreen(false);
      else if (artifactOpen) closeArtifact();
      else if (sidebarOpen) setSidebarOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [accountMenuOpen, artifactEditing, artifactFullscreen, artifactOpen, artifactSaveBusy, closeArtifact, conversationSearchOpen, isAdmin, notificationOpen, openAdmin, openSettings, providerMenuOpen, providerModelMenuId, sessionMenuId, sessionTitleEditing, sidebarOpen, startNewConversation, workspace.toggleTheme]);

  const showToast = useCallback((message: string) => setToast(message), []);

  const finishBulkSessionAction = (succeeded: string[]) => {
    const remaining = new Set([...bulkSessionIds].filter((id) => !succeeded.includes(id)));
    setBulkSessionIds(remaining);
    if (remaining.size === 0) {
      setBulkSessionMode(false);
      setBulkMoveOpen(false);
    }
  };

  const moveSelectedSessions = async (projectId: string) => {
    const ids = [...bulkSessionIds];
    if (!ids.length || bulkSessionBusy) return;
    setBulkSessionBusy(true);
    try {
      const succeeded = await workspace.moveConversations(ids, projectId);
      finishBulkSessionAction(succeeded);
    } finally {
      setBulkSessionBusy(false);
    }
  };

  const deleteSelectedSessions = async () => {
    const ids = [...bulkSessionIds];
    if (!ids.length || bulkSessionBusy) return;
    if (!bulkSessionDeleteArmed) {
      setBulkSessionDeleteArmed(true);
      return;
    }
    setBulkSessionBusy(true);
    try {
      const succeeded = await workspace.deleteConversations(ids);
      finishBulkSessionAction(succeeded);
    } finally {
      setBulkSessionBusy(false);
      setBulkSessionDeleteArmed(false);
    }
  };

  const deleteSessionFromMenu = async (conversationId: string) => {
    if (sessionDeleteBusyId) return;
    if (sessionDeleteArmedId !== conversationId) {
      setSessionDeleteArmedId(conversationId);
      return;
    }
    setSessionDeleteBusyId(conversationId);
    try {
      const deleted = await workspace.deleteConversation(conversationId);
      if (deleted) setSessionMenuId(null);
    } finally {
      setSessionDeleteBusyId(null);
      setSessionDeleteArmedId(null);
    }
  };
  const composerSuggestionDisabled = (suggestion: ComposerSuggestion) => {
    const attached = suggestion.kind === "file" && workspace.composerAttachments.some((item) => item.id === suggestion.id);
    const referenceId = suggestion.referenceId ?? suggestion.id;
    const key = `${suggestion.kind}:${referenceId}:${suggestion.versionOrDigest ?? ""}`;
    return suggestion.status !== undefined && suggestion.status !== "available" || attached || selectedReferences.some((item) => item.key === key);
  };
  const toggleSetItem = (setter: React.Dispatch<React.SetStateAction<Set<string>>>, id: string) => {
    setter((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const updateDraft = (value: string, caret: number) => {
    setDraft(value);
    setSelectedReferences((current) => current.filter((item) => value.includes(item.token)));
    setComposerTrigger(findComposerTrigger(value, caret));
  };

  const applyStarterPrompt = (prompt: string) => {
    updateDraft(prompt, prompt.length);
    window.requestAnimationFrame(() => {
      composerInputRef.current?.focus();
      composerInputRef.current?.setSelectionRange(prompt.length, prompt.length);
    });
  };

  const selectComposerSuggestion = (suggestion: ComposerSuggestion) => {
    if (!composerTrigger) return;
    if (composerSuggestionDisabled(suggestion)) {
      showToast(suggestion.kind === "file" ? "이미 첨부하거나 연결한 파일입니다." : "이미 연결한 항목입니다.");
      return;
    }
    const referenceId = suggestion.referenceId ?? suggestion.id;
    const key = `${suggestion.kind}:${referenceId}:${suggestion.versionOrDigest ?? ""}`;
    const token = suggestion.insertText ?? `${composerTrigger.trigger}${suggestion.name}`;
    const before = draft.slice(0, composerTrigger.start);
    const after = draft.slice(composerTrigger.end);
    const separator = after.startsWith(" ") ? "" : " ";
    const nextDraft = `${before}${token}${separator}${after}`;
    setDraft(nextDraft);
    setSelectedReferences((current) => [
      ...current,
      {
        key,
        token,
        name: suggestion.name,
        subtitle: suggestion.subtitle,
        reference: {
          kind: suggestion.kind,
          referenceId,
          versionOrDigest: suggestion.versionOrDigest,
          displaySnapshot: suggestion.displaySnapshot,
        },
      },
    ]);
    setComposerTrigger(null);
    setComposerSuggestions([]);
    window.requestAnimationFrame(() => {
      const input = composerInputRef.current;
      if (!input) return;
      const caret = before.length + token.length + separator.length;
      input.focus();
      input.setSelectionRange(caret, caret);
    });
  };

  const removeComposerReference = (key: string) => {
    const target = selectedReferences.find((item) => item.key === key);
    if (!target) return;
    setSelectedReferences((current) => current.filter((item) => item.key !== key));
    setDraft((current) => current.replace(target.token, "").replace(/ {2,}/g, " "));
    composerInputRef.current?.focus();
  };

  const insertComposerTrigger = (trigger: "@" | "$") => {
    const input = composerInputRef.current;
    const caret = input?.selectionStart ?? draft.length;
    const prefix = caret > 0 && !/\s/.test(draft.charAt(caret - 1)) ? ` ${trigger}` : trigger;
    const nextDraft = `${draft.slice(0, caret)}${prefix}${draft.slice(caret)}`;
    const nextCaret = caret + prefix.length;
    setDraft(nextDraft);
    setComposerTrigger({ trigger, query: "", start: nextCaret - 1, end: nextCaret });
    window.requestAnimationFrame(() => {
      input?.focus();
      input?.setSelectionRange(nextCaret, nextCaret);
    });
  };

  const moveSuggestionIndex = (direction: 1 | -1) => {
    if (!composerSuggestions.length) return;
    setSuggestionIndex((current) => {
      for (let offset = 1; offset <= composerSuggestions.length; offset += 1) {
        const candidate = (current + direction * offset + composerSuggestions.length) % composerSuggestions.length;
        if (!composerSuggestionDisabled(composerSuggestions[candidate])) return candidate;
      }
      return current;
    });
  };

  const beginSessionTitleEdit = (conversationId = workspace.activeConversationId) => {
    const target = workspace.conversations.find((conversation) => conversation.id === conversationId);
    if (!target) return;
    workspace.selectConversation(target.id);
    setSessionTitleDraft(target.title);
    setSessionTitleEditing(true);
    setSessionMenuId(null);
    setSidebarOpen(false);
  };

  const commitSessionTitle = async () => {
    if (titleCommitRef.current || !workspace.activeConversation) return;
    const nextTitle = sessionTitleDraft.trim();
    setSessionTitleEditing(false);
    if (!nextTitle) {
      showToast("세션명은 비워둘 수 없습니다.");
      return;
    }
    titleCommitRef.current = true;
    const updated = await workspace.renameConversation(workspace.activeConversation.id, nextTitle);
    titleCommitRef.current = false;
    if (updated) showToast("세션명을 변경했습니다.");
  };

  const sendMessage = async (queueNext = false) => {
    const value = draft.trim() || (workspace.composerAttachments.length > 0 ? "첨부한 내용을 확인해 주세요." : "");
    if (!value) {
      showToast("요청 내용을 입력해 주세요.");
      return;
    }
    const promptReferences = selectedReferences.flatMap(({ reference, token }) => {
      const tokenStart = value.indexOf(token);
      if (tokenStart < 0) return [];
      return [{ ...reference, tokenStart, tokenEnd: tokenStart + token.length }];
    });
    const mode = await workspace.sendMessage(value, queueNext, promptReferences);
    if (!mode) return;
    setDraft("");
    setSelectedReferences([]);
    setComposerTrigger(null);
    setComposerSuggestions([]);
    showToast(mode === "queue_next" ? "다음 요청으로 대기열에 추가했습니다." : mode === "steer" ? "현재 Run에 반영할 지시를 접수했습니다." : "새 Run을 시작했습니다.");
  };

  const controlRun = async (action: RunControlAction, targetId?: string) => {
    if (!activeRun) return;
    const succeeded = await workspace.runAction(activeRun.runId, action, targetId);
    if (!succeeded) return;
    showToast(action === "pause" ? "Run을 일시 정지했습니다." : action === "resume" ? "Run을 재개했습니다." : action === "cancel" ? "Run을 취소했습니다." : action === "approve" ? "위험 작업을 승인했습니다." : action === "reject" ? "위험 작업을 거부했습니다." : "실패한 단계를 다시 실행합니다.");
  };

  const copyTool = async (execution: ToolExecution) => {
    const requestText = execution.input
      ? JSON.stringify(execution.input, null, 2)
      : execution.inputSummary.join("\n") || "입력 없음";
    const resultText = execution.result
      ? JSON.stringify(execution.result, null, 2)
      : execution.error || execution.resultSummary.join("\n") || "결과 없음";
    try {
      await navigator.clipboard.writeText([`[${execution.toolName}]`, "", "도구 요청", requestText, "", "도구 결과", resultText].join("\n"));
      showToast("전체 Tool 로그를 복사했습니다.");
    } catch {
      showToast("Tool 메시지를 복사하지 못했습니다.");
    }
  };

  const openArtifact = async (artifact: ArtifactSummary) => {
    if (artifactSaveBusy) {
      showToast("Artifact 저장이 끝난 뒤 다른 문서를 열어 주세요.");
      return;
    }
    if (!artifactOpen && !artifactHistoryOpenRef.current) {
      window.history.pushState({ ...window.history.state, luminaArtifactPanel: true }, "");
      artifactHistoryOpenRef.current = true;
    }
    const requestId = artifactOpenRequestRef.current + 1;
    artifactOpenRequestRef.current = requestId;
    setArtifactOpen(true);
    setArtifactLoading(true);
    setArtifactSummary(artifact);
    setArtifactVersion(null);
    setArtifactTab("preview");
    setArtifactEditing(false);
    setArtifactDraft("");
    setArtifactDraftSaved(false);
    setArtifactDraftStale(false);
    setArtifactDraftNotice(null);
    setArtifactEditablePreview("");
    setArtifactAiComments([]);
    setArtifactAiStatus(null);
    setArtifactDraftEtag(undefined);
    try {
      const summary = await api.artifacts.get(artifact.id);
      const [version, savedDraft] = await Promise.all([
        api.artifacts.getVersion(artifact.id, summary.currentVersion),
        api.artifacts.getDraft(artifact.id),
      ]);
      if (artifactOpenRequestRef.current !== requestId) return;
      setArtifactSummary(summary);
      setArtifactVersion(version);
      if (savedDraft && !savedDraft.stale && savedDraft.baseVersion === version.version) {
        setArtifactDraft(savedDraft.content);
        setArtifactDraftEtag(savedDraft.etag);
        setArtifactDraftSaved(true);
        setArtifactDraftNotice("저장된 편집 초안이 있습니다. 본문 수정을 누르면 이어서 편집할 수 있습니다.");
      } else {
        setArtifactDraft(version.sourceText ?? "");
        if (savedDraft?.stale) {
          setArtifactDraftStale(true);
          setArtifactDraftNotice("이전 버전 기준 초안이 있어 최신 저장본을 표시합니다. 초안 덮어쓰기는 차단됩니다.");
        }
      }
    } catch (error) {
      if (artifactOpenRequestRef.current === requestId) {
        showToast(error instanceof Error ? error.message : "Artifact를 열지 못했습니다.");
      }
    } finally {
      if (artifactOpenRequestRef.current === requestId) setArtifactLoading(false);
    }
  };

  const saveArtifactDraft = async () => {
    if (!artifactSummary || !artifactVersion || artifactVersion.sourceText === null || !artifactIsCurrentVersion || artifactSaveBusy) return;
    setArtifactSaveBusy("draft");
    try {
      const saved = await api.artifacts.saveDraft(
        artifactSummary.id,
        artifactVersion.version,
        artifactDraft,
        artifactDraftEtag,
      );
      setArtifactDraftEtag(saved.etag);
      setArtifactDraftSaved(true);
      setArtifactDraftStale(false);
      setArtifactDraftNotice("편집 초안을 서버에 저장했습니다.");
      showToast("편집 초안을 서버에 저장했습니다.");
    } catch (error) {
      if (error instanceof ApiError && ["draft_conflict", "artifact_draft_stale", "artifact_version_conflict"].includes(error.code)) {
        setArtifactDraftStale(true);
        setArtifactDraftNotice("서버의 초안 또는 기준 버전이 변경되었습니다. Artifact를 다시 열어 최신 상태를 확인해 주세요.");
      }
      showToast(error instanceof Error ? error.message : "초안을 저장하지 못했습니다.");
    } finally {
      setArtifactSaveBusy(null);
    }
  };

  const submitArtifactAiEdit = async () => {
    if (!artifactSummary || !artifactVersion || artifactAiComments.length === 0 || artifactAiSubmitting) return;
    const numberedComments = artifactAiComments.map((comment, index) => [
      comment.scope === "document"
        ? `${index + 1}. 적용 범위: 전체 문서`
        : `${index + 1}. 선택 위치: ${JSON.stringify(comment.text)}`,
      `   앞 문맥: ${JSON.stringify(comment.before)}`,
      `   뒤 문맥: ${JSON.stringify(comment.after)}`,
      `   수정 의견: ${comment.instruction}`,
    ].join("\n")).join("\n");
    const prompt = [
      `Artifact ${artifactSummary.displayName}의 v${artifactVersion.version}을 다음 위치별 의견에 따라 수정해 주세요.`,
      `source artifact_id: ${artifactSummary.id}`,
      `source version: ${artifactVersion.version}`,
      "원본 version은 절대 덮어쓰지 말고, 수정 결과를 정확히 하나의 새 immutable Artifact version으로 저장해 주세요.",
      "선택 위치는 선택 텍스트와 앞뒤 문맥을 함께 재검증하고, 위치가 달라졌다면 임의 적용하지 말고 알려 주세요.",
      "",
      numberedComments,
    ].join("\n");
    setArtifactAiSubmitting(true);
    setArtifactAiStatus("AI 수정 요청을 중앙 Agent Run으로 전달하고 있습니다.");
    const hasActiveRun = Boolean(activeRun && !["completed", "failed", "cancelled", "limit_reached", "interrupted"].includes(activeRun.status));
    const mode = await workspace.sendMessage(prompt, hasActiveRun, [{
      kind: "artifact",
      referenceId: artifactSummary.id,
      versionOrDigest: String(artifactVersion.version),
      displaySnapshot: { displayName: artifactSummary.displayName, version: artifactVersion.version },
    }]);
    setArtifactAiSubmitting(false);
    if (!mode) {
      setArtifactAiStatus("AI 수정 요청을 전달하지 못했습니다. 의견은 그대로 보존했습니다.");
      return;
    }
    setArtifactAiStatus(mode === "queue_next" ? "AI 수정 요청이 다음 Run으로 대기 중입니다." : "AI 수정 요청이 Agent Run에서 진행 중입니다.");
  };

  const saveArtifactVersion = async () => {
    if (!artifactSummary || !artifactVersion || artifactVersion.sourceText === null || !artifactIsCurrentVersion || artifactSaveBusy) return;
    setArtifactSaveBusy("version");
    try {
      const cleanupDraftEtag = artifactDraftSaved ? artifactDraftEtag : undefined;
      const version = await api.artifacts.saveVersion(
        artifactSummary.id,
        {
          baseVersion: artifactVersion.version,
          sourceText: artifactDraft,
          changeSummary: "Artifact 패널에서 직접 편집",
          idempotencyKey: crypto.randomUUID(),
        },
        artifactVersion.etag,
        cleanupDraftEtag,
      );
      setArtifactVersion(version);
      setArtifactSummary((current) => current ? {
        ...current,
        currentVersion: version.version,
        size: version.size,
        updatedAt: version.createdAt,
        versions: [version.version, ...(current.versions ?? [])].filter((item, index, items) => items.indexOf(item) === index),
      } : current);
      setArtifactEditing(false);
      setArtifactAiComments([]);
      setArtifactAiStatus(null);
      setArtifactDraftSaved(false);
      if (cleanupDraftEtag) {
        setArtifactDraftEtag(undefined);
        setArtifactDraftStale(false);
        setArtifactDraftNotice(null);
      } else if (artifactDraftEtag) {
        setArtifactDraftStale(true);
        setArtifactDraftNotice("서버의 다른 편집 초안은 보존되었으며 이제 이전 버전을 기준으로 합니다.");
      }
      showToast(`Artifact v${version.version}을 저장했습니다.`);
    } catch (error) {
      if (error instanceof ApiError && ["artifact_etag_conflict", "artifact_version_conflict"].includes(error.code)) {
        setArtifactDraftStale(true);
        setArtifactDraftNotice("Artifact 기준 버전이 다른 곳에서 변경되었습니다. 다시 열어 최신 버전에서 편집해 주세요.");
      }
      showToast(error instanceof Error ? error.message : "새 버전을 저장하지 못했습니다.");
    } finally {
      setArtifactSaveBusy(null);
    }
  };

  const selectArtifactVersion = async (versionNumber: number) => {
    if (!artifactSummary || artifactEditing || artifactSaveBusy || artifactVersion?.version === versionNumber) return;
    const requestId = artifactOpenRequestRef.current + 1;
    artifactOpenRequestRef.current = requestId;
    setArtifactLoading(true);
    setArtifactVersion(null);
    setArtifactDraft("");
    setArtifactDraftEtag(undefined);
    setArtifactDraftSaved(false);
    setArtifactDraftStale(false);
    setArtifactDraftNotice(null);
    try {
      const [version, savedDraft] = await Promise.all([
        api.artifacts.getVersion(artifactSummary.id, versionNumber),
        versionNumber === artifactSummary.currentVersion
          ? api.artifacts.getDraft(artifactSummary.id)
          : Promise.resolve(null),
      ]);
      if (artifactOpenRequestRef.current !== requestId) return;
      setArtifactVersion(version);
      if (savedDraft && !savedDraft.stale && savedDraft.baseVersion === version.version) {
        setArtifactDraft(savedDraft.content);
        setArtifactDraftEtag(savedDraft.etag);
        setArtifactDraftSaved(true);
        setArtifactDraftNotice("저장된 편집 초안이 있습니다. 본문 수정을 누르면 이어서 편집할 수 있습니다.");
      } else {
        setArtifactDraft(version.sourceText ?? "");
        if (savedDraft?.stale) {
          setArtifactDraftStale(true);
          setArtifactDraftNotice("이전 버전 기준 초안이 있어 최신 저장본을 표시합니다. 초안 덮어쓰기는 차단됩니다.");
        }
      }
    } catch (error) {
      if (artifactOpenRequestRef.current === requestId) {
        showToast(error instanceof Error ? error.message : "Artifact 버전을 불러오지 못했습니다.");
      }
    } finally {
      if (artifactOpenRequestRef.current === requestId) setArtifactLoading(false);
    }
  };

  const downloadArtifact = async () => {
    if (!artifactSummary || !artifactVersion) return;
    try {
      const download = await api.artifacts.downloadVersion(artifactSummary.id, artifactVersion.version);
      const url = URL.createObjectURL(download.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = download.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
      showToast("Artifact 다운로드를 시작했습니다.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "다운로드하지 못했습니다.");
    }
  };

  const shareArtifact = async () => {
    if (!artifactSummary?.conversationId) return;
    try {
      const share = await api.sharing.create(artifactSummary.conversationId);
      const url = new URL(share.viewerPath, window.location.origin);
      url.searchParams.set("theme", theme);
      await navigator.clipboard.writeText(url.toString());
      showToast("Artifact 공유 링크를 복사했습니다.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "공유 링크를 만들지 못했습니다.");
    }
  };

  const markAllNotificationsRead = async () => {
    if (notificationBusyId || notificationUnreadCount === 0) return;
    setNotificationBusyId("all");
    try {
      const result = await api.notifications.markAllRead();
      setNotifications((items) => items.map((item) => item.readAt ? item : { ...item, readAt: result.readAt }));
      setNotificationUnreadCount(0);
      showToast("모든 알림을 읽음으로 표시했습니다.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "알림 상태를 변경하지 못했습니다.");
    } finally {
      setNotificationBusyId(null);
    }
  };

  const deleteOneNotification = async (notification: NotificationItem) => {
    if (notificationBusyId) return;
    if (notificationDeleteArmedId !== notification.id) {
      setNotificationDeleteArmedId(notification.id);
      return;
    }
    setNotificationBusyId(notification.id);
    try {
      await api.notifications.delete(notification.id);
      setNotifications((items) => items.filter((item) => item.id !== notification.id));
      if (!notification.readAt) setNotificationUnreadCount((count) => Math.max(0, count - 1));
      setNotificationDeleteArmedId(null);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "알림을 삭제하지 못했습니다.");
    } finally {
      setNotificationBusyId(null);
    }
  };

  const deleteAllNotifications = async () => {
    if (notificationBusyId || notifications.length === 0) return;
    if (notificationDeleteArmedId !== "all") {
      setNotificationDeleteArmedId("all");
      return;
    }
    setNotificationBusyId("delete-all");
    try {
      await api.notifications.deleteAll();
      setNotifications([]);
      setNotificationUnreadCount(0);
      setNotificationDeleteArmedId(null);
      showToast("알림을 모두 삭제했습니다.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "알림을 삭제하지 못했습니다.");
    } finally {
      setNotificationBusyId(null);
    }
  };

  const openNotificationTarget = async (notification: NotificationItem) => {
    if (notificationBusyId) return;
    setNotificationBusyId(notification.id);
    setNotificationOpen(false);
    if (!notification.readAt) {
      try {
        const updated = await api.notifications.markRead(notification.id);
        setNotifications((items) => items.map((item) => item.id === updated.id ? updated : item));
        setNotificationUnreadCount((count) => Math.max(0, count - 1));
      } catch {
        showToast("읽음 상태를 동기화하지 못했지만 연결된 화면으로 이동합니다.");
      }
    }

    const { projectId, conversationId, runId, artifactId } = notification.deepLink;
    const projectAvailable = !projectId || workspace.projects.some((project) => project.id === projectId);
    let openedTarget = false;
    let partialFailure = !projectAvailable;

    if (projectAvailable && conversationId) {
      try {
        const cached = workspace.conversations.find((conversation) => conversation.id === conversationId);
        const conversation = cached ?? (await api.conversations.list({ projectId, limit: 100 })).items.find((item) => item.id === conversationId);
        if (!conversation) throw new Error("conversation_not_found");
        workspace.openConversation(conversation);
        setMainView("chat");
        await workspace.loadConversation(conversation.id, true);
        openedTarget = true;
        if (runId) {
          window.setTimeout(() => {
            const target = Array.from(document.querySelectorAll<HTMLElement>("[data-run-id]"))
              .find((element) => element.dataset.runId === runId);
            target?.scrollIntoView({ behavior: "smooth", block: "center" });
          }, 120);
        }
      } catch {
        partialFailure = true;
      }
    } else if (projectAvailable && projectId) {
      workspace.setActiveProjectId(projectId);
      setMainView("chat");
      openedTarget = true;
    }

    if (artifactId) {
      try {
        const artifact = await api.artifacts.get(artifactId);
        if (!workspace.projects.some((project) => project.id === artifact.projectId)) {
          throw new Error("artifact_project_unavailable");
        }
        if (!conversationId && artifact.projectId !== workspace.activeProjectId) {
          workspace.setActiveProjectId(artifact.projectId);
        }
        await openArtifact(artifact);
        openedTarget = true;
      } catch {
        partialFailure = true;
      }
    }

    if (!openedTarget) {
      showToast("알림 대상이 삭제되었거나 접근 권한이 없습니다.");
    } else if (partialFailure) {
      showToast("연결된 일부 대상은 삭제되었거나 접근 권한이 없습니다.");
    }
    setNotificationBusyId(null);
  };

  if (workspace.authSession === undefined) {
    return <div className="app-boot"><Sparkles size={22} /><span>Lumina를 준비하고 있습니다.</span><LoaderCircle className="is-running" size={18} /></div>;
  }
  if (workspace.authSession === null) {
    return (
      <>
        <LoginScreen onAuthenticated={workspace.onAuthenticated} />
        {workspace.bootError && <div className="toast is-error" role="alert">{workspace.bootError}</div>}
      </>
    );
  }
  const streamLabel = activeRuntime.streamState === "reconnecting"
    ? "재연결 중"
    : activeRuntime.streamState === "connecting"
      ? "연결 중"
      : "Online";

  return (
    <div
      className={`app-shell ${artifactOpen ? "has-artifact" : ""} ${sidebarCollapsed ? "is-sidebar-collapsed" : ""} ${artifactResizing ? "is-artifact-resizing" : ""} ${theme === "dark" ? "theme-dark" : ""}`}
      style={{ "--artifact-pane-width": `${artifactPaneWidth}px` } as CSSProperties}
      onClick={() => {
        setSessionMenuId(null);
        setMoveMenuId(null);
        setAccountMenuOpen(false);
        setProjectMenuOpen(false);
      }}
    >
      <button className={`sidebar-backdrop ${sidebarOpen ? "is-visible" : ""}`} type="button" aria-label="사이드바 닫기" onClick={() => setSidebarOpen(false)} />
      <aside className={`sidebar ${sidebarOpen ? "is-open" : ""} ${sidebarCollapsed ? "is-collapsed" : ""}`} aria-label="Lumina 탐색">
        <nav className="sidebar-collapsed-navigation" aria-label="축소된 Lumina 탐색">
          <button type="button" aria-label="사이드바 펼치기" title="사이드바 펼치기" onClick={() => { sidebarAutoCollapsedRef.current = false; setSidebarCollapsed(false); }}><PanelLeftOpen size={17} /></button>
          <button type="button" aria-label="새 채팅" title="새 채팅" onClick={startNewConversation}><SquarePen size={18} /></button>
          {navigation.map(({ id, label, icon: Icon }) => (
            <button className={mainView === id ? "is-active" : ""} type="button" aria-label={label} title={label} key={id} onClick={() => setMainView(id)}><Icon size={18} /></button>
          ))}
        </nav>
        <header className="sidebar-header">
          <a className="wordmark" href="#top" aria-label="Lumina 홈" onClick={() => setMainView("chat")}><Sparkles size={20} strokeWidth={1.7} /><span>Lumina</span></a>
          <div className="sidebar-header-actions">
            <button type="button" aria-label="대화 검색" onClick={() => setConversationSearchOpen(true)}><Search size={17} /></button>
            <button className="tooltip-control" type="button" aria-label={theme === "dark" ? "Light 테마로 변경" : "Dark 테마로 변경"} data-tooltip={theme === "dark" ? "Light 테마" : "Dark 테마"} onClick={() => void workspace.toggleTheme()}>
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <button type="button" aria-label="사이드바 접기" onClick={() => {
              if (window.innerWidth < 1024) setSidebarOpen(false);
              else {
                sidebarAutoCollapsedRef.current = false;
                setSidebarCollapsed(true);
                setAccountMenuOpen(false);
                setProjectMenuOpen(false);
                setSessionMenuId(null);
              }
            }}><PanelLeftClose size={17} /></button>
          </div>
        </header>

        <nav className="primary-navigation" aria-label="주요 메뉴">
          {navigation.map(({ id, label, icon: Icon }) => <button className={mainView === id ? "is-active" : ""} type="button" key={id} onClick={() => {
            setMainView(id);
            setSidebarOpen(false);
          }}><Icon size={17} /> {label}</button>)}
        </nav>

        <div className="sidebar-scroll">
          <section className="sidebar-section">
            <button className="new-task-button" type="button" onClick={startNewConversation}><SquarePen size={17} /> <span>새 채팅</span><kbd aria-hidden="true">Ctrl + Shift + O</kbd></button>
          </section>

          <section className="sidebar-section">
            <div className="sidebar-section-heading project-heading">
              <span>프로젝트</span>
              <button className="tooltip-control" type="button" aria-label="프로젝트 설정" data-tooltip="프로젝트 설정" disabled={!activeProject} onClick={() => { setMainView(mainView === "project-settings" ? "chat" : "project-settings"); setSidebarOpen(false); }}><Settings size={15} /></button>
            </div>
            <div className="project-selector" onClick={(event) => event.stopPropagation()}>
              <button className="project-row is-selected" type="button" aria-haspopup="listbox" aria-expanded={projectMenuOpen} disabled={!activeProject} onClick={() => setProjectMenuOpen((open) => !open)}>
                <Folder size={16} /><span>{activeProject?.name ?? "프로젝트 없음"}</span><ChevronDown className={projectMenuOpen ? "is-open" : ""} size={14} />
              </button>
              {projectMenuOpen && (
                <div className="project-options" role="listbox" aria-label="프로젝트 선택">
                  {workspace.projects.map((project) => (
                    <button type="button" role="option" aria-selected={project.id === workspace.activeProjectId} key={project.id} onClick={() => {
                      workspace.setActiveProjectId(project.id);
                      setMainView("chat");
                      setProjectMenuOpen(false);
                    }}>
                      <Folder size={15} /><span>{project.name}</span>{project.id === workspace.activeProjectId && <Check size={14} />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section className="sidebar-section session-section">
            <div className="sidebar-section-heading session-heading">
              <span>{bulkSessionMode ? `${bulkSessionIds.size}개 선택` : "최근 항목"}</span>
              {bulkSessionMode ? (
                <div className="bulk-session-heading-actions">
                  <button className="tooltip-control" type="button" aria-label="선택한 대화 이동" data-tooltip="이동" disabled={!bulkSessionIds.size || bulkSessionBusy || workspace.projects.length < 2} onClick={() => setBulkMoveOpen((open) => !open)}><FolderInput size={14} /></button>
                  <button className={`tooltip-control is-danger ${bulkSessionDeleteArmed ? "is-armed" : ""}`} type="button" aria-label={bulkSessionDeleteArmed ? "선택한 대화 삭제 확인, 한 번 더 누르면 삭제" : "선택한 대화 삭제"} data-tooltip={bulkSessionDeleteArmed ? "삭제경고" : "삭제"} disabled={!bulkSessionIds.size || bulkSessionBusy} onClick={() => void deleteSelectedSessions()}>{bulkSessionBusy ? <LoaderCircle className="is-running" size={14} /> : bulkSessionDeleteArmed ? <AlertCircle size={14} /> : <Trash2 size={14} />}</button>
                  <button className="bulk-session-select tooltip-control" type="button" aria-label={bulkSessionIds.size === workspace.conversations.length ? "모든 대화 선택 해제" : "모든 대화 선택"} data-tooltip={bulkSessionIds.size === workspace.conversations.length ? "선택 해제" : "전체 선택"} onClick={() => setBulkSessionIds((current) => current.size === workspace.conversations.length ? new Set() : new Set(workspace.conversations.map((item) => item.id)))}><CheckCheck size={14} /></button>
                  <button className="tooltip-control" type="button" aria-label="세션 관리 닫기" data-tooltip="닫기" onClick={() => { setBulkSessionMode(false); setBulkSessionIds(new Set()); setBulkMoveOpen(false); }}><X size={14} /></button>
                  {bulkMoveOpen && (
                    <div className="bulk-session-projects">
                      {workspace.projects.filter((project) => project.id !== workspace.activeProjectId).map((project) => (
                        <button type="button" key={project.id} disabled={bulkSessionBusy} onClick={() => void moveSelectedSessions(project.id)}><Folder size={13} /> {project.name}</button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="session-heading-actions">
                  {workspace.loadingWorkspace && <LoaderCircle className="is-running" size={13} />}
                  <button className="bulk-session-open tooltip-control" type="button" aria-label="세션 관리" data-tooltip="세션 관리" disabled={workspace.conversations.length === 0} onClick={() => { setBulkSessionMode(true); setBulkSessionIds(new Set()); setSessionMenuId(null); setMoveMenuId(null); }}><CheckCheck size={14} /></button>
                </div>
              )}
            </div>
            <div className="session-list">
              {workspace.conversations.map((conversation) => (
                <div className={`session-item ${conversation.id === workspace.activeConversationId && !bulkSessionMode ? "is-selected" : ""} ${bulkSessionMode ? "is-bulk" : ""}`} key={conversation.id}>
                  <button className="session-row" type="button" onClick={() => {
                    if (bulkSessionMode) {
                      setBulkSessionIds((current) => {
                        const next = new Set(current);
                        if (next.has(conversation.id)) next.delete(conversation.id);
                        else next.add(conversation.id);
                        return next;
                      });
                      return;
                    }
                    setSessionTitleEditing(false);
                    setMainView("chat");
                    workspace.selectConversation(conversation.id);
                    setSidebarOpen(false);
                  }} aria-pressed={bulkSessionMode ? bulkSessionIds.has(conversation.id) : undefined}>
                    {bulkSessionMode ? <span className={`bulk-session-checkbox ${bulkSessionIds.has(conversation.id) ? "is-checked" : ""}`}>{bulkSessionIds.has(conversation.id) && <Check size={11} />}</span> : conversation.lastRunStatus === "running" ? <LoaderCircle className="is-running" size={14} /> : conversation.lastRunStatus === "queued" ? <Clock3 size={14} /> : conversation.lastRunStatus === "failed" ? <AlertCircle size={14} /> : conversation.isFavorite ? <Pin className="session-pin" size={14} /> : <MessageCircle size={14} />}
                    <span className={isUntitledConversation(conversation.title) ? "is-untitled" : undefined}>{isUntitledConversation(conversation.title) ? "제목 없음" : conversation.title}</span>
                  </button>
                  {!bulkSessionMode && <button className="session-options-button" type="button" aria-label={`${conversation.title} 옵션`} aria-expanded={sessionMenuId === conversation.id} onClick={(event) => {
                    event.stopPropagation();
                    setAccountMenuOpen(false);
                    setMoveMenuId(null);
                    setSessionMenuId((current) => current === conversation.id ? null : conversation.id);
                  }}><MoreVertical size={15} /></button>}
                  {!bulkSessionMode && sessionMenuId === conversation.id && (
                    <div className="session-options-menu" role="menu" onClick={(event) => event.stopPropagation()}>
                      <button type="button" role="menuitem" onClick={() => { setSessionMenuId(null); void workspace.toggleFavoriteConversation(conversation.id); }}>{conversation.isFavorite ? <PinOff size={14} /> : <Pin size={14} />} {conversation.isFavorite ? "즐겨찾기 해제" : "즐겨찾기"}</button>
                      <button type="button" role="menuitem" onClick={() => beginSessionTitleEdit(conversation.id)}><Pencil size={14} /> 세션명 변경</button>
                      <button type="button" role="menuitem" onClick={() => setMoveMenuId((current) => current === conversation.id ? null : conversation.id)}><FolderInput size={14} /> 프로젝트 변경</button>
                      {moveMenuId === conversation.id && (
                        <div className="session-project-options">
                          {workspace.projects.filter((project) => project.id !== conversation.projectId).map((project) => (
                            <button type="button" key={project.id} onClick={() => void workspace.moveConversation(conversation.id, project.id)}><Folder size={13} /> {project.name}</button>
                          ))}
                          {workspace.projects.length < 2 && <span>이동할 프로젝트가 없습니다.</span>}
                        </div>
                      )}
                      <button className={`is-danger ${sessionDeleteArmedId === conversation.id ? "is-armed" : ""}`} type="button" role="menuitem" disabled={sessionDeleteBusyId === conversation.id} onClick={() => void deleteSessionFromMenu(conversation.id)}>{sessionDeleteBusyId === conversation.id ? <LoaderCircle className="is-running" size={14} /> : sessionDeleteArmedId === conversation.id ? <AlertCircle size={14} /> : <Trash2 size={14} />} {sessionDeleteArmedId === conversation.id ? "한 번 더 눌러 삭제" : "삭제"}</button>
                    </div>
                  )}
                </div>
              ))}
              {!workspace.loadingWorkspace && workspace.conversations.length === 0 && <p className="sidebar-empty">새 채팅을 만들어 시작하세요.</p>}
            </div>
          </section>
        </div>

        <footer className="sidebar-footer" onClick={(event) => event.stopPropagation()}>
          {accountMenuOpen && (
            <div className="account-menu" role="menu" aria-label="계정 설정">
              {isAdmin && <button className="account-menu-admin" type="button" role="menuitem" onClick={openAdmin}><ShieldCheck size={15} /><span><strong>관리자 메뉴</strong></span><kbd aria-hidden="true">Ctrl + Shift + X</kbd></button>}
              <button className="account-menu-shortcut" type="button" role="menuitem" onClick={openSettings}><Settings size={15} /><span><strong>설정</strong></span><kbd aria-hidden="true">Ctrl + Shift + S</kbd></button>
              <div className="account-menu-separator" />
              <button className="account-menu-provider-trigger" type="button" role="menuitem" aria-expanded={providerMenuOpen} onClick={() => setProviderMenuOpen((open) => !open)}>
                <Bot size={15} />
                <span><strong>Provider</strong></span>
                {providerMenuOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
              {providerMenuOpen && (
                <div className="account-provider-list" role="group" aria-label="Provider 목록">
                  {accountProviders.map((provider) => {
                    const providerIsOpen = providerModelMenuId === provider.id;
                    const providerModels = workspace.providerModels[provider.id] ?? [];
                    const providerIsChecked = (workspace.settings?.modelCandidates[provider.id]?.length ?? 0) > 0;
                    return (
                      <div className={`account-provider-group ${provider.connectionStatus === "ready" ? "" : "is-needs-setup"}`} key={provider.id}>
                        <div className="account-provider-row">
                          <button className={`account-provider-checkbox ${providerIsChecked ? "is-checked" : ""}`} type="button" role="checkbox" aria-checked={providerIsChecked} aria-label={`${provider.displayName} 모델 ${providerIsChecked ? "숨기기" : "표시하기"}`} onClick={() => void workspace.setModelCandidates(provider.id, providerIsChecked ? [] : providerModels.map((model) => model.modelKey))}>
                            {providerIsChecked && <Check size={12} strokeWidth={3} />}
                          </button>
                          <button className="account-provider-toggle" type="button" role="menuitem" aria-expanded={providerIsOpen} onClick={() => setProviderModelMenuId((current) => current === provider.id ? null : provider.id)}>
                            <span><strong>{provider.displayName}</strong></span>
                            {providerIsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </button>
                        </div>
                        {providerIsOpen && (
                          <div className="account-model-checklist" role="group" aria-label={`${provider.displayName} 모델 목록`}>
                            {providerModels.map((model) => {
                              const checked = workspace.settings?.modelCandidates[provider.id]?.includes(model.modelKey) ?? false;
                              return (
                                <button type="button" role="menuitemcheckbox" aria-checked={checked} key={model.modelKey} onMouseEnter={(event) => scheduleModelNameTooltip(event, model.displayName)} onMouseLeave={hideModelNameTooltip} onClick={() => { hideModelNameTooltip(); void workspace.toggleModelCandidate(provider.id, model.modelKey); }}>
                                  <span className={`account-model-checkbox ${checked ? "is-checked" : ""}`}>{checked && <Check size={11} strokeWidth={3} />}</span>
                                  <span className="account-model-name">{model.displayName}</span>
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="account-menu-separator" />
              <button type="button" role="menuitem" onClick={() => void workspace.logout()}><LogOut size={15} /><span><strong>로그아웃</strong><small>현재 서버 세션 종료</small></span></button>
            </div>
          )}
          <button className="sidebar-account" type="button" aria-label="계정 메뉴" aria-expanded={accountMenuOpen} onClick={() => {
            setSessionMenuId(null);
            setAccountMenuOpen((open) => !open);
          }}>
            <div className="user-avatar">{userAvatarText(workspace.authSession.user.displayName, workspace.authSession.user.loginName, workspace.authSession.user.email)}</div>
            <div className="user-copy"><strong>{workspace.authSession.user.email}</strong>{(workspace.authSession.user.displayName || workspace.authSession.user.affiliation) && <small>{[workspace.authSession.user.displayName, workspace.authSession.user.affiliation].filter(Boolean).join(" · ")}</small>}</div>
            {accountMenuOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
          </button>
        </footer>
      </aside>

      <section className={`chat-pane view-${mainView}`} id="top">
        <header className="chat-header">
          <button className="mobile-menu-button" type="button" aria-label="사이드바 열기" onClick={() => setSidebarOpen(true)}><Menu size={19} /></button>
          <div className="chat-title-wrap">
            {sessionTitleEditing ? (
              <input className="chat-title-input" aria-label="세션명" autoFocus value={sessionTitleDraft} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setSessionTitleDraft(event.currentTarget.value)} onBlur={() => void commitSessionTitle()} onKeyDown={(event) => {
                if (event.key === "Enter") { event.preventDefault(); void commitSessionTitle(); }
                if (event.key === "Escape") { event.preventDefault(); setSessionTitleEditing(false); }
              }} />
            ) : (
              <h1><button className="chat-title-button" type="button" aria-label={sharedViewerToken ? "공유된 대화" : "세션명 수정"} disabled={Boolean(sharedViewerToken) || !workspace.activeConversation} onClick={() => beginSessionTitleEdit()}>{sharedViewerToken ? "공유된 대화" : workspace.activeConversation?.title ?? "새 작업"}</button></h1>
            )}
          </div>
          <div className="chat-actions">
            <span className={`connection-state state-${activeRuntime.streamState}`}>{streamLabel} <i /></span>
            <div className="notification-menu" ref={notificationMenuRef}>
              <button
                className={`notification-trigger tooltip-control ${notificationOpen ? "is-active" : ""}`}
                type="button"
                aria-label={notificationUnreadCount > 0 ? `알림 · 읽지 않음 ${notificationUnreadCount}개` : "알림"}
                aria-expanded={notificationOpen}
                data-tooltip={notificationOpen ? undefined : "알림"}
                onClick={() => {
                  setAccountMenuOpen(false);
                  setSessionMenuId(null);
                  setNotificationOpen((open) => !open);
                }}
              >
                <Bell size={16} />
                {notificationUnreadCount > 0 && (
                  <span className="notification-badge" aria-hidden="true">{notificationUnreadCount > 99 ? "99+" : notificationUnreadCount}</span>
                )}
              </button>
              {notificationOpen && (
                <section className="notification-panel" aria-label="알림 목록">
                  <header>
                    <div><strong>알림</strong><span>{notificationUnreadCount > 0 ? `읽지 않음 ${notificationUnreadCount}` : "모두 확인함"}</span></div>
                    <div className="notification-panel-actions">
                      <button
                        className="tooltip-control"
                        type="button"
                        aria-label="모든 알림 읽음 처리"
                        data-tooltip="모두 읽음"
                        disabled={notificationUnreadCount === 0 || Boolean(notificationBusyId)}
                        onClick={() => void markAllNotificationsRead()}
                      >
                        {notificationBusyId === "all" ? <LoaderCircle className="is-running" size={15} /> : <CheckCheck size={15} />}
                      </button>
                      <button
                        className={`tooltip-control notification-delete-all ${notificationDeleteArmedId === "all" ? "is-armed" : ""}`}
                        type="button"
                        aria-label={notificationDeleteArmedId === "all" ? "모든 알림 삭제 확인, 한 번 더 누르면 삭제" : "모든 알림 삭제"}
                        data-tooltip={notificationDeleteArmedId === "all" ? "한 번 더 눌러 삭제" : "모두 삭제"}
                        disabled={notifications.length === 0 || Boolean(notificationBusyId)}
                        onClick={() => void deleteAllNotifications()}
                      >
                        {notificationBusyId === "delete-all" ? <LoaderCircle className="is-running" size={15} /> : notificationDeleteArmedId === "all" ? <AlertCircle size={15} /> : <Trash2 size={15} />}
                      </button>
                    </div>
                  </header>
                  <div className="notification-list">
                    {notificationLoading && notifications.length === 0 && (
                      <div className="notification-state"><LoaderCircle className="is-running" size={16} /> 알림을 불러오고 있습니다.</div>
                    )}
                    {!notificationLoading && notificationError && (
                      <div className="notification-state is-error"><AlertCircle size={15} /> {notificationError}</div>
                    )}
                    {!notificationLoading && !notificationError && notifications.length === 0 && (
                      <div className="notification-state"><Bell size={16} /> 새 알림이 없습니다.</div>
                    )}
                    {notifications.map((notification) => {
                      const isFailure = notification.kind.includes("failed") || notification.kind.includes("limit");
                      const isApproval = notification.kind.includes("approval");
                      const conversationTitle = workspace.conversations.find(
                        (conversation) => conversation.id === notification.deepLink.conversationId,
                      )?.title.trim();
                      const runReference = notification.deepLink.runId?.slice(0, 6);
                      const notificationContext = [conversationTitle, runReference ? `작업 ${runReference}` : null]
                        .filter(Boolean)
                        .join(" · ");
                      const displayTitle = notification.kind === "run_completed" && notification.title === "작업이 완료되었습니다."
                        ? `${conversationTitle || "작업"} · 완료`
                        : notification.title;
                      return (
                        <article className={`notification-item ${notification.readAt ? "is-read" : "is-unread"}`} key={notification.id}>
                          <span className={`notification-kind ${isFailure ? "is-error" : isApproval ? "is-approval" : ""}`}>
                            {isFailure ? <AlertCircle size={15} /> : isApproval ? <Clock3 size={15} /> : <Check size={15} />}
                          </span>
                          <button className="notification-open" type="button" disabled={Boolean(notificationBusyId)} onClick={() => void openNotificationTarget(notification)}>
                            <span className="notification-copy">
                              <strong>{displayTitle}</strong>
                              <small>{notificationContext ? `${notificationContext} — ${notification.body}` : notification.body}</small>
                            </span>
                            <span className="notification-meta">
                              <time dateTime={notification.createdAt}>{formatNotificationTime(notification.createdAt)}</time>
                              {!notification.readAt && <i aria-label="읽지 않음" />}
                            </span>
                          </button>
                          <button className={`notification-delete ${notificationDeleteArmedId === notification.id ? "is-armed" : ""}`} type="button" aria-label={notificationDeleteArmedId === notification.id ? "알림 삭제 확인, 한 번 더 누르면 삭제" : "알림 삭제"} disabled={Boolean(notificationBusyId)} onClick={() => void deleteOneNotification(notification)}>
                            {notificationBusyId === notification.id ? <LoaderCircle className="is-running" size={14} /> : notificationDeleteArmedId === notification.id ? <AlertCircle size={14} /> : <Trash2 size={14} />}
                          </button>
                        </article>
                      );
                    })}
                  </div>
                </section>
              )}
            </div>
          </div>
        </header>

        {sharedViewerToken && (
          <SharedSnapshotViewer embedded token={sharedViewerToken} theme={sharedThemeFromLocation()} />
        )}

        <div
          className="conversation-scroll"
          ref={conversationFollow.containerRef}
          onScroll={conversationFollow.onScroll}
          onWheel={(event) => conversationFollow.onWheel(event.deltaY)}
          onPointerDown={conversationFollow.onPointerDown}
          onTouchStart={conversationFollow.onPointerDown}
          onDoubleClick={() => { if (artifactOpen) closeArtifact(); }}
        >
          <main className="conversation" aria-label="대화 내용">
            {activeRuntime.loading && !activeRuntime.loaded && <div className="conversation-loading"><LoaderCircle className="is-running" size={17} /> 대화를 불러오고 있습니다.</div>}
            {activeRuntime.error && <div className="conversation-error"><AlertCircle size={16} /> {activeRuntime.error}</div>}
            {!activeRuntime.loading && activeRuntime.turnSets.length === 0 && (
              <div className="conversation-empty"><Sparkles size={24} /><h2>무엇을 함께 진행할까요?</h2><p>요청을 보내면 진행 과정, Tool 사용과 Artifact가 이곳에 이어집니다.</p><StarterPrompts onSelect={applyStarterPrompt} /></div>
            )}
            {activeRuntime.turnSets.map((turnSet) => (
              <AssistantTurn
                key={turnSet.id}
                turnSet={turnSet}
                snapshot={turnSet.runId ? activeRuntime.snapshots[turnSet.runId] ?? null : null}
                openCalls={openCalls}
                onToggleCall={(id) => toggleSetItem(setOpenCalls, id)}
                onCopyTool={(execution) => void copyTool(execution)}
                onOpenArtifact={(artifact) => void openArtifact(artifact)}
                onShare={(anchorMessageId) => {
                  if (!workspace.activeConversationId) return;
                  void api.sharing.create(workspace.activeConversationId, anchorMessageId)
                    .then(async (share) => {
                      const url = new URL(share.viewerPath, window.location.origin).toString();
                      const themedUrl = new URL(url);
                      themedUrl.searchParams.set("theme", theme);
                      await navigator.clipboard.writeText(themedUrl.toString());
                      showToast("공유 링크를 복사했습니다.");
                    })
                    .catch((error) => {
                      showToast(error instanceof ApiError ? error.message : "공유 링크를 만들지 못했습니다.");
                    });
                }}
                onToast={showToast}
                onVisibleGrowth={conversationFollow.notifyGrowth}
              />
            ))}
          </main>
        </div>

        <div className="dock-area" ref={dockAreaRef}>
          <div className="run-dock">
            {activeRun && (
              <>
                <div className="progress-header">
                  <button className="progress-trigger" type="button" aria-expanded={progressOpen} onClick={() => setProgressOpen((open) => !open)}>
                    <div className="progress-title"><Sparkles size={15} /><strong>작업 진행 상황</strong></div>
                    {!progressOpen && (
                      <span className="current-step" title={latestProgressSummary?.text}>
                        {latestProgressSummary?.text ?? runStatusLabel(activeRun.status)}
                      </span>
                    )}
                    <span className="progress-count">{progress.filter((item) => item.status === "complete").length} / {progress.length} · {runStatusLabel(activeRun.status)}</span>
                    {progressOpen ? <ChevronDown className="progress-chevron" size={15} /> : <ChevronUp className="progress-chevron" size={15} />}
                  </button>
                  {(runCanPause || runIsPaused || runCanCancel) && (
                    <div className="run-controls" role="group" aria-label="Run 실행 제어">
                      {runCanPause && <button type="button" aria-label="Run 일시 정지" title="일시 정지" disabled={workspace.runActionBusy} onClick={() => void controlRun("pause")}><Pause size={14} /></button>}
                      {runIsPaused && <button type="button" aria-label="Run 재개" title="재개" disabled={workspace.runActionBusy} onClick={() => void controlRun("resume")}><Play size={14} /></button>}
                      {runCanCancel && <button className="is-danger" type="button" aria-label="Run 취소" title="취소" disabled={workspace.runActionBusy} onClick={() => void controlRun("cancel")}><X size={14} /></button>}
                    </div>
                  )}
                </div>
                {activeRun.pendingApprovals.length > 0 && (
                  <div className="approval-list" aria-label="승인이 필요한 Tool 작업">
                    {activeRun.pendingApprovals.map((approval) => (
                      <div className="approval-row" key={approval.id}>
                        <ShieldCheck size={15} />
                        <div className="approval-copy">
                          <strong>{approval.toolName}</strong>
                          <span>{approval.effect === "destructive" ? "삭제 등 되돌리기 어려운 작업" : "외부 시스템을 변경하는 작업"} · 인자 {approval.summary.argumentCount}개</span>
                        </div>
                        <button type="button" disabled={workspace.runActionBusy} onClick={() => void controlRun("reject", approval.id)}>거부</button>
                        <button className="is-primary lumina-primary-action" type="button" disabled={workspace.runActionBusy} onClick={() => void controlRun("approve", approval.id)}>승인</button>
                      </div>
                    ))}
                  </div>
                )}
                {progressOpen && (
                  <ol className="progress-steps">
                    {progress.map((step) => {
                      const canRetry = (activeRun.status === "failed" || activeRun.status === "limit_reached") && retryableStepIds.has(step.id);
                      return (
                      <li className={`progress-step step-${step.status} ${canRetry ? "has-action" : ""}`} key={step.id}>
                        <div className="progress-step-label">
                          {step.status === "complete" ? <Check size={15} /> : step.status === "running" ? <LoaderCircle className="is-running" size={15} /> : step.status === "error" ? <AlertCircle size={15} /> : <Circle size={14} />}
                          <span>{step.label}</span><small>{step.status === "complete" ? "완료" : step.status === "running" ? "진행 중" : step.status === "error" ? "확인 필요" : "대기"}</small>
                        </div>
                        {canRetry && <button className="step-retry" type="button" disabled={workspace.runActionBusy} onClick={() => void controlRun("retry_step", step.id)}><RotateCcw size={12} /> 재시도</button>}
                      </li>
                    );})}
                  </ol>
                )}
              </>
            )}
            <div className="composer">
              {workspace.composerAttachments.length > 0 && (
                <div className="composer-attachments" aria-label="첨부 Context">
                  {workspace.composerAttachments.map((attachment, attachmentIndex) => (
                    <span key={attachment.id}>
                      <FileText size={13} />
                      <span>{attachment.kind === "pasted_text" ? pastedTextAttachmentLabel(attachment, workspace.composerAttachments.slice(0, attachmentIndex).filter((item) => item.kind === "pasted_text").length) : attachment.fileName}</span>
                      {attachment.kind !== "pasted_text" && <small>{attachment.extractionStatus === "completed" ? "읽기 완료" : attachment.extractionStatus}</small>}
                      <button type="button" aria-label={`${attachment.fileName} 첨부 제거`} onClick={() => workspace.removeComposerAttachment(attachment.id)}><X size={12} /></button>
                    </span>
                  ))}
                </div>
              )}
              {selectedReferences.length > 0 && (
                <div className="composer-references" aria-label="연결된 Context 및 확장">
                  {selectedReferences.map((item) => (
                    <span className={`composer-reference kind-${item.reference.kind}`} key={item.key}>
                      {suggestionIcon(item.reference.kind)}
                      <span><strong>{item.token}</strong><small>{item.subtitle}</small></span>
                      <button type="button" aria-label={`${item.name} 연결 제거`} onClick={() => removeComposerReference(item.key)}><X size={12} /></button>
                    </span>
                  ))}
                </div>
              )}
              {composerTrigger && (
                <div className="composer-suggestions" id="composer-suggestions" role="listbox" aria-label={composerTrigger.trigger === "@" ? "파일 및 Artifact 후보" : "Skill 및 MCP 후보"}>
                  <div className="composer-suggestions-heading">
                    <span>{composerTrigger.trigger === "@" ? "Context 연결" : "Skill / MCP 호출"}</span>
                    <small>{composerTrigger.query ? `'${composerTrigger.query}' 검색` : "사용 가능한 항목"}</small>
                  </div>
                  {suggestionsLoading && <div className="composer-suggestion-state"><LoaderCircle className="is-running" size={14} /> 후보를 찾고 있습니다.</div>}
                  {!suggestionsLoading && composerSuggestions.length === 0 && <div className="composer-suggestion-state">사용 가능한 후보가 없습니다.</div>}
                  {!suggestionsLoading && composerSuggestions.map((suggestion, index) => {
                    const attached = suggestion.kind === "file" && workspace.composerAttachments.some((item) => item.id === suggestion.id);
                    const referenceId = suggestion.referenceId ?? suggestion.id;
                    const selected = selectedReferences.some((item) => item.key === `${suggestion.kind}:${referenceId}:${suggestion.versionOrDigest ?? ""}`);
                    const unavailable = suggestion.status !== undefined && suggestion.status !== "available";
                    const disabled = attached || selected || unavailable;
                    return (
                      <button
                        className={index === suggestionIndex ? "is-active" : ""}
                        id={`composer-suggestion-${index}`}
                        type="button"
                        role="option"
                        aria-selected={index === suggestionIndex}
                        disabled={disabled}
                        key={`${suggestion.kind}:${suggestion.id}`}
                        onMouseEnter={() => setSuggestionIndex(index)}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => selectComposerSuggestion(suggestion)}
                      >
                        <span className="composer-suggestion-icon">{suggestionIcon(suggestion.kind)}</span>
                        <span className="composer-suggestion-copy"><strong>{suggestion.name}</strong><small>{suggestion.subtitle}</small></span>
                        <span className="composer-suggestion-kind">{unavailable ? "사용 불가" : disabled ? attached ? "첨부됨" : "선택됨" : suggestion.kind === "mcp" ? `MCP · ${String(suggestion.displaySnapshot.configurationRevision ? `r${suggestion.displaySnapshot.configurationRevision}` : "revision")}` : referenceKindLabel(suggestion.kind)}</span>
                      </button>
                    );
                  })}
                </div>
              )}
              <textarea
                ref={composerInputRef}
                role="combobox"
                aria-label="Lumina에게 보낼 메시지"
                aria-autocomplete="list"
                aria-controls={composerTrigger ? "composer-suggestions" : undefined}
                aria-expanded={Boolean(composerTrigger)}
                aria-activedescendant={composerTrigger && composerSuggestions[suggestionIndex] ? `composer-suggestion-${suggestionIndex}` : undefined}
                value={draft}
                placeholder="메시지 보내기"
                rows={2}
                onChange={(event) => updateDraft(event.currentTarget.value, event.currentTarget.selectionStart)}
                onClick={(event) => setComposerTrigger(findComposerTrigger(event.currentTarget.value, event.currentTarget.selectionStart))}
                onKeyUp={(event) => {
                  if (["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(event.key)) return;
                  setComposerTrigger(findComposerTrigger(event.currentTarget.value, event.currentTarget.selectionStart));
                }}
                onPaste={(event) => {
                const files = Array.from(event.clipboardData.items)
                  .filter((item) => item.kind === "file")
                  .map((item) => item.getAsFile())
                  .filter((file): file is File => file !== null);
                if (files.length > 0) {
                  event.preventDefault();
                  void workspace.uploadFiles(files, "clipboard");
                  return;
                }
                const pasted = event.clipboardData.getData("text/plain");
                if (pasted && pasted.split(/\r?\n/).length > 20) {
                  event.preventDefault();
                  void workspace.attachPastedText(pasted);
                }
              }} onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return;
                if (composerTrigger && composerSuggestions.length > 0 && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
                  event.preventDefault();
                  moveSuggestionIndex(event.key === "ArrowDown" ? 1 : -1);
                  return;
                }
                if (composerTrigger && composerSuggestions[suggestionIndex] && (event.key === "Enter" || event.key === "Tab") && !event.shiftKey) {
                  event.preventDefault();
                  const highlighted = composerSuggestions[suggestionIndex];
                  const selectable = composerSuggestionDisabled(highlighted)
                    ? composerSuggestions.find((suggestion) => !composerSuggestionDisabled(suggestion))
                    : highlighted;
                  if (selectable) selectComposerSuggestion(selectable);
                  return;
                }
                if (composerTrigger && event.key === "Escape") {
                  event.preventDefault();
                  setComposerTrigger(null);
                  return;
                }
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage(event.ctrlKey || event.metaKey);
                }
              }} />
              <div className="composer-footer">
                <div>
                  <input ref={fileInputRef} className="visually-hidden" type="file" multiple accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.tsv,.png,.jpg,.jpeg,.webp,.gif" onChange={(event) => {
                    const files = Array.from(event.currentTarget.files ?? []);
                    event.currentTarget.value = "";
                    void workspace.uploadFiles(files);
                  }} />
                  <button type="button" aria-label="파일 첨부" disabled={workspace.uploadingAttachments} onClick={() => fileInputRef.current?.click()}>{workspace.uploadingAttachments ? <LoaderCircle className="is-running" size={17} /> : <Paperclip size={17} />}</button>
                  <button type="button" aria-label="Context 연결" onClick={() => insertComposerTrigger("@")}><AtSign size={17} /></button>
                  <button type="button" className="tooltip-control" aria-label="Skill 및 MCP 호출" data-tooltip="Skill / MCP" onClick={() => insertComposerTrigger("$")}><CircleDollarSign size={17} /></button>
                  <div className="output-mode-toggle" role="group" aria-label="출력 방식">
                    {([['auto', '자동'], ['chat', '채팅'], ['file', '파일']] as const).map(([value, label]) => (
                      <button
                        type="button"
                        key={value}
                        className={workspace.settings?.outputMode === value ? "is-active" : ""}
                        aria-pressed={workspace.settings?.outputMode === value}
                        onClick={() => void workspace.selectOutputMode(value)}
                      >{label}</button>
                    ))}
                  </div>
                </div>
                <div>
                  <ComposerPicker
                    options={candidateModelOptions}
                    value={selectedCandidateId}
                    onChange={(candidateId) => {
                      const candidate = candidateModelOptions.find((option) => option.id === candidateId);
                      if (candidate) void workspace.selectModelCandidate(candidate.providerId, candidate.modelKey);
                    }}
                    ariaLabel="모델 선택"
                    menuLabel="Model"
                    controlClassName="model-control"
                    placeholder="재설정 필요"
                  />
                  <ComposerPicker
                    options={effortOptions}
                    value={workspace.settings?.execution.effortId ?? ""}
                    onChange={(effortId) => void workspace.selectEffort(effortId || null)}
                    ariaLabel="추론 노력도 설정"
                    menuLabel="Effort"
                    controlClassName="effort-control"
                  />
                  <button className="send-button tooltip-control" type="button" disabled={workspace.sending || workspace.uploadingAttachments} aria-label={activeRun && !["completed", "failed", "cancelled", "limit_reached", "interrupted"].includes(activeRun.status) ? "현재 작업에 반영" : "새 작업 시작"} data-tooltip="Enter 반영 · Ctrl+Enter 대기" onClick={() => void sendMessage(false)}>
                    {workspace.sending ? <LoaderCircle className="is-running" size={17} /> : <Send size={17} />}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {mainView === "marketplace" && <MarketplaceView projectId={workspace.activeProjectId} onOpenNavigation={() => setSidebarOpen(true)} />}
        {mainView === "library" && <ArtifactLibraryView projectId={workspace.activeProjectId} onOpenArtifact={(artifact) => void openArtifact(artifact)} onOpenNavigation={() => setSidebarOpen(true)} />}
        {mainView === "files" && <ProjectFilesView projectId={workspace.activeProjectId} onOpenNavigation={() => setSidebarOpen(true)} onToast={showToast} />}
        {mainView === "schedules" && <SchedulesView projectId={workspace.activeProjectId} execution={workspace.settings?.execution ?? null} onOpenNavigation={() => setSidebarOpen(true)} />}
        {mainView === "memory" && <MemoryView project={activeProject} completedRunId={completedProjectLearningRunId} canReviewProjectLearning={canReviewProjectLearning} onOpenNavigation={() => setSidebarOpen(true)} />}
        {mainView === "admin" && isAdmin && <AdminView onOpenNavigation={() => setSidebarOpen(true)} onToast={showToast} onUserUpdated={() => void workspace.refreshAuthSession()} />}
        {mainView === "settings" && (
          <main className="feature-view settings-view" aria-label="설정">
            <aside className="settings-section-nav" aria-label="설정 항목">
              <header><Settings size={16} /><strong>설정</strong></header>
              <small>개인</small>
              <button className={settingsSection === "personal" ? "is-active" : ""} type="button" aria-current={settingsSection === "personal" ? "page" : undefined} onClick={() => setSettingsSection("personal")}><SlidersHorizontal size={15} />내 설정</button>
              {isAdmin && <><small>관리</small><button className={settingsSection === "admin" ? "is-active" : ""} type="button" aria-current={settingsSection === "admin" ? "page" : undefined} onClick={() => setSettingsSection("admin")}><ShieldCheck size={15} />관리자 설정</button></>}
            </aside>
            <section className="settings-content">
              <div className="settings-content-inner">
                <header className="settings-title"><h1>{settingsSection === "personal" ? "일반" : "관리자 설정"}</h1><p>{settingsSection === "personal" ? "Lumina의 화면과 기본 실행 옵션을 설정합니다." : "모든 사용자에게 적용할 실행 옵션을 설정합니다."}</p></header>
                {settingsSection === "personal" && <>
                <section className="settings-card" aria-labelledby="appearance-settings-title">
                  <header><h2 id="appearance-settings-title">모양</h2></header>
                  <div className="settings-row"><span><strong>테마</strong><small>앱 화면의 밝기를 선택합니다.</small></span><button className="settings-value-button" type="button" onClick={() => void workspace.toggleTheme()}>{theme === "dark" ? "다크" : "라이트"}</button></div>
                </section>
                <section className="settings-card" aria-labelledby="execution-settings-title">
                  <header><h2 id="execution-settings-title">기본 실행 옵션</h2></header>
                  <label className="settings-row"><span><strong>Provider</strong><small>새 Run에서 기본으로 사용할 Provider입니다.</small></span><select value={workspace.settings?.execution.providerId ?? ""} onChange={(event) => void workspace.selectProvider(event.currentTarget.value)}>{accountProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.displayName}</option>)}</select></label>
                  <label className="settings-row"><span><strong>Model</strong><small>선택한 Provider의 기본 Model입니다.</small></span><select value={workspace.settings?.execution.modelKey ?? ""} onChange={(event) => void workspace.selectModel(event.currentTarget.value)}>{workspace.models.map((model) => <option key={model.modelKey} value={model.modelKey}>{model.displayName}</option>)}</select></label>
                  <label className="settings-row"><span><strong>Effort</strong><small>지원되는 경우 기본 추론 강도를 선택합니다.</small></span><select value={workspace.settings?.execution.effortId ?? ""} onChange={(event) => void workspace.selectEffort(event.currentTarget.value || null)}><option value="">기본값</option>{effortOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
                </section>
                </>}
                {isAdmin && settingsSection === "admin" && (
                  <section className="settings-card settings-admin-card" aria-labelledby="admin-model-settings-title">
                    <header><span><ShieldCheck size={15} /><h2 id="admin-model-settings-title">관리자 설정</h2></span><small>모든 사용자에게 적용</small></header>
                    <label className="settings-row"><span><strong>Provider</strong><small>최대 토큰을 변경할 Provider입니다.</small></span><select value={adminSettingsProviderId} disabled={adminSettingsBusy} onChange={(event) => setAdminSettingsProviderId(event.currentTarget.value)}>{accountProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.displayName}</option>)}</select></label>
                    <label className="settings-row"><span><strong>Model</strong><small>설정값은 선택한 Model에만 적용됩니다.</small></span><select value={adminSettingsModelKey} disabled={adminSettingsBusy} onChange={(event) => setAdminSettingsModelKey(event.currentTarget.value)}>{adminSettingsModels.map((model) => <option key={model.modelKey} value={model.modelKey}>{model.displayName}</option>)}</select></label>
                    <div className="settings-row"><span><strong>최대 컨텍스트 토큰</strong><small>Run의 입력 예산 계산에 사용하는 모델별 최대 토큰입니다.{selectedAdminSettingsModel?.defaultContextWindow ? ` 기본값 ${selectedAdminSettingsModel.defaultContextWindow.toLocaleString()} 토큰.` : " 등록된 기본값이 없습니다."}</small></span><div className="settings-inline-control"><input type="text" inputMode="numeric" value={adminMaxTokens} disabled={adminSettingsBusy || !selectedAdminSettingsModel} onChange={(event) => setAdminMaxTokens(event.currentTarget.value.replace(/\D/g, "").replace(/\B(?=(\d{3})+(?!\d))/g, ","))} /><button className="is-secondary" type="button" disabled={adminSettingsBusy || !selectedAdminSettingsModel?.defaultContextWindow} onClick={() => void resetAdminMaxTokens()}>초기화</button><button type="button" disabled={adminSettingsBusy || !selectedAdminSettingsModel} onClick={() => void saveAdminMaxTokens()}>{adminSettingsBusy ? "저장 중" : "저장"}</button></div></div>
                    {adminSettingsError && <p className="settings-inline-error" role="alert">{adminSettingsError}</p>}
                  </section>
                )}
              </div>
            </section>
          </main>
        )}
        {mainView === "project-settings" && <ProjectSettings
          projects={workspace.projects}
          project={activeProject}
          onOpenNavigation={() => setSidebarOpen(true)}
          onSelect={(projectId) => workspace.setActiveProjectId(projectId)}
          onCreate={async () => {
            const names = new Set(workspace.projects.map((item) => item.name));
            let name = "새 프로젝트";
            let suffix = 2;
            while (names.has(name)) {
              name = `새 프로젝트 ${suffix}`;
              suffix += 1;
            }
            const created = await workspace.createProject(name);
            if (!created) showToast("프로젝트를 생성하지 못했습니다.");
          }}
          onSave={(projectId, changes) => workspace.updateProjectDetails(projectId, changes)}
          onDelete={(projectId) => workspace.archiveProject(projectId)}
        />}
      </section>

      {artifactOpen && (
        <aside className={`artifact-pane ${artifactFullscreen ? "is-fullscreen" : ""}`} aria-label="Artifact 작업 화면" aria-busy={artifactLoading || artifactSaveBusy !== null}>
          {!artifactFullscreen && <button className="artifact-resize-handle" type="button" role="separator" aria-label="Artifact 패널 너비 조절" aria-orientation="vertical" aria-valuemin={360} aria-valuenow={artifactPaneWidth} onPointerDown={beginArtifactResize} onKeyDown={resizeArtifactByKeyboard} />}
          <header className="artifact-header">
            <div>
              {artifactSummary && artifactVersionOptions.length > 0 && (
                <select className="artifact-version-control" aria-label="Artifact 버전 선택" value={artifactVersion?.version ?? artifactSummary.currentVersion} disabled={artifactLoading || artifactEditing || artifactSaveBusy !== null} onChange={(event) => void selectArtifactVersion(Number(event.currentTarget.value))}>
                  {artifactVersionOptions.map((version) => <option value={version} key={version}>{version === 1 ? "원본" : `v${version}`}</option>)}
                </select>
              )}
              <strong>{artifactSummary?.displayName ?? "Artifact"}</strong>
            </div>
            <div>
              <button className={`artifact-edit-control tooltip-control ${artifactEditing ? "is-active" : ""}`} type="button" aria-label="본문 수정" aria-pressed={artifactEditing} data-tooltip={!artifactIsCurrentVersion ? "과거 버전은 읽기 전용" : artifactHasTextSource ? "본문 수정" : "Binary 형식은 편집할 수 없음"} disabled={!artifactHasTextSource || !artifactIsCurrentVersion || artifactLoading || artifactSaveBusy !== null} onClick={() => {
                if (artifactEditing) {
                  setArtifactDraft(artifactVersion?.sourceText ?? "");
                  setArtifactEditing(false);
                  setArtifactEditablePreview("");
                  setArtifactAiComments([]);
                  setArtifactAiStatus(null);
                  setArtifactDraftSaved(false);
                  return;
                }
                setArtifactEditing(true);
                setArtifactTab(artifactVersion?.mimeType === "text/html" ? "preview" : "source");
                const editSource = artifactDraftSaved ? artifactDraft : artifactVersion?.sourceText ?? "";
                setArtifactDraft(editSource);
                setArtifactEditablePreview(artifactVersion?.mimeType === "text/html" ? editableArtifactHtml(editSource) : "");
              }}><Pencil size={16} /></button>
              {artifactEditing && (
                <>
                  <button className="tooltip-control" type="button" aria-label="편집 초안 저장" data-tooltip={artifactDraftStale ? "이전 초안 충돌 해결 필요" : "초안 저장"} disabled={artifactDraftStale || artifactSaveBusy !== null} onClick={() => void saveArtifactDraft()}>{artifactSaveBusy === "draft" ? <LoaderCircle className="is-running" size={16} /> : <Save size={16} />}</button>
                  <button className="tooltip-control" type="button" aria-label="새 Artifact 버전 저장" data-tooltip="새 버전 저장" disabled={artifactSaveBusy !== null} onClick={() => void saveArtifactVersion()}>{artifactSaveBusy === "version" ? <LoaderCircle className="is-running" size={16} /> : <FileCheck2 size={16} />}</button>
                  <button className="tooltip-control" type="button" aria-label="편집 취소" data-tooltip="편집 취소" disabled={artifactSaveBusy !== null} onClick={() => {
                    setArtifactDraft(artifactVersion?.sourceText ?? "");
                    setArtifactEditing(false);
                    setArtifactEditablePreview("");
                    setArtifactAiComments([]);
                    setArtifactAiStatus(null);
                    setArtifactDraftSaved(false);
                  }}><Undo2 size={16} /></button>
                </>
              )}
              <button className="artifact-view-control tooltip-control" type="button" aria-label={artifactTab === "preview" ? "코드 보기" : "미리보기"} data-tooltip={artifactHasTextSource ? artifactTab === "preview" ? "코드 보기" : "미리보기" : "Binary 형식은 소스 보기 없음"} disabled={!artifactHasTextSource} onClick={() => setArtifactTab((current) => current === "preview" ? "source" : "preview")}>
                {artifactTab === "preview" ? <Code2 size={17} /> : <Eye size={17} />}
              </button>
              <button className="tooltip-control" type="button" aria-label={artifactFullscreen ? "전체화면 종료" : "전체화면"} data-tooltip={artifactFullscreen ? "전체화면 종료" : "전체화면"} onClick={() => setArtifactFullscreen((value) => !value)}>
                {artifactFullscreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
              </button>
              <button className="tooltip-control" type="button" aria-label="Artifact 공유 링크 복사" data-tooltip={artifactSummary?.conversationId ? "공유 링크 복사" : "대화에 연결된 Artifact만 공유 가능"} disabled={!artifactSummary?.conversationId || artifactLoading} onClick={() => void shareArtifact()}><Share2 size={17} /></button>
              <button className="artifact-file-control tooltip-control" type="button" aria-label="Artifact 다운로드" data-tooltip="다운로드" disabled={!artifactVersion} onClick={() => void downloadArtifact()}><Download size={17} /></button>
              <button className="tooltip-control" type="button" aria-label="Artifact 닫기" data-tooltip="닫기" disabled={artifactSaveBusy !== null} onClick={closeArtifact}><X size={18} /></button>
            </div>
          </header>
          {(artifactEditing || artifactDraftNotice) && <div className={`artifact-edit-hint ${artifactDraftStale ? "is-conflict" : ""}`} role={artifactDraftStale ? "alert" : "status"} aria-live={artifactDraftStale ? "assertive" : "polite"}>
            {artifactDraftStale ? <AlertCircle size={13} /> : <Pencil size={13} />}
            {artifactDraftNotice ?? (artifactVersion?.mimeType === "text/html" ? "미리보기에서 본문을 직접 수정하고 초안 또는 새 버전으로 서버에 저장할 수 있습니다." : "소스를 편집하고 초안 또는 새 버전으로 서버에 저장할 수 있습니다.")}
          </div>}
          {artifactEditing && artifactVersion?.mimeType === "text/html" && artifactAiComments.length > 0 && (
            <section className="artifact-ai-comments" aria-label="AI 수정 의견">
              <header>
                <strong>{`수정 의견 ${artifactAiComments.length}개`}</strong>
                <button type="button" disabled={artifactAiSubmitting} onClick={() => void submitArtifactAiEdit()}>
                  {artifactAiSubmitting ? <LoaderCircle className="is-running" size={13} /> : <Sparkles size={13} />}
                  AI 자동편집
                </button>
              </header>
              <div className="artifact-ai-comment-list">
                {artifactAiComments.map((comment, index) => (
                  <div className="artifact-ai-comment" key={comment.id}>
                    <span>{index + 1}</span>
                    <div><small>{comment.text}</small><p>{comment.instruction}</p></div>
                    <button type="button" aria-label={`수정 의견 ${index + 1} 삭제`} disabled={artifactAiSubmitting} onClick={() => setArtifactAiComments((current) => current.filter((item) => item.id !== comment.id))}><X size={13} /></button>
                  </div>
                ))}
              </div>
              {artifactAiStatus && <p className="artifact-ai-status" role="status">{artifactAiStatus}</p>}
            </section>
          )}
          <div className={`artifact-body artifact-${artifactTab} ${artifactVersion?.mimeType === "application/pdf" ? "is-pdf" : ""} ${artifactVersion?.mimeType === "text/html" ? "is-html" : ""} ${artifactVersion && artifactHasTextSource && (artifactVersion.mimeType === "text/markdown" || artifactSummary?.kind === "markdown") ? "is-markdown" : ""}`}>
            {artifactLoading && <div className="artifact-loading"><LoaderCircle className="is-running" size={17} /> Artifact를 불러오고 있습니다.</div>}
            {!artifactLoading && artifactVersion?.mimeType === "application/pdf" && artifactPreviewUrl && (
              <div className="artifact-pdf-preview">
                <object data={artifactPreviewUrl} type="application/pdf" aria-label={`${artifactSummary?.displayName ?? "Artifact"} PDF 미리보기`}>
                  <p>이 브라우저에서는 PDF를 바로 표시할 수 없습니다. <a href={artifactPreviewUrl} target="_blank" rel="noreferrer noopener">새 탭에서 PDF 열기</a></p>
                </object>
              </div>
            )}
            {!artifactLoading && artifactVersion && !artifactHasTextSource && artifactVersion.mimeType !== "application/pdf" && (
              <div className={`artifact-binary-summary ${artifactVersion.mimeType.startsWith("image/") ? "is-image" : ""}`}>
                {artifactVersion.mimeType.startsWith("image/") && artifactVersion.previewUrl
                  ? <img className="artifact-image-preview" src={artifactVersion.previewUrl} alt={artifactSummary?.displayName ?? "생성 이미지"} />
                  : <FileCheck2 size={24} />}
                <h2>{artifactSummary?.displayName}</h2>
                <p>{artifactVersion.mimeType.startsWith("image/") ? "원본 비율로 미리보기 중입니다." : "이 형식은 본문 편집과 소스 미리보기를 지원하지 않습니다."}</p>
                <dl>
                  <div><dt>형식</dt><dd>{artifactVersion.mimeType}</dd></div>
                  <div><dt>검증</dt><dd className={`status-${artifactVersion.validationStatus}`}>{artifactVersion.validationStatus}</dd></div>
                  <div><dt>크기</dt><dd>{(artifactVersion.size / 1024).toFixed(1)}KB</dd></div>
                  {artifactVersion.metadata?.requestedModel && <div><dt>요청 모델</dt><dd>{artifactVersion.metadata.requestedModel}</dd></div>}
                  {artifactVersion.metadata?.actualModel && <div><dt>이미지 모델</dt><dd>{artifactVersion.metadata.actualModel}</dd></div>}
                  {artifactVersion.metadata?.actualBackend && <div><dt>Backend</dt><dd>{artifactVersion.metadata.actualBackend}</dd></div>}
                </dl>
                <button type="button" onClick={() => void downloadArtifact()}><Download size={15} /> 다운로드</button>
              </div>
            )}
            {!artifactLoading && artifactVersion && artifactHasTextSource && artifactTab === "preview" && (
              artifactVersion.mimeType === "text/markdown" || artifactSummary?.kind === "markdown" ? (
                <div className="artifact-markdown-preview"><MarkdownResponse text={artifactEditing ? artifactDraft : artifactVersion.sourceText ?? ""} artifact /></div>
              ) : artifactVersion.mimeType === "text/html" ? (
                <iframe ref={artifactPreviewFrameRef} className="artifact-preview-frame" title={artifactSummary?.displayName ?? "Artifact 미리보기"} sandbox={artifactEditing ? "allow-scripts allow-same-origin" : ""} srcDoc={artifactEditing ? artifactEditablePreview : artifactVersion.sourceText ?? ""} />
              ) : (
                <SyntaxCode className="artifact-text-preview" value={artifactEditing ? artifactDraft : artifactVersion.sourceText ?? ""} fileName={artifactSummary?.displayName} mimeType={artifactVersion.mimeType} />
              )
            )}
            {!artifactLoading && artifactVersion && artifactHasTextSource && artifactTab === "source" && (
              <div className="source-view">
                <div className="source-toolbar"><Code2 size={15} /> {artifactSummary?.displayName}<span>{artifactVersion.mimeType}</span></div>
                {artifactEditing ? (
                  <SyntaxTextarea className="artifact-source-editor" ariaLabel="Artifact 소스 편집" disabled={artifactSaveBusy !== null} value={artifactDraft} fileName={artifactSummary?.displayName} mimeType={artifactVersion.mimeType} onChange={(event) => {
                    setArtifactDraft(event.currentTarget.value);
                    setArtifactDraftSaved(false);
                    setArtifactDraftNotice(null);
                  }} />
                ) : (
                  <SyntaxCode value={artifactVersion.sourceText ?? "이 형식은 소스 미리보기를 지원하지 않습니다."} fileName={artifactSummary?.displayName} mimeType={artifactVersion.mimeType} />
                )}
              </div>
            )}
          </div>
          <footer className="artifact-footer">
            <span><i /> {artifactSaveBusy === "draft" ? "초안 저장 중" : artifactSaveBusy === "version" ? "버전 저장 중" : artifactDraftStale ? "초안 충돌" : artifactEditing ? artifactDraftSaved ? "초안 저장됨" : "편집 중" : "저장됨"}</span>
            <span>{artifactSummary && artifactVersion ? `v${artifactVersion.version} · ${artifactSummary.kind.toUpperCase()} · ${(artifactVersion.size / 1024).toFixed(1)}KB` : ""}</span>
          </footer>
        </aside>
      )}

      {conversationSearchOpen && (
        <ConversationSearchDialog
          projectId={workspace.activeProjectId}
          projectName={activeProject?.name ?? null}
          onClose={() => setConversationSearchOpen(false)}
          onSelect={(conversation) => {
            workspace.openConversation(conversation);
            setMainView("chat");
            setSidebarOpen(false);
            setConversationSearchOpen(false);
          }}
        />
      )}

      {toast && <div className="toast" role="status">{toast}</div>}
      {modelNameTooltip && <div className="account-model-tooltip" role="tooltip" style={{ left: modelNameTooltip.left, top: modelNameTooltip.top }}>{modelNameTooltip.name}</div>}
    </div>
  );
}

export default App;

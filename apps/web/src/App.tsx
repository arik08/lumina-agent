import {
  AlertCircle,
  ArrowDown,
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
  Heart,
  Library,
  LoaderCircle,
  LogOut,
  Maximize2,
  Menu,
  MessageCircle,
  MessageCircleQuestion,
  MessageSquarePlus,
  Megaphone,
  Minimize2,
  Moon,
  MoreVertical,
  Paperclip,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Pin,
  PinOff,
  Play,
  RotateCcw,
  Save,
  Search,
  Send,
  Settings,
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
  Image as ImageIcon,
  Info,
  Wrench,
  X,
} from "lucide-react";
import { createClientId } from "./client-id";
import { BranchFromHereIcon } from "./components/ActionIcons";
import { copyText } from "./clipboard";
import { lazy, Suspense, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type RefObject, type UIEvent as ReactUIEvent } from "react";
import { createPortal } from "react-dom";
import { api, ApiError, attachmentContentUrl } from "./api";
import { isTerminalRunStatus } from "./run-status";
import { SyntaxCode, SyntaxTextarea } from "./components/SyntaxCode";
import { GlobalTooltipLayer } from "./components/GlobalTooltip";
import { renderMermaidSvg } from "./components/InteractiveResponse";
import type {
  AnnouncementItem,
  AdminProviderModel,
  AdminProviderSummary,
  ArtifactSummary,
  ArtifactVersion,
  ComposerSuggestion,
  ExecutionSelection,
  NotificationItem,
  PromptReference,
  ReferenceKind,
  RunSnapshot,
  RunCommand,
  ToolExecution,
} from "./api-types";

type AdminProviderModelWithContextUsageRatio = AdminProviderModel & {
  defaultContextUsageRatio?: number;
};
import LoginScreen from "./components/LoginScreen";
import { AdminRunSafetySettings } from "./components/AdminRunSafetySettings";
import { ViewDataCacheProvider } from "./view-data-cache";
import { SelectMenu } from "./components/SelectMenu";
import { SharedSnapshotViewer } from "./components/SharedSnapshotViewer";
import { ConversationSearchDialog } from "./components/ConversationSearchDialog";
import { ConversationQuestionNavigator } from "./components/ConversationQuestionNavigator";
import { type PendingCommandAction, type RunControlAction, useLuminaWorkspace } from "./use-lumina-workspace";
import { useBackendConnectionState } from "./BackendConnectionGuard";
import { useConversationAutoFollow } from "./streaming-ui";
import {
  AssistantTurn,
  cumulativeSessionUsageByTurnSet,
  MarkdownResponse,
  pastedTextAttachmentLabel,
  runStatusLabel,
} from "./components/ConversationTurn";
import { ShareActionIcon } from "./components/ActionIcons";

const AdminView = lazy(() => import("./components/AdminView").then(({ AdminView }) => ({ default: AdminView })));
const ArtifactLibraryView = lazy(() => import("./components/ArtifactLibraryView").then(({ ArtifactLibraryView }) => ({ default: ArtifactLibraryView })));
const HelpCenterView = lazy(() => import("./components/HelpCenterView").then(({ HelpCenterView }) => ({ default: HelpCenterView })));
const MarketplaceView = lazy(() => import("./components/MarketplaceView").then(({ MarketplaceView }) => ({ default: MarketplaceView })));
const MemoryView = lazy(() => import("./components/MemoryView").then(({ MemoryView }) => ({ default: MemoryView })));
const ProjectFilesView = lazy(() => import("./components/ProjectFilesView").then(({ ProjectFilesView }) => ({ default: ProjectFilesView })));
const ProjectSettings = lazy(() => import("./components/ProjectSettings").then(({ ProjectSettings }) => ({ default: ProjectSettings })));
const SchedulesView = lazy(() => import("./components/SchedulesView").then(({ SchedulesView }) => ({ default: SchedulesView })));

type ArtifactTab = "preview" | "source";
type NotificationTab = "notifications" | "announcements";

const artifactPreviewEditMessage = "lumina:artifact-preview-edit";
const artifactAiCommentMessage = "lumina:artifact-ai-comment";
const artifactAiCommentsMessage = "lumina:artifact-ai-comments";
const artifactPaneMinWidth = 360;
const artifactSplitPaneMinViewport = 1024;
const chatPaneMinWidth = 440;

function focusSelectableRegion(event: ReactPointerEvent<HTMLElement>) {
  if (event.target instanceof Element && event.target.closest("a, button, input, textarea, select, [contenteditable='true']")) return;
  event.currentTarget.focus({ preventScroll: true });
}

function selectAllInRegion(event: import("react").KeyboardEvent<HTMLElement>) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey || event.key.toLowerCase() !== "a") return;
  const target = event.target;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || (target instanceof HTMLElement && target.isContentEditable)) return;
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(event.currentTarget);
  event.preventDefault();
  selection.removeAllRanges();
  selection.addRange(range);
}

const artifactCitationMarkers = [
  "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
  "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳",
];

const artifactMermaidCodeSelector = "pre > code.language-mermaid, pre > code.lang-mermaid, pre > code.language-mmd, pre > code.lang-mmd";

function hasRawArtifactMermaid(source: string) {
  return /class=["'][^"']*\bmermaid\b/i.test(source)
    || /class=["'][^"']*\b(?:language|lang)-(?:mermaid|mmd)\b/i.test(source);
}

function serializeArtifactHtml(document: Document, fullDocument: boolean, source: string) {
  if (!fullDocument) return document.body.innerHTML;
  const doctype = source.match(/<!doctype[^>]*>/i)?.[0] ?? "<!doctype html>";
  return `${doctype}\n${document.documentElement.outerHTML}`;
}

async function renderArtifactMermaidHtml(source: string) {
  if (!hasRawArtifactMermaid(source)) return source;
  const fullDocument = /<(?:!doctype|html|head|body)\b/i.test(source);
  const document = new DOMParser().parseFromString(source, "text/html");
  const tasks: Array<{ source: string; target: HTMLElement; replaceTarget?: Element }> = [];

  document.querySelectorAll<HTMLElement>(".mermaid").forEach((element) => {
    if (element.querySelector("svg")) return;
    const mermaidSource = (element.textContent ?? "").trim();
    if (mermaidSource) tasks.push({ source: mermaidSource, target: element });
  });
  document.querySelectorAll<HTMLElement>(artifactMermaidCodeSelector).forEach((code) => {
    if (code.closest(".mermaid")) return;
    const mermaidSource = (code.textContent ?? "").trim();
    const pre = code.closest("pre");
    if (!mermaidSource || !pre) return;
    const target = document.createElement("div");
    target.className = "mermaid";
    tasks.push({ source: mermaidSource, target, replaceTarget: pre });
  });

  await Promise.all(tasks.map(async (task) => {
    try {
      const { svg } = await renderMermaidSvg(task.source);
      task.target.innerHTML = svg;
      task.target.dataset.luminaRenderedMermaid = "true";
      task.target.setAttribute("role", "img");
      if (!task.target.getAttribute("aria-label")) task.target.setAttribute("aria-label", "Mermaid 다이어그램");
      task.replaceTarget?.replaceWith(task.target);
    } catch {
      task.target.classList.add("lumina-mermaid-error");
      task.target.textContent = "Mermaid 다이어그램을 렌더링하지 못했습니다.";
    }
  }));

  return serializeArtifactHtml(document, fullDocument, source);
}

const artifactMermaidZoomLayer = `<style id="lumina-artifact-mermaid-zoom-style">
.lumina-artifact-mermaid-host{position:relative!important}
.lumina-artifact-mermaid-expand{position:absolute;top:10px;right:10px;z-index:20;display:grid;width:32px;height:32px;padding:0;place-items:center;border:1px solid rgba(32,36,44,.18);border-radius:6px;background:rgba(255,255,255,.96);color:#20242c;box-shadow:0 7px 20px rgba(20,31,54,.15);cursor:pointer}
.lumina-artifact-mermaid-expand:hover,.lumina-artifact-mermaid-expand:focus-visible{border-color:#3f66c9;color:#315fbd;outline:2px solid rgba(63,102,201,.22);outline-offset:2px}
.lumina-artifact-mermaid-expand svg,.lumina-artifact-mermaid-control svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.lumina-artifact-mermaid-backdrop{position:fixed;inset:0;z-index:2147483647;display:flex;flex-direction:column;background:rgba(248,250,252,.99);color:#20242c;font:13px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
.lumina-artifact-mermaid-header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border-bottom:1px solid rgba(32,36,44,.14);background:#fff}
.lumina-artifact-mermaid-controls{display:flex;align-items:center;gap:6px}
.lumina-artifact-mermaid-value{min-width:48px;text-align:center;color:#626b78}
.lumina-artifact-mermaid-control{display:grid;width:30px;height:30px;padding:0;place-items:center;border:1px solid rgba(32,36,44,.16);border-radius:6px;background:#fff;color:#20242c;cursor:pointer}
.lumina-artifact-mermaid-control:hover,.lumina-artifact-mermaid-control:focus-visible{border-color:#3f66c9;color:#315fbd;outline:2px solid rgba(63,102,201,.22);outline-offset:1px}
.lumina-artifact-mermaid-viewport{display:grid;flex:1;overflow:hidden;place-items:center;background:radial-gradient(circle,rgba(108,115,126,.22) 0 1px,transparent 1.2px),#eef1f5;background-size:18px 18px,auto;cursor:grab;touch-action:none;user-select:none}
.lumina-artifact-mermaid-viewport.is-dragging{cursor:grabbing}
.lumina-artifact-mermaid-canvas{transform-origin:center;transition:transform 100ms ease}
.lumina-artifact-mermaid-canvas svg{display:block!important;width:auto!important;height:auto!important;max-width:calc(100vw - 48px)!important;max-height:calc(100vh - 92px)!important}
@media print{.lumina-artifact-mermaid-expand,.lumina-artifact-mermaid-backdrop{display:none!important}}
</style><script id="lumina-artifact-mermaid-zoom-bridge">
(() => {
  if (window.__luminaArtifactMermaidZoomReady) return;
  window.__luminaArtifactMermaidZoomReady = true;
  const expandIcon = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M8 3H3v5"></path><path d="M3 3l7 7"></path><path d="M16 3h5v5"></path><path d="m21 3-7 7"></path><path d="M8 21H3v-5"></path><path d="m3 21 7-7"></path><path d="M16 21h5v-5"></path><path d="m21 21-7-7"></path></svg>';
  const icons = {
    close: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>',
    reset: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 7v5h5"></path><path d="M5.7 12A7 7 0 0 1 17 6.5"></path><path d="M18.3 12A7 7 0 0 1 7 17.5"></path></svg>',
    zoomIn: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>',
    zoomOut: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 12h14"></path></svg>'
  };
  let activeViewer = null;

  const closeViewer = () => {
    if (!activeViewer) return;
    activeViewer.close();
    activeViewer = null;
  };
  const onEscape = (event) => { if (event.key === "Escape") closeViewer(); };
  const control = (label, icon, action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lumina-artifact-mermaid-control";
    button.setAttribute("aria-label", label);
    button.innerHTML = icons[icon];
    button.addEventListener("click", action);
    return button;
  };
  const openViewer = (svg, trigger) => {
    closeViewer();
    const previousOverflow = document.body.style.overflow;
    const backdrop = document.createElement("section");
    backdrop.className = "lumina-artifact-mermaid-backdrop";
    backdrop.setAttribute("role", "dialog");
    backdrop.setAttribute("aria-modal", "true");
    backdrop.setAttribute("aria-label", "Mermaid 다이어그램 크게 보기");
    const header = document.createElement("header");
    header.className = "lumina-artifact-mermaid-header";
    const heading = document.createElement("strong");
    heading.textContent = svg.closest("[aria-label]")?.getAttribute("aria-label") || "Mermaid";
    const controls = document.createElement("div");
    controls.className = "lumina-artifact-mermaid-controls";
    const value = document.createElement("output");
    value.className = "lumina-artifact-mermaid-value";
    const viewport = document.createElement("div");
    viewport.className = "lumina-artifact-mermaid-viewport";
    const canvas = document.createElement("div");
    canvas.className = "lumina-artifact-mermaid-canvas";
    const clonedSvg = svg.cloneNode(true);
    const viewBox = String(svg.getAttribute("viewBox") || "").split(/[\\s,]+/).map(Number);
    if (viewBox.length >= 4 && Number.isFinite(viewBox[2]) && Number.isFinite(viewBox[3]) && viewBox[2] > 0 && viewBox[3] > 0) {
      clonedSvg.setAttribute("width", String(viewBox[2]));
      clonedSvg.setAttribute("height", String(viewBox[3]));
    }
    canvas.append(clonedSvg);
    viewport.append(canvas);
    let zoom = 1;
    let offsetX = 0;
    let offsetY = 0;
    let drag = null;
    const update = () => {
      canvas.style.transform = "translate(" + offsetX + "px," + offsetY + "px) scale(" + zoom + ")";
      value.textContent = Math.round(zoom * 100) + "%";
    };
    const changeZoom = (next) => { zoom = Math.min(4, Math.max(.5, next)); update(); };
    const reset = () => { zoom = 1; offsetX = 0; offsetY = 0; update(); };
    const close = () => {
      backdrop.remove();
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onEscape);
      trigger.focus();
    };
    activeViewer = { close };
    const closeButton = control("크게 보기 닫기", "close", closeViewer);
    controls.append(
      control("축소", "zoomOut", () => changeZoom(zoom / 1.2)),
      value,
      control("확대", "zoomIn", () => changeZoom(zoom * 1.2)),
      control("보기 초기화", "reset", reset),
      closeButton
    );
    header.append(heading, controls);
    backdrop.append(header, viewport);
    document.body.append(backdrop);
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onEscape);
    viewport.addEventListener("wheel", (event) => {
      event.preventDefault();
      changeZoom(zoom * (event.deltaY > 0 ? .9 : 1.1));
    }, { passive: false });
    viewport.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, offsetX, offsetY };
      viewport.setPointerCapture?.(event.pointerId);
      viewport.classList.add("is-dragging");
    });
    viewport.addEventListener("pointermove", (event) => {
      if (!drag || drag.id !== event.pointerId) return;
      offsetX = drag.offsetX + event.clientX - drag.x;
      offsetY = drag.offsetY + event.clientY - drag.y;
      update();
    });
    const finishDrag = (event) => {
      if (!drag || drag.id !== event.pointerId) return;
      drag = null;
      viewport.classList.remove("is-dragging");
    };
    viewport.addEventListener("pointerup", finishDrag);
    viewport.addEventListener("pointercancel", finishDrag);
    closeButton.focus();
    update();
  };
  const attach = (svg) => {
    if (svg.closest(".lumina-artifact-mermaid-backdrop")) return;
    const host = svg.closest("[data-lumina-rendered-mermaid],.mermaid,.mermaid-chart") || svg.parentElement;
    if (!host || host.dataset.luminaMermaidZoomAttached === "true") return;
    host.dataset.luminaMermaidZoomAttached = "true";
    host.classList.add("lumina-artifact-mermaid-host");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lumina-artifact-mermaid-expand";
    button.setAttribute("aria-label", "Mermaid 다이어그램 크게 보기");
    button.innerHTML = expandIcon;
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openViewer(svg, button);
    });
    host.prepend(button);
  };
  const enhance = () => document.querySelectorAll("[data-lumina-rendered-mermaid] svg,.mermaid svg,.mermaid-chart svg,svg[id^='mermaid-']").forEach(attach);
  const schedule = () => requestAnimationFrame(enhance);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", schedule, { once: true });
  else schedule();
  window.addEventListener("load", schedule);
  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
})();
</script>`;

function previewArtifactHtml(source: string) {
  const layers: string[] = [];
  if (/class=["'][^"']*\bsource-ref\b/i.test(source)) layers.push(`<style id="lumina-artifact-citation-style">
sup.source-ref { display: inline; margin: 0 1px 0 2px; color: #315fbd; font-size: inherit; line-height: inherit; vertical-align: baseline; }
a.source-ref, sup.source-ref > a { display: inline; width: auto; height: auto; margin: 0 1px 0 2px; padding: 0; border: 0; border-radius: 3px; background: transparent; color: #315fbd; font-family: inherit; font-size: 1em; font-weight: 720; line-height: inherit; text-decoration: none; vertical-align: baseline; }
a.source-ref:hover, sup.source-ref > a:hover { text-decoration: none !important; }
a.source-ref:focus-visible, sup.source-ref > a:focus-visible { outline: 2px solid color-mix(in srgb, currentColor 55%, transparent); outline-offset: 2px; }
.lumina-artifact-source-card { position: fixed; z-index: 2147483647; right: 18px; bottom: 18px; display: grid; width: min(420px, calc(100vw - 36px)); gap: 8px; padding: 14px 42px 14px 15px; border: 1px solid rgba(49,95,189,.28); border-radius: 8px; background: #fff; color: #202631; box-shadow: 0 16px 44px rgba(20,31,54,.22); font: 14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
.lumina-artifact-source-card strong { font-size: 14px; }
.lumina-artifact-source-card a { overflow-wrap: anywhere; color: #315fbd; text-decoration: underline; text-underline-offset: 2px; }
.lumina-artifact-source-card button { position: absolute; top: 8px; right: 8px; display: grid; width: 28px; height: 28px; place-items: center; border: 0; border-radius: 5px; background: transparent; color: #6b7280; cursor: pointer; font: 18px/1 sans-serif; }
</style><script id="lumina-artifact-citation-bridge">
(() => {
  const markers = ${JSON.stringify(artifactCitationMarkers)};
  document.querySelectorAll("a.source-ref[href], sup.source-ref > a[href]").forEach((link) => {
    const number = Number((link.textContent || "").trim());
    if (Number.isInteger(number) && number > 0) link.textContent = markers[number - 1] || "[" + number + "]";
    link.target = "_blank";
    link.rel = "noreferrer noopener";
    if (!link.getAttribute("aria-label")) link.setAttribute("aria-label", Number.isInteger(number) ? "출처 " + number + " 열기" : "출처 열기");
    if (!link.title) link.title = link.href;
    link.addEventListener("click", () => {
      document.getElementById("lumina-artifact-source-card")?.remove();
      const card = document.createElement("aside");
      card.id = "lumina-artifact-source-card";
      card.className = "lumina-artifact-source-card";
      card.setAttribute("role", "dialog");
      card.setAttribute("aria-label", "출처 링크");
      const heading = document.createElement("strong");
      heading.textContent = link.getAttribute("aria-label") || "출처 링크";
      const sourceLink = document.createElement("a");
      sourceLink.href = link.href;
      sourceLink.target = "_blank";
      sourceLink.rel = "noreferrer noopener";
      sourceLink.textContent = link.href;
      const close = document.createElement("button");
      close.type = "button";
      close.setAttribute("aria-label", "출처 링크 닫기");
      close.textContent = "×";
      close.addEventListener("click", () => card.remove());
      card.append(heading, sourceLink, close);
      document.body.appendChild(card);
    });
  });
})();
</script>`);
  if (hasRawArtifactMermaid(source) || /data-lumina-rendered-mermaid/i.test(source)) layers.push(artifactMermaidZoomLayer);
  if (!layers.length) return source;
  const compatibilityLayer = layers.join("");
  return /<\/body\s*>/i.test(source)
    ? source.replace(/<\/body\s*>/i, `${compatibilityLayer}</body>`)
    : `${source}${compatibilityLayer}`;
}

function ArtifactHtmlPreview({
  frameRef,
  source,
  title,
  renderMermaid,
}: {
  frameRef: RefObject<HTMLIFrameElement | null>;
  source: string;
  title: string;
  renderMermaid: boolean;
}) {
  const [previewHtml, setPreviewHtml] = useState(() => previewArtifactHtml(source));
  useEffect(() => {
    let cancelled = false;
    if (!renderMermaid || !hasRawArtifactMermaid(source)) {
      setPreviewHtml(previewArtifactHtml(source));
      return undefined;
    }
    void renderArtifactMermaidHtml(source).then((rendered) => {
      if (!cancelled) setPreviewHtml(previewArtifactHtml(rendered));
    });
    return () => { cancelled = true; };
  }, [renderMermaid, source]);
  return <iframe ref={frameRef} className="artifact-preview-frame" title={title} sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads allow-popups allow-popups-to-escape-sandbox" srcDoc={previewHtml} />;
}

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
    .lumina-ai-comment-popover.is-multiline textarea { grid-column: 1/-1; height: auto; min-height: 58px; overflow-y: auto; padding: 0 2px; font-size: 14px; line-height: 1.4; }
    .lumina-ai-comment-popover button { display: inline-grid; min-width: 26px; height: 26px; place-items: center; border: 0; border-radius: 999px; background: rgba(255,255,255,.92); color: #1f1f1f; cursor: pointer; font: 800 13px/1 system-ui,sans-serif; }
    .lumina-ai-comment-popover .lumina-ai-comment-cancel { display: none; justify-self: start; min-width: 45px; padding: 0 10px; background: rgba(255,255,255,.12); color: rgba(255,255,255,.86); font-size: 13px; }
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
        const randomBytes = new Uint8Array(16);
        if (typeof crypto.getRandomValues === 'function') crypto.getRandomValues(randomBytes);
        else for (let index = 0; index < randomBytes.length; index += 1) randomBytes[index] = Math.floor(Math.random() * 256);
        randomBytes[6] = (randomBytes[6] & 15) | 64;
        randomBytes[8] = (randomBytes[8] & 63) | 128;
        const randomHex = Array.from(randomBytes, (byte) => byte.toString(16).padStart(2, '0'));
        const id = typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : randomHex.slice(0, 4).join('') + '-' + randomHex.slice(4, 6).join('') + '-' + randomHex.slice(6, 8).join('') + '-' + randomHex.slice(8, 10).join('') + '-' + randomHex.slice(10).join('');
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
  { category: "Workflow", title: "업무 흐름 다이어그램", prompt: "[포스코 투자관리그룹]의 주요 업무를 조사하고, workflow diagram을 포함하여 전반적인 업무 흐름과 세부 사항을 정리해줘.", icon: BranchFromHereIcon },
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
type MainView = "chat" | "marketplace" | "library" | "files" | "help" | "schedules" | "memory" | "admin" | "settings" | "project-settings";

const artifactPaneViews = new Set<MainView>(["chat", "library"]);

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
  openai: 4,
  openai_compatible: 5,
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
  if (kind === "folder") return <Folder size={15} aria-hidden="true" />;
  if (kind === "skill") return <Sparkles size={15} aria-hidden="true" />;
  if (kind === "mcp") return <Wrench size={15} aria-hidden="true" />;
  return <FileText size={15} aria-hidden="true" />;
}

function referenceKindLabel(kind: ReferenceKind) {
  if (kind === "artifact") return "Artifact";
  if (kind === "folder") return "폴더";
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

function sharedArtifactFromLocation() {
  const params = new URLSearchParams(window.location.search);
  const artifactId = params.get("artifact");
  const parsedVersion = Number(params.get("version"));
  return {
    artifactId,
    artifactVersion: Number.isInteger(parsedVersion) && parsedVersion > 0 ? parsedVersion : null,
  };
}

function formalizePlanStepLabel(label: string) {
  return label
    .replace(/한다([.!?]?)$/u, "합니다$1")
    .replace(/된다([.!?]?)$/u, "됩니다$1")
    .replace(/이다([.!?]?)$/u, "입니다$1");
}

function derivedProgress(run: RunSnapshot) {
  if (run.workPlan?.length) {
    return [...run.workPlan].sort((left, right) => left.order - right.order).map((step) => ({
      id: step.id,
      label: formalizePlanStepLabel(step.step),
      status: step.status === "completed" ? "complete" : step.status === "in_progress" ? "running" : "waiting",
      subtasks: [],
    }));
  }
  const terminal = isTerminalRunStatus(run.status);
  return [
    {
      id: "request",
      label: terminal ? "요청을 처리했습니다" : "작업 계획을 수립합니다",
      status: run.status === "completed" ? "complete" : terminal ? "error" : "running",
      subtasks: [],
    },
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

const defaultArtifactOutputTokens = 10_000;

const artifactLengthSteps = [
  { value: 8_000, label: "8k", warning: null },
  { value: 10_000, label: "10k", warning: null },
  { value: 12_000, label: "12k", warning: null },
  { value: 15_000, label: "15k", warning: null },
  { value: 20_000, label: "20k", warning: "장문" },
  { value: 30_000, label: "30k", warning: "장문" },
  { value: 40_000, label: "40k", warning: "최대" },
] as const;

function ArtifactLengthSlider({
  value,
  onChange,
  disabled = false,
}: {
  value: number | null;
  onChange: (value: number | null) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({ left: 0, top: 0, visibility: "hidden" });
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const inputId = useId();
  const popoverId = useId();
  const selectedIndex = Math.max(
    0,
    artifactLengthSteps.findIndex((option) => option.value === (value ?? defaultArtifactOutputTokens)),
  );
  const selected = artifactLengthSteps[selectedIndex];
  const selectStep = (index: number) => {
    const boundedIndex = Math.min(artifactLengthSteps.length - 1, Math.max(0, index));
    const option = artifactLengthSteps[boundedIndex];
    onChange(option ? option.value : defaultArtifactOutputTokens);
  };
  const tone = selected.warning === "최대"
    ? "danger"
    : selected.warning
      ? "warning"
      : selected.value <= 10_000
        ? "muted"
        : "normal";
  const ariaValueText = `${selected.label}${selected.warning ? `, ${selected.warning}` : ""}, 채팅 답변이 아닌 생성 파일의 목표 분량`;

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !popoverRef.current?.contains(target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return undefined;
    const updatePosition = () => {
      const trigger = triggerRef.current;
      const popover = popoverRef.current;
      if (!trigger || !popover) return;
      const triggerRect = trigger.getBoundingClientRect();
      const popoverRect = popover.getBoundingClientRect();
      const viewportPadding = 12;
      const gap = 8;
      const maximumLeft = Math.max(viewportPadding, window.innerWidth - viewportPadding - popoverRect.width);
      const left = Math.min(
        maximumLeft,
        Math.max(viewportPadding, triggerRect.left),
      );
      setPopoverStyle({
        left,
        top: Math.max(viewportPadding, triggerRect.top - gap - popoverRect.height),
        visibility: "visible",
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  return (
    <div
      ref={rootRef}
      className={`artifact-length-control is-${tone}${open ? " is-open" : ""}`}
    >
      <button
        ref={triggerRef}
        className="artifact-length-trigger"
        type="button"
        disabled={disabled}
        aria-label={`문서 출력 토큰: ${selected.label}${selected.warning ? `, ${selected.warning}` : ""}`}
        aria-expanded={open}
        aria-controls={popoverId}
        onClick={() => setOpen((current) => !current)}
      >
        <FileText size={12} aria-hidden="true" />
        <span className="artifact-length-value">{selected.label}</span>
        {selected.warning && <small>{selected.warning}</small>}
      </button>
      {open && createPortal(
        <div
          ref={popoverRef}
          id={popoverId}
          className={`artifact-length-popover is-${tone}${rootRef.current?.closest(".theme-dark") ? " theme-dark" : ""}`}
          role="group"
          aria-label="문서 출력 토큰 조절"
          style={{
            ...popoverStyle,
            "--artifact-length-progress": `${(selectedIndex / (artifactLengthSteps.length - 1)) * 100}%`,
          } as CSSProperties}
        >
          <div>
            <label htmlFor={inputId}>문서 출력 토큰</label>
            <output htmlFor={inputId}>
              <span>{selected.label}</span>
              {selected.warning && <small>{selected.warning}</small>}
            </output>
          </div>
          <input
            id={inputId}
            data-testid="artifact-length-slider"
            type="range"
            min={0}
            max={artifactLengthSteps.length - 1}
            step={1}
            value={selectedIndex}
            aria-label="문서 출력 토큰"
            aria-valuetext={ariaValueText}
            onChange={(event) => selectStep(Number(event.currentTarget.value))}
            onKeyDown={(event) => {
              const nextIndex = event.key === "Home"
                ? 0
                : event.key === "End"
                  ? artifactLengthSteps.length - 1
                  : ["ArrowRight", "ArrowUp"].includes(event.key)
                    ? selectedIndex + 1
                    : ["ArrowLeft", "ArrowDown"].includes(event.key)
                      ? selectedIndex - 1
                      : null;
              if (nextIndex === null) return;
              event.preventDefault();
              selectStep(nextIndex);
            }}
          />
        </div>,
        document.body,
      )}
    </div>
  );
}

function ComposerPicker({
  options,
  value,
  onChange,
  ariaLabel,
  menuLabel,
  controlClassName,
  placeholder,
  tooltip,
  disabled = false,
}: {
  options: ComposerPickerOption[];
  value: string;
  onChange: (id: string) => void;
  ariaLabel: string;
  menuLabel: string;
  controlClassName: string;
  placeholder?: string;
  tooltip?: string;
  disabled?: boolean;
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
        className={`composer-picker-trigger ${controlClassName}${tooltip ? " tooltip-control" : ""}`}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        disabled={disabled || options.length === 0}
        data-tooltip={tooltip}
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

function FeatureViewLoading() {
  return (
    <main className="feature-view feature-view-loading" aria-label="화면 로딩" aria-busy="true">
      <LoaderCircle className="is-running" size={17} />
      <span>화면을 불러오고 있습니다.</span>
    </main>
  );
}

function App() {
  const workspace = useLuminaWorkspace();
  const backendConnectionState = useBackendConnectionState();
  const [mainView, setMainView] = useState<MainView>("chat");
  const [settingsSection, setSettingsSection] = useState<"personal" | "admin">("personal");
  const [progressOpen, setProgressOpen] = useState(false);
  const progressRunIdRef = useRef<string | null>(null);
  const progressPlanIdRef = useRef<string | null>(null);
  const [openCalls, setOpenCalls] = useState<Set<string>>(new Set());
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const sidebarAutoCollapsedRef = useRef(false);
  const [sessionMenuId, setSessionMenuId] = useState<string | null>(null);
  const [likedSessionsOnly, setLikedSessionsOnly] = useState(false);
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
  const [adminFooterProviders, setAdminFooterProviders] = useState<AdminProviderSummary[]>([]);
  const [adminFooterModels, setAdminFooterModels] = useState<Record<string, AdminProviderModel[]>>({});
  const [adminFooterBusyId, setAdminFooterBusyId] = useState<string | null>(null);
  const [modelNameTooltip, setModelNameTooltip] = useState<{ name: string; left: number; top: number } | null>(null);
  const [conversationSearchOpen, setConversationSearchOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [notificationTab, setNotificationTab] = useState<NotificationTab>("notifications");
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);
  const [helpAnnouncementId, setHelpAnnouncementId] = useState<string | null>(null);
  const [notificationUnreadCount, setNotificationUnreadCount] = useState(0);
  const [notificationLoading, setNotificationLoading] = useState(false);
  const [notificationError, setNotificationError] = useState<string | null>(null);
  const [notificationBusyId, setNotificationBusyId] = useState<string | null>(null);
  const [notificationDeleteArmedId, setNotificationDeleteArmedId] = useState<string | null>(null);
  const [sessionTitleEditing, setSessionTitleEditing] = useState(false);
  const [sessionTitleDraft, setSessionTitleDraft] = useState("");
  const [draft, setDraft] = useState("");
  const [targetOutputTokens, setTargetOutputTokens] = useState<number | null>(defaultArtifactOutputTokens);
  const [composerTrigger, setComposerTrigger] = useState<ComposerTriggerState | null>(null);
  const [composerSuggestions, setComposerSuggestions] = useState<ComposerSuggestion[]>([]);
  const [selectedReferences, setSelectedReferences] = useState<SelectedComposerReference[]>([]);
  const [suggestionIndex, setSuggestionIndex] = useState(0);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [pendingCommandAction, setPendingCommandAction] = useState<{ id: string; action: PendingCommandAction } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [adminSettingsProviderId, setAdminSettingsProviderId] = useState("");
  const [adminSettingsModels, setAdminSettingsModels] = useState<AdminProviderModel[]>([]);
  const [adminSettingsModelKey, setAdminSettingsModelKey] = useState("");
  const [adminInitialExecution, setAdminInitialExecution] = useState<ExecutionSelection | null>(null);
  const [adminInitialExecutionBusy, setAdminInitialExecutionBusy] = useState(false);
  const [adminInitialExecutionError, setAdminInitialExecutionError] = useState<string | null>(null);
  const [adminMaxTokens, setAdminMaxTokens] = useState("");
  const [adminContextUsagePercent, setAdminContextUsagePercent] = useState("");
  const [adminOutputTokens, setAdminOutputTokens] = useState(0);
  const [adminSettingsBusy, setAdminSettingsBusy] = useState(false);
  const [adminSettingsError, setAdminSettingsError] = useState<string | null>(null);
  const [artifactOpen, setArtifactOpen] = useState(false);
  const [artifactPaneWidth, setArtifactPaneWidth] = useState(() => {
    const saved = Number(localStorage.getItem("lumina:artifactPaneWidth"));
    return Number.isFinite(saved) && saved >= artifactPaneMinWidth
      ? saved
      : Math.max(520, Math.round(window.innerWidth * 0.42));
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
  const fileModeButtonRef = useRef<HTMLButtonElement>(null);
  const previousConversationRef = useRef<string | null>(null);
  const artifactOpenRequestRef = useRef(0);
  const artifactHistoryOpenRef = useRef(false);
  const artifactPreviewFrameRef = useRef<HTMLIFrameElement>(null);
  const dockAreaRef = useRef<HTMLDivElement>(null);
  const notificationMenuRef = useRef<HTMLDivElement>(null);
  const modelNameTooltipTimerRef = useRef<number | null>(null);
  const sessionScrollbarIdleTimerRef = useRef<number | null>(null);

  useEffect(() => {
    localStorage.setItem("lumina:artifactPaneWidth", String(artifactPaneWidth));
  }, [artifactPaneWidth]);

  function clampArtifactPaneWidth(value: number, collapsed: boolean) {
    const sidebarWidth = collapsed ? 48 : 278;
    const maximum = Math.max(artifactPaneMinWidth, window.innerWidth - sidebarWidth - chatPaneMinWidth);
    return Math.min(Math.max(value, artifactPaneMinWidth), maximum);
  }

  function beginArtifactResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (artifactFullscreen || window.innerWidth < artifactSplitPaneMinViewport) return;
    event.preventDefault();
    const handle = event.currentTarget;
    let currentCollapsed = sidebarCollapsed;
    setArtifactResizing(true);
    try { handle.setPointerCapture(event.pointerId); } catch { /* Pointer capture is not available in every browser path. */ }
    let finished = false;
    let resizeFrame: number | null = null;
    let pendingClientX = event.clientX;
    const finish = () => {
      if (finished) return;
      finished = true;
      if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame);
      resizeFrame = null;
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
    const applyResize = () => {
      resizeFrame = null;
      const expandedChatWidth = pendingClientX - 278;
      let nextCollapsed = currentCollapsed;
      if (!currentCollapsed && expandedChatWidth <= chatPaneMinWidth) {
        nextCollapsed = true;
        sidebarAutoCollapsedRef.current = true;
        setSidebarCollapsed(true);
      } else if (currentCollapsed && sidebarAutoCollapsedRef.current && expandedChatWidth > chatPaneMinWidth) {
        nextCollapsed = false;
        sidebarAutoCollapsedRef.current = false;
        setSidebarCollapsed(false);
      }
      currentCollapsed = nextCollapsed;
      setArtifactPaneWidth(Math.round(clampArtifactPaneWidth(window.innerWidth - pendingClientX, nextCollapsed)));
    };
    const move = (moveEvent: PointerEvent) => {
      if (moveEvent.buttons === 0) {
        finish();
        return;
      }
      pendingClientX = moveEvent.clientX;
      if (resizeFrame === null) resizeFrame = window.requestAnimationFrame(applyResize);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    window.addEventListener("mouseup", finish);
    window.addEventListener("blur", finish);
  }

  function resizeArtifactByKeyboard(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (artifactFullscreen || window.innerWidth < artifactSplitPaneMinViewport || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? 24 : -24;
    const nextWidth = artifactPaneWidth + delta;
    const expandedChatWidth = window.innerWidth - 278 - nextWidth;
    let nextCollapsed = sidebarCollapsed;
    if (!sidebarCollapsed && expandedChatWidth <= chatPaneMinWidth) {
      nextCollapsed = true;
      sidebarAutoCollapsedRef.current = true;
      setSidebarCollapsed(true);
    } else if (sidebarCollapsed && sidebarAutoCollapsedRef.current && expandedChatWidth > chatPaneMinWidth) {
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
    if (sidebarAutoCollapsedRef.current) {
      sidebarAutoCollapsedRef.current = false;
      setSidebarCollapsed(false);
    }
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
    if (!artifactOpen || artifactPaneViews.has(mainView)) return;
    if (artifactHistoryOpenRef.current) window.history.back();
    else finishCloseArtifact();
  }, [artifactOpen, finishCloseArtifact, mainView]);

  useEffect(() => {
    const onPopState = () => {
      if (artifactHistoryOpenRef.current) finishCloseArtifact();
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [finishCloseArtifact]);

  const theme = workspace.settings?.theme ?? "light";
  const isAdmin = workspace.authSession?.user.role === "admin";
  const artifactPaneVisible = artifactOpen && artifactPaneViews.has(mainView);
  const activeRuntime = workspace.activeRuntime;
  const activeRun = workspace.activeRun;
  const cumulativeUsageByTurnSetId = useMemo(
    () => cumulativeSessionUsageByTurnSet(activeRuntime.turnSets, activeRuntime.snapshots),
    [activeRuntime.snapshots, activeRuntime.turnSets],
  );
  const activeProject = workspace.projects.find((project) => project.id === workspace.activeProjectId) ?? null;
  const restoringActiveConversation = Boolean(
    workspace.activeConversationId && !activeRuntime.loaded && !activeRuntime.error,
  );
  const showNewConversationWelcome = activeRuntime.turnSets.length === 0 && (
    !workspace.activeConversationId || activeRuntime.loaded
  );

  useEffect(() => {
    if (!activeRun) {
      progressRunIdRef.current = null;
      progressPlanIdRef.current = null;
      return;
    }
    const terminal = isTerminalRunStatus(activeRun.status);
    const planId = activeRun.plan?.id ?? null;
    if (progressRunIdRef.current !== activeRun.runId) {
      progressRunIdRef.current = activeRun.runId;
      progressPlanIdRef.current = planId;
      setProgressOpen(Boolean(planId) && !terminal);
      return;
    }
    if (planId && progressPlanIdRef.current !== planId) {
      progressPlanIdRef.current = planId;
      if (!terminal) setProgressOpen(true);
    }
    if (terminal) {
      setProgressOpen(false);
    }
  }, [activeRun?.plan?.id, activeRun?.runId, activeRun?.status]);
  const accountProviders = workspace.providers
    .filter((provider) => provider.id !== "mock")
    .sort((left, right) => (accountProviderOrder[left.id] ?? Number.MAX_SAFE_INTEGER) - (accountProviderOrder[right.id] ?? Number.MAX_SAFE_INTEGER)
      || left.displayName.localeCompare(right.displayName));
  const selectedAdminSettingsModel = adminSettingsModels.find((model) => model.modelKey === adminSettingsModelKey) ?? null;
  const adminInitialProviders = adminInitialExecution
    && !accountProviders.some((provider) => provider.id === adminInitialExecution.providerId)
    ? [
        ...workspace.providers.filter((provider) => provider.id === adminInitialExecution.providerId),
        ...accountProviders,
      ]
    : accountProviders;
  const adminInitialExecutionModels = adminInitialExecution
    ? (
        workspace.providerModels[adminInitialExecution.providerId]
        ?? (workspace.settings?.execution.providerId === adminInitialExecution.providerId ? workspace.models : [])
      )
    : [];
  const selectedAdminInitialExecutionModel = adminInitialExecutionModels.find(
    (model) => model.modelKey === adminInitialExecution?.modelKey,
  ) ?? null;
  const adminInitialEffortOptions = selectedAdminInitialExecutionModel?.capabilities.effortOptions ?? [];
  const adminDefaultContextUsageRatio = (
    selectedAdminSettingsModel as AdminProviderModelWithContextUsageRatio | null
  )?.defaultContextUsageRatio ?? 0.75;

  useEffect(() => {
    if (!isAdmin || !providerMenuOpen) return;
    const controller = new AbortController();
    api.adminProviders.list(controller.signal)
      .then(async (providers) => {
        const models = await Promise.all(
          providers.map(async (provider) => [
            provider.id,
            await api.adminProviders.listModels(provider.id, controller.signal),
          ] as const),
        );
        if (controller.signal.aborted) return;
        setAdminFooterProviders(providers);
        setAdminFooterModels(Object.fromEntries(models));
      })
      .catch((error) => {
        if (!controller.signal.aborted) showToast(error instanceof Error ? error.message : "Provider 설정을 불러오지 못했습니다.");
      });
    return () => controller.abort();
  }, [isAdmin, providerMenuOpen]);

  const setAdminFooterProviderEnabled = async (providerId: string, enabled: boolean) => {
    setAdminFooterBusyId(providerId);
    try {
      const provider = await api.adminProviders.updateAvailability(providerId, enabled);
      const models = await api.adminProviders.listModels(providerId);
      setAdminFooterProviders((items) => items.map((item) => item.id === providerId ? provider : item));
      setAdminFooterModels((items) => ({ ...items, [providerId]: models }));
      await workspace.refreshProviderCatalog();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Provider 설정을 변경하지 못했습니다.");
    } finally {
      setAdminFooterBusyId(null);
    }
  };

  const setAdminFooterModelEnabled = async (providerId: string, modelKey: string, enabled: boolean) => {
    const busyId = `${providerId}:${modelKey}`;
    setAdminFooterBusyId(busyId);
    try {
      await api.adminProviders.updateModel(providerId, modelKey, { enabled });
      const [providers, models] = await Promise.all([
        api.adminProviders.list(),
        api.adminProviders.listModels(providerId),
      ]);
      setAdminFooterProviders(providers);
      setAdminFooterModels((items) => ({ ...items, [providerId]: models }));
      await workspace.refreshProviderCatalog();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Model 설정을 변경하지 못했습니다.");
    } finally {
      setAdminFooterBusyId(null);
    }
  };

  useEffect(() => {
    if (mainView !== "settings" || settingsSection !== "admin" || !isAdmin) return;
    const controller = new AbortController();
    setAdminInitialExecutionBusy(true);
    setAdminInitialExecutionError(null);
    api.adminProviders.getInitialExecution(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setAdminInitialExecution(value.execution);
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setAdminInitialExecutionError(error instanceof Error ? error.message : "최초 실행 기본값을 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setAdminInitialExecutionBusy(false);
      });
    return () => controller.abort();
  }, [isAdmin, mainView, settingsSection]);

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
    const ratio = selectedAdminSettingsModel?.capabilities.context_compaction_threshold
      ?? selectedAdminSettingsModel?.capabilities.contextCompactionThreshold
      ?? adminDefaultContextUsageRatio;
    setAdminMaxTokens(typeof value === "number" ? value.toLocaleString("en-US") : "");
    setAdminContextUsagePercent(typeof ratio === "number" ? String(Math.round(ratio * 100)) : "75");
    setAdminOutputTokens(
      selectedAdminSettingsModel?.configuredMaxOutputTokens
      ?? selectedAdminSettingsModel?.defaultMaxOutputTokens
      ?? 0,
    );
  }, [adminDefaultContextUsageRatio, selectedAdminSettingsModel]);

  const parsedAdminContextWindow = Number(adminMaxTokens.replaceAll(",", ""));
  const parsedAdminContextUsagePercent = Number(adminContextUsagePercent);
  const adminBaseInputContext = (() => {
    if (!Number.isSafeInteger(parsedAdminContextWindow) || parsedAdminContextWindow < 1) return null;
    const reservedOutput = adminOutputTokens > 0
      ? adminOutputTokens
      : Math.max(512, Math.min(4_096, Math.floor(parsedAdminContextWindow / 8)));
    const safetyMargin = Math.max(256, Math.min(4_096, Math.floor(parsedAdminContextWindow / 20)));
    return Math.max(256, parsedAdminContextWindow - reservedOutput - safetyMargin);
  })();
  const adminBaseCompactionThreshold = (
    adminBaseInputContext !== null
    && Number.isFinite(parsedAdminContextUsagePercent)
    && parsedAdminContextUsagePercent >= 1
    && parsedAdminContextUsagePercent <= 100
  )
    ? Math.max(1, Math.floor(adminBaseInputContext * parsedAdminContextUsagePercent / 100))
    : null;

  const saveAdminMaxTokens = async () => {
    if (!selectedAdminSettingsModel) return;
    if (selectedAdminSettingsModel.contextPolicyLocked) {
      setAdminSettingsError("Codex Context는 서비스 정책값으로 고정됩니다.");
      return;
    }
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
      const updated = await api.adminProviders.updateModel(adminSettingsProviderId, selectedAdminSettingsModel.modelKey, { capabilities });
      setAdminSettingsModels((models) => models.map((model) => model.modelKey === updated.modelKey ? updated : model));
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
      const updated = await api.adminProviders.updateModel(adminSettingsProviderId, selectedAdminSettingsModel.modelKey, { capabilities });
      setAdminSettingsModels((models) => models.map((model) => model.modelKey === updated.modelKey ? updated : model));
    } catch (error) {
      setAdminSettingsError(error instanceof Error ? error.message : "최대 토큰을 초기화하지 못했습니다.");
    } finally {
      setAdminSettingsBusy(false);
    }
  };
  const saveAdminContextUsagePercent = async (nextPercent = parsedAdminContextUsagePercent) => {
    if (!selectedAdminSettingsModel) return;
    if (selectedAdminSettingsModel.contextPolicyLocked) {
      setAdminSettingsError("Codex 자동 압축 시작 비율은 서비스 정책값으로 고정됩니다.");
      return;
    }
    if (!Number.isInteger(nextPercent) || nextPercent < 1 || nextPercent > 100) {
      setAdminSettingsError("자동 압축 시작 비율은 1% 이상 100% 이하의 정수로 입력해 주세요.");
      return;
    }
    setAdminSettingsBusy(true);
    setAdminSettingsError(null);
    try {
      const capabilities: Record<string, unknown> = {
        ...selectedAdminSettingsModel.capabilities,
        context_compaction_threshold: nextPercent / 100,
      };
      delete capabilities.contextCompactionThreshold;
      const updated = await api.adminProviders.updateModel(adminSettingsProviderId, selectedAdminSettingsModel.modelKey, { capabilities });
      setAdminSettingsModels((models) => models.map((model) => model.modelKey === updated.modelKey ? updated : model));
      setAdminContextUsagePercent(String(nextPercent));
    } catch (error) {
      setAdminSettingsError(error instanceof Error ? error.message : "자동 압축 시작 비율을 저장하지 못했습니다.");
    } finally {
      setAdminSettingsBusy(false);
    }
  };
  const resetAdminContextUsagePercent = async () => {
    if (!selectedAdminSettingsModel) return;
    await saveAdminContextUsagePercent(Math.round(adminDefaultContextUsageRatio * 100));
  };
  const saveAdminOutputTokens = async (value = adminOutputTokens) => {
    if (!selectedAdminSettingsModel?.maxOutputTokens) return;
    if (!Number.isSafeInteger(value) || value < 1 || value > selectedAdminSettingsModel.maxOutputTokens) {
      setAdminSettingsError(`출력 토큰 상한은 1부터 모델 최대 ${selectedAdminSettingsModel.maxOutputTokens.toLocaleString()} 사이여야 합니다.`);
      return;
    }
    setAdminSettingsBusy(true);
    setAdminSettingsError(null);
    try {
      const capabilities: Record<string, unknown> = {
        ...selectedAdminSettingsModel.capabilities,
        configured_max_output_tokens: value,
      };
      delete capabilities.configuredMaxOutputTokens;
      const updated = await api.adminProviders.updateModel(
        adminSettingsProviderId,
        selectedAdminSettingsModel.modelKey,
        { capabilities },
      );
      setAdminSettingsModels((models) => models.map((model) => model.modelKey === updated.modelKey ? updated : model));
    } catch (error) {
      setAdminSettingsError(error instanceof Error ? error.message : "출력 토큰 상한을 저장하지 못했습니다.");
    } finally {
      setAdminSettingsBusy(false);
    }
  };
  const resetAdminOutputTokens = () => {
    const defaultValue = selectedAdminSettingsModel?.defaultMaxOutputTokens;
    if (!defaultValue) return;
    setAdminOutputTokens(defaultValue);
    void saveAdminOutputTokens(defaultValue);
  };
  const selectAdminInitialProvider = (providerId: string) => {
    const models = workspace.providerModels[providerId] ?? [];
    const model = models.find((item) => item.isDefault) ?? models[0];
    if (!model) return;
    const efforts = model.capabilities.effortOptions;
    const effortId = efforts.find((item) => item.id === "auto")?.id ?? efforts[0]?.id ?? null;
    setAdminInitialExecution({ providerId, modelKey: model.modelKey, effortId });
  };
  const selectAdminInitialModel = (modelKey: string) => {
    if (!adminInitialExecution) return;
    const model = adminInitialExecutionModels.find((item) => item.modelKey === modelKey);
    if (!model) return;
    const effortIds = model.capabilities.effortOptions.map((item) => item.id);
    const effortId = adminInitialExecution.effortId && effortIds.includes(adminInitialExecution.effortId)
      ? adminInitialExecution.effortId
      : (effortIds.find((item) => item === "auto") ?? effortIds[0] ?? null);
    setAdminInitialExecution({ ...adminInitialExecution, modelKey, effortId });
  };
  const saveAdminInitialExecution = async () => {
    if (!adminInitialExecution) return;
    setAdminInitialExecutionBusy(true);
    setAdminInitialExecutionError(null);
    try {
      const updated = await api.adminProviders.updateInitialExecution(adminInitialExecution);
      setAdminInitialExecution(updated.execution);
    } catch (error) {
      setAdminInitialExecutionError(error instanceof Error ? error.message : "최초 실행 기본값을 저장하지 못했습니다.");
    } finally {
      setAdminInitialExecutionBusy(false);
    }
  };
  const candidateModelOptions = accountProviders.flatMap((provider) =>
    (workspace.providerModels[provider.id] ?? [])
      .map((model) => ({
        id: `${provider.id}:${model.modelKey}`,
        label: `${model.displayName} · ${provider.displayName}`,
        triggerLabel: model.displayName,
        providerId: provider.id,
        providerLabel: provider.displayName,
        modelKey: model.modelKey,
        modelLabel: model.displayName,
        effortOptions: model.capabilities.effortOptions,
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
        top: rect.top - 5,
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
  const runIsActive = Boolean(
    activeRun && !isTerminalRunStatus(activeRun.status),
  );
  const runIsPaused = activeRun?.status === "paused";
  const composerHasPayload = Boolean(draft.trim() || workspace.composerAttachments.length > 0);
  const composerShowsStop = Boolean(runIsActive && !composerHasPayload);
  const queuedComposerCommands = useMemo(
    () => (activeRun?.pendingCommands ?? [])
      .filter((command): command is RunCommand => command.type === "queue_next" && command.status === "queued")
      .sort((left, right) => (left.queuePosition ?? Number.MAX_SAFE_INTEGER) - (right.queuePosition ?? Number.MAX_SAFE_INTEGER)),
    [activeRun?.pendingCommands],
  );
  const shouldNudgeFileMode = mainView === "chat"
    && workspace.settings?.outputMode === "file"
    && draft.trim().length === 0
    && activeRun?.outputIntent?.fileCreationRequested === false;
  const conversationFollow = useConversationAutoFollow(
    runIsActive,
    workspace.activeConversationId,
    activeRuntime.loaded,
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
  const artifactDownloadVersion = artifactVersion?.version ?? artifactSummary?.currentVersion ?? null;
  const artifactPreviewUrl = artifactVersion?.previewUrl
    ?? (artifactSummary && artifactVersion?.mimeType === "application/pdf"
      ? `/api/artifacts/${encodeURIComponent(artifactSummary.id)}/preview?version=${encodeURIComponent(String(artifactVersion.version))}`
      : null);
  const sharedViewerToken = sharedTokenFromPath(window.location.pathname);
  const sharedArtifactTarget = sharedArtifactFromLocation();

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const dock = dockAreaRef.current;
    const pane = dock?.parentElement;
    if (!dock || !pane) return;
    let followFrame: number | null = null;
    const updateDockHeight = () => {
      pane.style.setProperty("--dock-height", `${Math.ceil(dock.getBoundingClientRect().height)}px`);
      if (followFrame !== null) window.cancelAnimationFrame(followFrame);
      followFrame = window.requestAnimationFrame(() => {
        followFrame = null;
        conversationFollow.follow(true);
      });
    };
    updateDockHeight();
    const observer = new ResizeObserver(updateDockHeight);
    observer.observe(dock);
    return () => {
      observer.disconnect();
      if (followFrame !== null) window.cancelAnimationFrame(followFrame);
      pane.style.removeProperty("--dock-height");
    };
  }, [conversationFollow.follow, mainView, workspace.authSession?.user.id]);

  useEffect(() => {
    if (!workspace.notice) return;
    setToast(workspace.notice);
    workspace.clearNotice();
  }, [workspace.clearNotice, workspace.notice]);

  useEffect(() => {
    if (!workspace.authSession) {
      setNotificationOpen(false);
      setNotificationTab("notifications");
      setNotifications([]);
      setAnnouncements([]);
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
          const [page, announcementPage] = await Promise.all([
            api.notifications.list(false, 50, 0, controller.signal),
            api.notifications.listAnnouncements(50, 0, controller.signal),
          ]);
          if (controller.signal.aborted) return;
          setNotifications(page.items);
          setAnnouncements(announcementPage.items);
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
    if (sessionScrollbarIdleTimerRef.current !== null) {
      window.clearTimeout(sessionScrollbarIdleTimerRef.current);
    }
  }, []);

  function handleSessionListScroll(event: ReactUIEvent<HTMLDivElement>) {
    const list = event.currentTarget;
    list.classList.add("is-scrolling");
    if (sessionScrollbarIdleTimerRef.current !== null) {
      window.clearTimeout(sessionScrollbarIdleTimerRef.current);
    }
    sessionScrollbarIdleTimerRef.current = window.setTimeout(() => {
      list.classList.remove("is-scrolling");
      sessionScrollbarIdleTimerRef.current = null;
    }, 650);
  }

  useEffect(() => {
    setSessionDeleteArmedId(null);
  }, [sessionMenuId]);

  useEffect(() => {
    setBulkSessionDeleteArmed(false);
  }, [bulkSessionIds, bulkSessionMode]);

  const startNewConversation = useCallback(() => {
    setMainView("chat");
    setSidebarOpen(false);
    setComposerTrigger(null);
    setComposerSuggestions([]);
    setSuggestionIndex(0);
    setSuggestionsLoading(false);
    workspace.startNewConversation();
    window.requestAnimationFrame(() => composerInputRef.current?.focus());
  }, [workspace.startNewConversation]);

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
    if (composerTrigger?.trigger === trigger) {
      setComposerTrigger(null);
      setComposerSuggestions([]);
      setSuggestionIndex(0);
      setSuggestionsLoading(false);
      window.requestAnimationFrame(() => input?.focus());
      return;
    }
    const existingTrigger = findComposerTrigger(draft, caret);
    if (existingTrigger?.trigger === trigger) {
      setComposerTrigger(existingTrigger);
      window.requestAnimationFrame(() => input?.focus());
      return;
    }
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
    await workspace.renameConversation(workspace.activeConversation.id, nextTitle);
    titleCommitRef.current = false;
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
    const resetFileModeAfterSend = workspace.settings?.outputMode === "file";
    const mode = await workspace.sendMessage(
      value,
      queueNext,
      promptReferences,
      targetOutputTokens ?? undefined,
    );
    if (!mode) return;
    if (resetFileModeAfterSend) void workspace.selectOutputMode("auto");
    setDraft("");
    setSelectedReferences([]);
    setTargetOutputTokens(defaultArtifactOutputTokens);
    setComposerTrigger(null);
    setComposerSuggestions([]);
  };

  const controlRun = async (action: RunControlAction, targetId?: string) => {
    if (!activeRun) return;
    await workspace.runAction(activeRun.runId, action, targetId);
  };

  const controlPendingCommand = async (action: PendingCommandAction, commandId: string) => {
    if (!activeRun || pendingCommandAction) return;
    setPendingCommandAction({ id: commandId, action });
    await workspace.runPendingCommandAction(activeRun.runId, action, commandId);
    setPendingCommandAction(null);
  };

  const copyTool = async (execution: ToolExecution) => {
    const requestText = execution.input
      ? JSON.stringify(execution.input, null, 2)
      : execution.inputSummary.join("\n") || "입력 없음";
    const resultText = execution.result
      ? JSON.stringify(execution.result, null, 2)
      : execution.error || execution.resultSummary.join("\n") || "결과 없음";
    try {
      await copyText([`[${execution.toolName}]`, "", "도구 요청", requestText, "", "도구 결과", resultText].join("\n"));
    } catch {
      showToast("Tool 메시지를 복사하지 못했습니다.");
    }
  };

  const openArtifact = async (artifact: ArtifactSummary) => {
    if (artifactSaveBusy) {
      showToast("Artifact 저장이 끝난 뒤 다른 문서를 열어 주세요.");
      return;
    }
    if (window.innerWidth >= 1024 && window.innerWidth < 1400) {
      if (!sidebarCollapsed) {
        sidebarAutoCollapsedRef.current = true;
        setSidebarCollapsed(true);
      }
      setArtifactPaneWidth((current) => Math.round(clampArtifactPaneWidth(current, true)));
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
      const [summary, initialVersion, savedDraft] = await Promise.all([
        api.artifacts.get(artifact.id),
        api.artifacts.getVersion(artifact.id, artifact.currentVersion),
        api.artifacts.getDraft(artifact.id),
      ]);
      const version = summary.currentVersion === initialVersion.version
        ? initialVersion
        : await api.artifacts.getVersion(artifact.id, summary.currentVersion);
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
    const hasActiveRun = Boolean(activeRun && !isTerminalRunStatus(activeRun.status));
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
          idempotencyKey: createClientId(),
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
    if (!artifactSummary || artifactDownloadVersion === null) return;
    try {
      const download = await api.artifacts.downloadVersion(artifactSummary.id, artifactDownloadVersion);
      const url = URL.createObjectURL(download.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = download.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
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
      url.searchParams.set("artifact", artifactSummary.id);
      url.searchParams.set("version", String(artifactDownloadVersion ?? artifactSummary.currentVersion));
      await copyText(url.toString());
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

    if (notification.deepLink.target === "admin" && workspace.authSession?.user.role === "admin") {
      setMainView("admin");
      setNotificationBusyId(null);
      return;
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

  const openAnnouncementInHelp = (announcementId: string | null) => {
    setHelpAnnouncementId(announcementId);
    setNotificationOpen(false);
    setMainView("help");
    setSidebarOpen(false);
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
  if (sharedViewerToken) {
    return (
      <SharedSnapshotViewer
        artifactId={sharedArtifactTarget.artifactId}
        artifactVersion={sharedArtifactTarget.artifactVersion}
        token={sharedViewerToken}
        theme={sharedThemeFromLocation()}
      />
    );
  }
  const streamLabel = backendConnectionState === "offline"
    ? "연결 끊김"
    : backendConnectionState === "recovering"
      ? "복구 확인 중"
      : backendConnectionState === "checking"
        ? "연결 확인 중"
        : activeRuntime.streamState === "reconnecting"
          ? "재연결 중"
          : activeRuntime.streamState === "connecting"
            ? "연결 중"
            : "Online";
  const connectionIndicatorState = backendConnectionState === "online"
    ? activeRuntime.streamState
    : backendConnectionState;

  return (
    <div
      className={`app-shell ${artifactPaneVisible ? "has-artifact" : ""} ${sidebarCollapsed ? "is-sidebar-collapsed" : ""} ${artifactResizing ? "is-artifact-resizing" : ""} ${theme === "dark" ? "theme-dark" : ""}`}
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
        <nav
          className="sidebar-collapsed-navigation"
          aria-label="축소된 Lumina 탐색"
          onMouseDown={(event) => {
            if (event.detail > 1 && event.target === event.currentTarget) event.preventDefault();
          }}
          onDoubleClick={(event) => {
            if (event.target !== event.currentTarget) return;
            event.preventDefault();
            sidebarAutoCollapsedRef.current = false;
            setSidebarCollapsed(false);
          }}
        >
          <button type="button" aria-label="사이드바 펼치기" data-tooltip="사이드바 펼치기" onClick={() => { sidebarAutoCollapsedRef.current = false; setSidebarCollapsed(false); }}><PanelLeftOpen size={17} /></button>
          <button type="button" aria-label="새 채팅" data-tooltip="새 채팅" onClick={startNewConversation}><SquarePen size={18} /></button>
          {navigation.map(({ id, label, icon: Icon }) => (
            <button className={mainView === id ? "is-active" : ""} type="button" aria-label={label} data-tooltip={label} key={id} onClick={() => setMainView(id)}><Icon size={18} /></button>
          ))}
        </nav>
        <header className="sidebar-header">
          <a className="wordmark" href="#top" aria-label="Lumina 홈" onClick={() => setMainView("chat")}><Sparkles size={20} strokeWidth={1.7} /><span>Lumina</span></a>
          <div className="sidebar-header-actions">
            <button type="button" aria-label="대화 검색" onClick={() => setConversationSearchOpen(true)}><Search size={17} /></button>
            <button className="tooltip-control" type="button" aria-label={theme === "dark" ? "Light 테마로 변경" : "Dark 테마로 변경"} data-tooltip={theme === "dark" ? "Light 테마" : "Dark 테마"} onClick={() => void workspace.toggleTheme()}>
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <button className="tooltip-control" type="button" aria-label="사용 안내 열기" data-tooltip="사용 안내" onClick={() => openAnnouncementInHelp(null)}><Info size={17} /></button>
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
              <span>{bulkSessionMode ? `${likedSessionsOnly ? "좋아요 · " : ""}${bulkSessionIds.size}개 선택` : likedSessionsOnly ? "좋아요" : "최근 항목"}</span>
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
                  <button className={`liked-sessions-filter session-heading-action tooltip-control ${likedSessionsOnly ? "is-active" : ""}`} type="button" aria-label={likedSessionsOnly ? "전체 보기" : "좋아요만 보기"} aria-pressed={likedSessionsOnly} data-tooltip={likedSessionsOnly ? "전체 보기" : "좋아요만"} onClick={() => setLikedSessionsOnly((active) => !active)}><Heart size={14} fill={likedSessionsOnly ? "currentColor" : "none"} /></button>
                  <button className="bulk-session-open tooltip-control" type="button" aria-label="세션 관리" data-tooltip="세션 관리" disabled={workspace.conversations.length === 0} onClick={() => { setBulkSessionMode(true); setBulkSessionIds(new Set()); setSessionMenuId(null); setMoveMenuId(null); }}><CheckCheck size={14} /></button>
                </div>
              )}
            </div>
            <div className="session-list" onScroll={handleSessionListScroll}>
              {workspace.conversations.filter((conversation) => !likedSessionsOnly || conversation.isLiked).map((conversation) => (
                <div className={`session-item ${conversation.id === workspace.activeConversationId && !bulkSessionMode ? "is-selected" : ""} ${bulkSessionMode ? "is-bulk" : ""}`} key={conversation.id}>
                  {bulkSessionMode ? (
                    <button className="session-row" type="button" onClick={() => {
                      setBulkSessionIds((current) => {
                        const next = new Set(current);
                        if (next.has(conversation.id)) next.delete(conversation.id);
                        else next.add(conversation.id);
                        return next;
                      });
                    }} aria-pressed={bulkSessionIds.has(conversation.id)}>
                      <span className={`bulk-session-checkbox ${bulkSessionIds.has(conversation.id) ? "is-checked" : ""}`}>{bulkSessionIds.has(conversation.id) && <Check size={11} />}</span>
                      <span className={isUntitledConversation(conversation.title) ? "is-untitled" : undefined}>{isUntitledConversation(conversation.title) ? "제목 없음" : conversation.title}</span>
                    </button>
                  ) : (
                    <>
                      <button className="session-like-button" type="button" aria-label={`${conversation.title} ${conversation.isLiked ? "좋아요 취소" : "좋아요"}`} aria-pressed={conversation.isLiked} onClick={() => void workspace.toggleLikedConversation(conversation.id)}>
                        {conversation.isLiked ? <Heart className="session-like" size={14} fill="currentColor" /> : conversation.lastRunStatus === "running" ? <LoaderCircle className="is-running" size={14} /> : conversation.lastRunStatus === "queued" ? <Clock3 size={14} /> : conversation.lastRunStatus === "input" ? <MessageCircleQuestion size={14} /> : conversation.lastRunStatus === "failed" ? <AlertCircle size={14} /> : conversation.isFavorite ? <Pin className="session-pin" size={14} /> : <MessageCircle size={14} />}
                      </button>
                      <button className="session-row session-title-button" type="button" onClick={() => {
                        setSessionTitleEditing(false);
                        setMainView("chat");
                        workspace.selectConversation(conversation.id);
                        setSidebarOpen(false);
                      }}>
                        <span className={isUntitledConversation(conversation.title) ? "is-untitled" : undefined}>{isUntitledConversation(conversation.title) ? "제목 없음" : conversation.title}</span>
                      </button>
                    </>
                  )}
                  {!bulkSessionMode && <button className="session-options-button" type="button" aria-label={`${conversation.title} 옵션`} aria-expanded={sessionMenuId === conversation.id} onClick={(event) => {
                    event.stopPropagation();
                    setAccountMenuOpen(false);
                    setMoveMenuId(null);
                    setSessionMenuId((current) => current === conversation.id ? null : conversation.id);
                  }}><MoreVertical size={15} /></button>}
                  {!bulkSessionMode && sessionMenuId === conversation.id && (
                    <div className="session-options-menu" role="menu" onClick={(event) => event.stopPropagation()}>
                      <button type="button" role="menuitem" onClick={() => { setSessionMenuId(null); void workspace.toggleFavoriteConversation(conversation.id); }}>{conversation.isFavorite ? <PinOff size={14} /> : <Pin size={14} />} {conversation.isFavorite ? "즐겨찾기 해제" : "즐겨찾기"}</button>
                      <button type="button" role="menuitem" onClick={() => { setSessionMenuId(null); void workspace.toggleLikedConversation(conversation.id); }}><Heart size={14} fill={conversation.isLiked ? "currentColor" : "none"} /> {conversation.isLiked ? "좋아요 취소" : "좋아요"}</button>
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
                      <button className={`is-danger ${sessionDeleteArmedId === conversation.id ? "is-armed" : ""}`} type="button" role="menuitem" disabled={sessionDeleteBusyId === conversation.id} onClick={() => void deleteSessionFromMenu(conversation.id)}>{sessionDeleteBusyId === conversation.id ? <LoaderCircle className="is-running" size={14} /> : sessionDeleteArmedId === conversation.id ? <AlertCircle size={14} /> : <Trash2 size={14} />} {sessionDeleteArmedId === conversation.id ? "삭제 확인" : "삭제"}</button>
                    </div>
                  )}
                </div>
              ))}
              {!workspace.loadingWorkspace && workspace.conversations.filter((conversation) => !likedSessionsOnly || conversation.isLiked).length === 0 && <p className="sidebar-empty">{likedSessionsOnly ? "좋아요한 채팅이 없습니다." : "새 채팅을 만들어 시작하세요."}</p>}
            </div>
          </section>
        </div>

        <footer className="sidebar-footer" onClick={(event) => event.stopPropagation()}>
          {accountMenuOpen && (
            <div className="account-menu" role="menu" aria-label="계정 설정">
              {isAdmin && <button className="account-menu-admin" type="button" role="menuitem" onClick={openAdmin}><ShieldCheck size={15} /><span><strong>시스템 관리</strong></span><kbd aria-hidden="true">Ctrl + Shift + X</kbd></button>}
              <button className="account-menu-shortcut" type="button" role="menuitem" onClick={openSettings}><Settings size={15} /><span><strong>설정</strong></span><kbd aria-hidden="true">Ctrl + Shift + S</kbd></button>
              {isAdmin && <>
                <div className="account-menu-separator" />
                <button className="account-menu-provider-trigger" type="button" role="menuitem" aria-expanded={providerMenuOpen} onClick={() => setProviderMenuOpen((open) => !open)}>
                  <Bot size={15} />
                  <span><strong>Provider</strong></span>
                  {providerMenuOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                {providerMenuOpen && (
                  <div className="account-provider-list" role="group" aria-label="사용 가능한 Provider 관리">
                    {[...adminFooterProviders].sort((left, right) => (accountProviderOrder[left.id] ?? Number.MAX_SAFE_INTEGER) - (accountProviderOrder[right.id] ?? Number.MAX_SAFE_INTEGER) || left.displayName.localeCompare(right.displayName)).map((provider) => {
                      const providerIsOpen = providerModelMenuId === provider.id;
                      const providerModels = adminFooterModels[provider.id] ?? [];
                      const providerBusy = adminFooterBusyId === provider.id;
                      return (
                        <div className="account-provider-group" key={provider.id}>
                          <div className="account-provider-row">
                            <button className={`account-provider-checkbox ${provider.enabled ? "is-checked" : ""}`} type="button" role="checkbox" aria-checked={provider.enabled} aria-label={`${provider.displayName} 사용자 사용 ${provider.enabled ? "중지" : "허용"}`} disabled={providerBusy} onClick={() => void setAdminFooterProviderEnabled(provider.id, !provider.enabled)}>
                              {provider.enabled && <Check size={12} strokeWidth={3} />}
                            </button>
                            <button className="account-provider-toggle" type="button" role="menuitem" aria-expanded={providerIsOpen} onClick={() => setProviderModelMenuId((current) => current === provider.id ? null : provider.id)}>
                              <span><strong>{provider.displayName}</strong></span>
                              {providerIsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            </button>
                          </div>
                          {providerIsOpen && (
                            <div className="account-model-checklist" role="group" aria-label={`${provider.displayName} 사용자 모델 허용 목록`}>
                              {providerModels.map((model) => {
                                const busy = adminFooterBusyId === `${provider.id}:${model.modelKey}`;
                                return (
                                  <button type="button" role="menuitemcheckbox" aria-checked={model.enabled} disabled={busy} key={model.modelKey} onMouseEnter={(event) => scheduleModelNameTooltip(event, model.displayName)} onMouseLeave={hideModelNameTooltip} onClick={() => { hideModelNameTooltip(); void setAdminFooterModelEnabled(provider.id, model.modelKey, !model.enabled); }}>
                                    <span className={`account-model-checkbox ${model.enabled ? "is-checked" : ""}`}>{model.enabled && <Check size={11} strokeWidth={3} />}</span>
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
              </>}
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
            <span className={`connection-state state-${connectionIndicatorState}`}>{streamLabel} <i /></span>
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
                <section className="notification-panel" aria-label="알림과 공지사항">
                  <header>
                    <div className="notification-tabs" role="tablist" aria-label="받은 소식 분류">
                      <button
                        id="notification-tab-notifications"
                        type="button"
                        role="tab"
                        aria-controls="notification-panel-notifications"
                        aria-selected={notificationTab === "notifications"}
                        onClick={() => setNotificationTab("notifications")}
                      >
                        알림
                        {notificationUnreadCount > 0 && <span>{notificationUnreadCount > 99 ? "99+" : notificationUnreadCount}</span>}
                      </button>
                      <button
                        id="notification-tab-announcements"
                        type="button"
                        role="tab"
                        aria-controls="notification-panel-announcements"
                        aria-selected={notificationTab === "announcements"}
                        onClick={() => {
                          setNotificationDeleteArmedId(null);
                          setNotificationTab("announcements");
                        }}
                      >
                        공지사항
                      </button>
                    </div>
                    {notificationTab === "notifications" && (
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
                    )}
                  </header>
                  {notificationTab === "notifications" ? (
                  <div
                    className="notification-list"
                    id="notification-panel-notifications"
                    role="tabpanel"
                    aria-labelledby="notification-tab-notifications"
                  >
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
                  ) : (
                    <div
                      className="notification-list announcement-list"
                      id="notification-panel-announcements"
                      role="tabpanel"
                      aria-labelledby="notification-tab-announcements"
                    >
                      {!notificationLoading && notificationError && <div className="notification-state is-error"><AlertCircle size={15} /> {notificationError}</div>}
                      {!notificationLoading && !notificationError && announcements.length === 0 && <div className="announcement-empty"><Megaphone size={18} /><strong>게시된 공지사항이 없습니다.</strong><span>새 공지가 등록되면 이곳에서 확인할 수 있습니다.</span></div>}
                      {announcements.map((announcement) => <button className="announcement-item" type="button" key={announcement.id} onClick={() => openAnnouncementInHelp(announcement.id)}><Megaphone size={16} aria-hidden="true" /><span><strong>{announcement.title}</strong><p>{announcement.body}</p><small>{announcement.author?.displayName || announcement.author?.loginId || "관리자"} · {formatNotificationTime(announcement.createdAt)}</small></span></button>)}
                    </div>
                  )}
                </section>
              )}
            </div>
          </div>
        </header>

        <ConversationQuestionNavigator
          turnSets={activeRuntime.turnSets}
          theme={theme}
          scrollContainerRef={conversationFollow.containerRef}
          onNavigateStart={conversationFollow.onUserIntent}
        />

        <div
          className="conversation-scroll"
          ref={conversationFollow.containerRef}
          tabIndex={-1}
          onKeyDown={selectAllInRegion}
          onScroll={conversationFollow.onScroll}
          onWheel={(event) => conversationFollow.onWheel(event.deltaY)}
          onPointerDown={(event) => {
            conversationFollow.onPointerDown();
            focusSelectableRegion(event);
          }}
          onTouchStart={conversationFollow.onPointerDown}
          onDoubleClick={() => { if (artifactOpen) closeArtifact(); }}
        >
          <main className="conversation" aria-label="대화 내용" aria-busy={restoringActiveConversation}>
            {restoringActiveConversation && <div className="conversation-loading"><LoaderCircle className="is-running" size={17} /> 대화를 불러오고 있습니다.</div>}
            {activeRuntime.error && <div className="conversation-error"><AlertCircle size={16} /> {activeRuntime.error}</div>}
            {showNewConversationWelcome && (
              <div className="conversation-empty"><Sparkles size={24} /><h2>무엇을 함께 진행할까요?</h2><p>요청을 보내면 진행 과정, Tool 사용과 Artifact가 이곳에 이어집니다.</p><StarterPrompts onSelect={applyStarterPrompt} /></div>
            )}
            {activeRuntime.turnSets.map((turnSet) => (
              <AssistantTurn
                key={turnSet.id}
                turnSet={turnSet}
                snapshot={turnSet.runId ? activeRuntime.snapshots[turnSet.runId] ?? null : null}
                sessionUsage={cumulativeUsageByTurnSetId[turnSet.id]}
                openCalls={openCalls}
                onToggleCall={(id) => toggleSetItem(setOpenCalls, id)}
                onCopyTool={(execution) => void copyTool(execution)}
                onOpenArtifact={(artifact) => void openArtifact(artifact)}
                onBranch={async (anchorMessageId) => {
                  if (!workspace.activeConversationId) return;
                  await workspace.branchConversation(workspace.activeConversationId, anchorMessageId);
                }}
                onShare={(anchorMessageId) => {
                  if (!workspace.activeConversationId) return;
                  void api.sharing.create(workspace.activeConversationId, anchorMessageId)
                    .then(async (share) => {
                      const url = new URL(share.viewerPath, window.location.origin).toString();
                      const themedUrl = new URL(url);
                      themedUrl.searchParams.set("theme", theme);
                      await copyText(themedUrl.toString());
                    })
                    .catch((error) => {
                      showToast(error instanceof ApiError ? error.message : "공유 링크를 만들지 못했습니다.");
                    });
                }}
                onToast={showToast}
                onVisibleGrowth={conversationFollow.notifyGrowth}
                clarificationMode={workspace.settings?.clarificationMode ?? "balanced"}
                inputBusy={workspace.runActionBusy}
                onSubmitUserInput={workspace.submitUserInput}
                onClarificationModeChange={workspace.selectClarificationMode}
              />
            ))}
          </main>
        </div>

        <div className="dock-area" ref={dockAreaRef}>
          {conversationFollow.showJumpToLatest && (
            <button className="jump-to-latest" type="button" aria-label="최신 응답으로 이동" onClick={conversationFollow.jumpToLatest}>
              <ArrowDown size={16} aria-hidden="true" />
            </button>
          )}
          <div className="run-dock">
            {activeRun && (
              <div
                className="progress-panel"
                onClick={(event) => {
                  const clickedButton = (event.target as HTMLElement).closest("button");
                  if (clickedButton && !clickedButton.classList.contains("progress-trigger")) return;
                  setProgressOpen((open) => !open);
                }}
              >
                <div className="progress-header">
                  <button className="progress-trigger" type="button" aria-expanded={progressOpen} aria-controls="active-run-progress-steps" data-tooltip={progressOpen ? undefined : latestProgressSummary?.text ?? runStatusLabel(activeRun.status)}>
                    <div className="progress-title"><Sparkles size={15} /><strong>작업 계획</strong></div>
                    {!progressOpen && (
                      <span className="current-step">
                        {latestProgressSummary?.text ?? runStatusLabel(activeRun.status)}
                      </span>
                    )}
                    <span className="progress-count">{progress.filter((item) => item.status === "complete").length} / {progress.length} · {runStatusLabel(activeRun.status)}</span>
                    {progressOpen ? <ChevronDown className="progress-chevron" size={15} /> : <ChevronUp className="progress-chevron" size={15} />}
                  </button>
                  {runIsPaused && (
                    <div className="run-controls" role="group" aria-label="Run 실행 제어">
                      {runIsPaused && <button type="button" aria-label="Run 재개" data-tooltip="재개" disabled={workspace.runActionBusy} onClick={() => void controlRun("resume")}><Play size={14} /></button>}
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
                  <ol className="progress-steps" id="active-run-progress-steps">
                    {progress.map((step) => {
                      const canRetry = (activeRun.status === "failed" || activeRun.status === "limit_reached") && retryableStepIds.has(step.id);
                      return (
                      <li className={`progress-step step-${step.status} ${canRetry ? "has-action" : ""}`} key={step.id}>
                        <div className="progress-step-label">
                          {step.status === "complete" ? <Check size={15} /> : step.status === "running" ? <LoaderCircle className="is-running" size={15} /> : step.status === "error" ? <AlertCircle size={15} /> : <Circle size={14} />}
                          <span>{step.label}</span><small className={`progress-step-status ${step.status === "complete" ? "status-complete" : ""}`}>{step.status === "complete" ? "완료" : step.status === "running" ? "진행 중" : step.status === "error" ? "확인 필요" : "대기"}</small>
                        </div>
                        {canRetry && <button className="step-retry" type="button" disabled={workspace.runActionBusy} onClick={() => void controlRun("retry_step", step.id)}><RotateCcw size={12} /> 재시도</button>}
                      </li>
                    );})}
                  </ol>
                )}
              </div>
            )}
            <div className="composer">
              {queuedComposerCommands.length > 0 && (
                <div className="composer-pending-commands thin-scrollbar" aria-label={`${queuedComposerCommands.length}개의 Queue 요청`} aria-live="polite">
                  {queuedComposerCommands.map((command, index) => {
                    const busyAction = pendingCommandAction?.id === command.id ? pendingCommandAction.action : null;
                    const position = command.queuePosition ?? index + 1;
                    return (
                      <div className="composer-pending-command" key={command.id}>
                        <span className="composer-command-sequence" aria-label={`Queue ${position}번`}>{position}</span>
                        <span className="composer-command-text">{command.messageText || "대기 중인 요청"}</span>
                        <div className="composer-command-actions">
                          <button
                            className="composer-command-steer"
                            type="button"
                            disabled={workspace.runActionBusy}
                            onClick={() => void controlPendingCommand("steer_queued", command.id)}
                          >
                            {busyAction === "steer_queued" ? <LoaderCircle className="is-running" size={14} /> : <Undo2 size={14} aria-hidden="true" />}
                            <span>현재 작업 조정</span>
                          </button>
                          <button
                            className="composer-command-cancel tooltip-control"
                            type="button"
                            aria-label={`Queue ${position}번 요청 취소`}
                            data-tooltip="Queue 취소"
                            disabled={workspace.runActionBusy}
                            onClick={() => void controlPendingCommand("cancel_command", command.id)}
                          >
                            {busyAction === "cancel_command" ? <LoaderCircle className="is-running" size={14} /> : <Trash2 size={14} />}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {workspace.composerAttachments.length > 0 && (
                <div className="composer-attachments" aria-label="첨부 Context">
                  {workspace.composerAttachments.map((attachment, attachmentIndex) => (
                    <span key={attachment.id}>
                      <FileText size={13} />
                      <span>{attachment.kind === "pasted_text" ? pastedTextAttachmentLabel(attachment, workspace.composerAttachments.slice(0, attachmentIndex).filter((item) => item.kind === "pasted_text").length) : attachment.fileName}</span>
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
                <div className={`composer-suggestions ${composerTrigger.trigger === "$" ? "is-extension-list" : ""}`} id="composer-suggestions" role="listbox" aria-label={composerTrigger.trigger === "@" ? "파일 및 Artifact 후보" : "Skill 및 MCP 후보"}>
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
                        <span className={`composer-suggestion-icon kind-${suggestion.kind}`}>{suggestionIcon(suggestion.kind)}</span>
                        <span className="composer-suggestion-copy">
                          <strong>{suggestion.name}</strong>
                          {composerTrigger.trigger === "$" && suggestion.description && <small className="composer-suggestion-description">· {suggestion.description}</small>}
                          {composerTrigger.trigger === "@" && <small>{suggestion.subtitle}</small>}
                        </span>
                        <span className="composer-suggestion-kind">{unavailable ? "사용 불가" : disabled ? attached ? "첨부됨" : "선택됨" : referenceKindLabel(suggestion.kind)}</span>
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
                rows={1}
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
                  if (composerShowsStop) {
                    void controlRun("cancel");
                    return;
                  }
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
                        ref={value === "file" ? fileModeButtonRef : undefined}
                        className={`${workspace.settings?.outputMode === value ? "is-active" : ""} ${value === "file" && shouldNudgeFileMode ? "is-file-mode-nudged" : ""}`.trim()}
                        aria-pressed={workspace.settings?.outputMode === value}
                        aria-describedby={value === "file" && shouldNudgeFileMode ? "file-mode-nudge" : undefined}
                        onClick={() => {
                          setTargetOutputTokens((current) => value === "chat" ? null : current ?? defaultArtifactOutputTokens);
                          void workspace.selectOutputMode(value);
                        }}
                      >{label}</button>
                    ))}
                  </div>
                  <GlobalTooltipLayer
                    anchor={fileModeButtonRef.current}
                    className="file-mode-nudge-layer"
                    id="file-mode-nudge"
                    open={shouldNudgeFileMode}
                  >
                    <span className="file-mode-nudge-icon" aria-hidden="true"><FileText size={20} /></span>
                    <span className="file-mode-nudge-copy">
                      <strong>파일 생성 요청이 아닌 것 같아요</strong>
                      <small>현재는 파일 모드입니다. 대화만 원하면 ‘채팅’을 선택하세요.</small>
                    </span>
                  </GlobalTooltipLayer>
                  <ArtifactLengthSlider
                    value={targetOutputTokens}
                    onChange={setTargetOutputTokens}
                    disabled={workspace.settings?.outputMode === "chat"}
                  />
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
                  <button
                    className={`send-button tooltip-control ${composerShowsStop ? "is-stop" : ""}`}
                    type="button"
                    disabled={composerShowsStop ? workspace.runActionBusy : workspace.sending || workspace.uploadingAttachments}
                    aria-label={composerShowsStop ? "작업 중단" : runIsActive ? "현재 작업에 반영" : "새 작업 시작"}
                    data-tooltip={composerShowsStop ? "중지" : "Enter 반영 · Ctrl+Enter 대기"}
                    onClick={() => {
                      if (composerShowsStop) void controlRun("cancel");
                      else void sendMessage(false);
                    }}
                  >
                    {composerShowsStop && workspace.runActionBusy
                      ? <LoaderCircle className="is-running" size={17} />
                      : composerShowsStop
                        ? <span className="stop-glyph" aria-hidden="true" />
                        : workspace.sending
                          ? <LoaderCircle className="is-running" size={17} />
                          : <Send size={17} />}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <Suspense fallback={<FeatureViewLoading />}>
          <ViewDataCacheProvider scope={workspace.authSession.user.id}>
          {mainView === "marketplace" && <MarketplaceView key={workspace.activeProjectId ?? "none"} projectId={workspace.activeProjectId} onOpenNavigation={() => setSidebarOpen(true)} />}
          {mainView === "library" && <ArtifactLibraryView key={workspace.activeProjectId ?? "all"} projectId={workspace.activeProjectId} onOpenArtifact={(artifact) => void openArtifact(artifact)} onOpenNavigation={() => setSidebarOpen(true)} />}
          {mainView === "files" && <ProjectFilesView key={workspace.activeProjectId ?? "none"} projectId={workspace.activeProjectId} onOpenNavigation={() => setSidebarOpen(true)} />}
          {mainView === "help" && <HelpCenterView canManage={isAdmin} initialAnnouncementId={helpAnnouncementId} onOpenNavigation={() => setSidebarOpen(true)} />}
          {mainView === "schedules" && <SchedulesView key={workspace.activeProjectId ?? "none"} projectId={workspace.activeProjectId} projects={workspace.projects} execution={workspace.settings?.execution ?? null} executionOptions={candidateModelOptions} onOpenNavigation={() => setSidebarOpen(true)} onProjectChange={workspace.setActiveProjectId} onConversationsChanged={workspace.refreshConversations} />}
          {mainView === "memory" && <MemoryView key={activeProject?.id ?? "none"} project={activeProject} completedRunId={completedProjectLearningRunId} canReviewProjectLearning={canReviewProjectLearning} onOpenNavigation={() => setSidebarOpen(true)} />}
          </ViewDataCacheProvider>
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
                <section className="settings-card" aria-labelledby="clarification-settings-title">
                  <header><h2 id="clarification-settings-title">대화 방식</h2></header>
                  <div className="settings-row"><span><strong>AI 확인 질문</strong><small>모호한 요청에서 AI가 되묻는 정도입니다. 계정 기본값으로 계속 적용됩니다.</small></span><SelectMenu className="settings-select" align="end" value={workspace.settings?.clarificationMode ?? "balanced"} options={[{ value: "autonomous", label: "알아서 진행" }, { value: "balanced", label: "균형 있게" }, { value: "confirming", label: "먼저 확인" }]} ariaLabel="AI 확인 질문 정도" onChange={(value) => void workspace.selectClarificationMode(value as "autonomous" | "balanced" | "confirming")} /></div>
                </section>
                <section className="settings-card" aria-labelledby="execution-settings-title">
                  <header><h2 id="execution-settings-title">기본 실행 옵션</h2></header>
                  <div className="settings-row"><span><strong>Provider</strong><small>새 Run에서 기본으로 사용할 Provider입니다.</small></span><SelectMenu className="settings-select" align="end" value={workspace.settings?.execution.providerId ?? ""} options={accountProviders.map((provider) => ({ value: provider.id, label: provider.displayName }))} ariaLabel="기본 Provider" onChange={(value) => void workspace.selectProvider(value)} /></div>
                  <div className="settings-row"><span><strong>Model</strong><small>선택한 Provider의 기본 Model입니다.</small></span><SelectMenu className="settings-select" align="end" value={workspace.settings?.execution.modelKey ?? ""} options={workspace.models.map((model) => ({ value: model.modelKey, label: model.displayName }))} ariaLabel="기본 Model" onChange={(value) => void workspace.selectModel(value)} /></div>
                  <div className="settings-row"><span><strong>Effort</strong><small>지원되는 경우 기본 추론 강도를 선택합니다.</small></span><SelectMenu className="settings-select" align="end" value={workspace.settings?.execution.effortId ?? ""} options={[{ value: "", label: "기본값" }, ...effortOptions.map((option) => ({ value: option.id, label: option.label }))]} ariaLabel="기본 Effort" onChange={(value) => void workspace.selectEffort(value || null)} /></div>
                </section>
                </>}
                {isAdmin && settingsSection === "admin" && (<>
                  <section className="settings-card settings-admin-card" aria-labelledby="admin-initial-execution-title" aria-busy={adminInitialExecutionBusy}>
                    <header><span><Sparkles size={15} /><h2 id="admin-initial-execution-title">최초 사용자 실행 기본값</h2></span><small>모든 사용자에게 적용</small></header>
                    <div className="settings-row"><span><strong>Provider</strong><small>사용 이력이 없는 사용자가 처음 보게 될 Provider입니다.</small></span><SelectMenu className="settings-select" align="end" value={adminInitialExecution?.providerId ?? ""} options={adminInitialProviders.map((provider) => ({ value: provider.id, label: provider.displayName }))} ariaLabel="최초 사용자 Provider" disabled={adminInitialExecutionBusy} onChange={selectAdminInitialProvider} /></div>
                    <div className="settings-row"><span><strong>Model</strong><small>최초 실행에 선택되어 있을 Model입니다.</small></span><SelectMenu className="settings-select" align="end" value={adminInitialExecution?.modelKey ?? ""} options={adminInitialExecutionModels.map((model) => ({ value: model.modelKey, label: model.displayName }))} ariaLabel="최초 사용자 Model" disabled={adminInitialExecutionBusy || !adminInitialExecution} onChange={selectAdminInitialModel} /></div>
                    <div className="settings-row"><span><strong>Effort</strong><small>최초 실행에 선택되어 있을 추론 강도입니다.</small></span><SelectMenu className="settings-select" align="end" value={adminInitialExecution?.effortId ?? ""} options={[{ value: "", label: "기본값" }, ...adminInitialEffortOptions.map((option) => ({ value: option.id, label: option.label }))]} ariaLabel="최초 사용자 Effort" disabled={adminInitialExecutionBusy || !adminInitialExecution} onChange={(value) => setAdminInitialExecution((current) => current ? { ...current, effortId: value || null } : current)} /></div>
                    <div className="settings-row"><span><strong>적용 범위</strong><small>개인 실행 선택 이력이 없을 때만 사용하며, 이후에는 사용자의 마지막 선택값이 우선합니다.</small></span><div className="settings-inline-control"><button type="button" disabled={adminInitialExecutionBusy || !adminInitialExecution} onClick={() => void saveAdminInitialExecution()}>저장</button></div></div>
                    {adminInitialExecutionError && <p className="settings-inline-error" role="alert">{adminInitialExecutionError}</p>}
                  </section>
                  <section className="settings-card settings-admin-card" aria-labelledby="admin-context-settings-title" aria-busy={adminSettingsBusy}>
                    <header><span><ShieldCheck size={15} /><h2 id="admin-context-settings-title">컨텍스트 관리</h2></span><small>모든 사용자에게 적용</small></header>
                    <div className="settings-row"><span><strong>Provider</strong><small>컨텍스트 실행 정책을 확인할 Provider입니다.</small></span><SelectMenu className="settings-select" align="end" value={adminSettingsProviderId} options={accountProviders.map((provider) => ({ value: provider.id, label: provider.displayName }))} ariaLabel="컨텍스트 관리 Provider" disabled={adminSettingsBusy} onChange={setAdminSettingsProviderId} /></div>
                    <div className="settings-row"><span><strong>Model</strong><small>설정값은 선택한 Model에만 적용됩니다.</small></span><SelectMenu className="settings-select" align="end" value={adminSettingsModelKey} options={adminSettingsModels.map((model) => ({ value: model.modelKey, label: model.displayName }))} ariaLabel="컨텍스트 관리 Model" disabled={adminSettingsBusy} onChange={setAdminSettingsModelKey} /></div>
                    <div className="settings-row">
                      <span>
                        <strong>모델 전체 컨텍스트</strong>
                        <small>
                          Provider가 명시한 입력과 출력의 전체 컨텍스트 윈도우입니다.
                          {selectedAdminSettingsModel?.contextPolicyLocked
                            ? " Codex는 서비스 정책값으로 고정됩니다."
                            : selectedAdminSettingsModel?.defaultContextWindow
                              ? ` 기본값 ${selectedAdminSettingsModel.defaultContextWindow.toLocaleString()} 토큰.`
                              : " 등록된 기본값이 없습니다."}
                        </small>
                      </span>
                      <div className="settings-inline-control">
                        <input aria-label="모델 전체 컨텍스트 토큰" type="text" inputMode="numeric" value={adminMaxTokens} disabled={adminSettingsBusy || !selectedAdminSettingsModel || selectedAdminSettingsModel.contextPolicyLocked} onChange={(event) => setAdminMaxTokens(event.currentTarget.value.replace(/\D/g, "").replace(/\B(?=(\d{3})+(?!\d))/g, ","))} />
                        <button className="is-secondary" type="button" disabled={adminSettingsBusy || !selectedAdminSettingsModel?.defaultContextWindow || selectedAdminSettingsModel.contextPolicyLocked} onClick={() => void resetAdminMaxTokens()}>초기화</button>
                        <button type="button" disabled={adminSettingsBusy || !selectedAdminSettingsModel || selectedAdminSettingsModel.contextPolicyLocked} onClick={() => void saveAdminMaxTokens()}>저장</button>
                      </div>
                    </div>
                    <div className="settings-row settings-output-token-row">
                      <span>
                        <strong>최대 출력 토큰</strong>
                        <small>
                          한 번의 모델 호출에 적용할 운영 상한입니다.
                          {selectedAdminSettingsModel?.maxOutputTokens
                            ? adminOutputTokens > 0
                              ? ` 현재 ${adminOutputTokens.toLocaleString()} · 모델 최대 ${selectedAdminSettingsModel.maxOutputTokens.toLocaleString()} 토큰.`
                              : ` 모델 최대 ${selectedAdminSettingsModel.maxOutputTokens.toLocaleString()} 토큰 · 운영 기본값이 등록되지 않았습니다.`
                            : " 모델 최대 출력 한도가 등록되지 않았습니다."}
                        </small>
                      </span>
                      <div className="settings-inline-control settings-token-slider">
                        <input
                          type="range"
                          min={Math.min(selectedAdminSettingsModel?.outputTokenStep ?? 1_000, selectedAdminSettingsModel?.maxOutputTokens ?? 1_000)}
                          max={selectedAdminSettingsModel?.maxOutputTokens ?? 1_000}
                          step={selectedAdminSettingsModel?.outputTokenStep ?? 1_000}
                          value={adminOutputTokens || selectedAdminSettingsModel?.outputTokenStep || 1_000}
                          disabled={adminSettingsBusy || !selectedAdminSettingsModel?.maxOutputTokens || !adminOutputTokens}
                          aria-label="최대 출력 토큰"
                          aria-valuetext={`${adminOutputTokens.toLocaleString()} 토큰`}
                          onChange={(event) => setAdminOutputTokens(event.currentTarget.valueAsNumber)}
                        />
                        <output>{adminOutputTokens > 0 ? `${adminOutputTokens.toLocaleString()} 토큰` : "미설정"}</output>
                        <button className="is-secondary" type="button" disabled={adminSettingsBusy || !selectedAdminSettingsModel?.defaultMaxOutputTokens} onClick={resetAdminOutputTokens}>초기화</button>
                        <button type="button" disabled={adminSettingsBusy || !selectedAdminSettingsModel?.maxOutputTokens || !adminOutputTokens} onClick={() => void saveAdminOutputTokens()}>저장</button>
                      </div>
                    </div>
                    <div className="settings-row settings-context-budget-row">
                      <span>
                        <strong>기본 최대 입력 컨텍스트</strong>
                        <small>전체 컨텍스트에서 최대 출력 토큰과 안전 여유를 뺀 시스템 입력 상한입니다. Tool 적용 전 기준이며 실제 Run에서는 Tool schema 토큰을 추가 차감합니다.</small>
                      </span>
                      <output aria-live="polite">{adminBaseInputContext === null ? "계산할 수 없음" : `${adminBaseInputContext.toLocaleString()} 토큰`}</output>
                    </div>
                    <div className="settings-row">
                      <span>
                        <strong>자동 압축 시작 비율</strong>
                        <small>
                          위 최대 입력 컨텍스트의 몇 %에서 선제 압축할지 정합니다.
                          {selectedAdminSettingsModel?.contextPolicyLocked
                            ? ` Codex 서비스 정책은 ${Math.round(adminDefaultContextUsageRatio * 100)}%로 고정됩니다.`
                            : null}
                        </small>
                      </span>
                      <div className="settings-inline-control settings-percent-control">
                        <span className="settings-suffixed-input"><input aria-label="자동 압축 시작 비율" type="text" inputMode="numeric" value={adminContextUsagePercent} disabled={adminSettingsBusy || !selectedAdminSettingsModel || selectedAdminSettingsModel.contextPolicyLocked} onChange={(event) => setAdminContextUsagePercent(event.currentTarget.value.replace(/\D/g, "").slice(0, 3))} /><span aria-hidden="true">%</span></span>
                        <button className="is-secondary" type="button" disabled={adminSettingsBusy || !selectedAdminSettingsModel || selectedAdminSettingsModel.contextPolicyLocked} onClick={() => void resetAdminContextUsagePercent()}>초기화</button>
                        <button type="button" disabled={adminSettingsBusy || !selectedAdminSettingsModel || selectedAdminSettingsModel.contextPolicyLocked} onClick={() => void saveAdminContextUsagePercent()}>저장</button>
                      </div>
                    </div>
                    <div className="settings-row settings-context-budget-row">
                      <span>
                        <strong>기본 자동 압축 시작점</strong>
                        <small>Tool 적용 전 최대 입력 컨텍스트에 위 비율을 적용한 소프트 임계값입니다. 실제 Run에서는 Tool schema만큼 더 낮아집니다.</small>
                      </span>
                      <output aria-live="polite">{adminBaseCompactionThreshold === null ? "계산할 수 없음" : `${adminBaseCompactionThreshold.toLocaleString()} 토큰`}</output>
                    </div>
                    {adminSettingsError && <p className="settings-inline-error" role="alert">{adminSettingsError}</p>}
                  </section>
                  <AdminRunSafetySettings onToast={showToast} />
                </>)}
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
            onMembershipsChanged={workspace.refreshProjects}
          />}
        </Suspense>
      </section>

      {artifactPaneVisible && (
        <aside className={`artifact-pane ${artifactFullscreen ? "is-fullscreen" : ""}`} aria-label="Artifact 작업 화면" aria-busy={artifactLoading || artifactSaveBusy !== null}>
          {!artifactFullscreen && <button className="artifact-resize-handle" type="button" role="separator" aria-label="Artifact 패널 너비 조절" aria-orientation="vertical" aria-valuemin={artifactPaneMinWidth} aria-valuenow={artifactPaneWidth} onPointerDown={beginArtifactResize} onKeyDown={resizeArtifactByKeyboard} />}
          <header className="artifact-header">
            <div>
              {artifactSummary && artifactVersionOptions.length > 0 && (
                <SelectMenu className="artifact-version-select" size="small" width="auto" value={String(artifactVersion?.version ?? artifactSummary.currentVersion)} options={artifactVersionOptions.map((version) => ({ value: String(version), label: version === 1 ? "원본" : `v${version}` }))} ariaLabel="Artifact 버전 선택" disabled={artifactLoading || artifactEditing || artifactSaveBusy !== null} onChange={(value) => void selectArtifactVersion(Number(value))} />
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
              <button className="tooltip-control" type="button" aria-label="Artifact 공유 링크 복사" data-tooltip={artifactSummary?.conversationId ? "공유 링크 복사" : "대화에 연결된 Artifact만 공유 가능"} disabled={!artifactSummary?.conversationId} onClick={() => void shareArtifact()}><ShareActionIcon size={17} /></button>
              <button className="artifact-file-control tooltip-control" type="button" aria-label="Artifact 다운로드" data-tooltip="다운로드" disabled={!artifactSummary || artifactDownloadVersion === null} onClick={() => void downloadArtifact()}><Download size={17} /></button>
              <button className="tooltip-control" type="button" aria-label={artifactFullscreen ? "전체화면 종료" : "전체화면"} data-tooltip={artifactFullscreen ? "전체화면 종료" : "전체화면"} onClick={() => setArtifactFullscreen((value) => !value)}>
                {artifactFullscreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
              </button>
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
          <div className={`artifact-body artifact-${artifactTab} ${artifactVersion?.mimeType === "application/pdf" ? "is-pdf" : ""} ${artifactVersion?.mimeType === "text/html" ? "is-html" : ""} ${artifactVersion && artifactHasTextSource && (artifactVersion.mimeType === "text/markdown" || artifactSummary?.kind === "markdown") ? "is-markdown" : ""}`} tabIndex={-1} onPointerDown={focusSelectableRegion} onKeyDown={selectAllInRegion}>
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
                <ArtifactHtmlPreview
                  frameRef={artifactPreviewFrameRef}
                  source={artifactEditing ? artifactEditablePreview : artifactVersion.sourceText ?? ""}
                  title={artifactSummary?.displayName ?? "Artifact 미리보기"}
                  renderMermaid={!artifactEditing}
                />
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
      {modelNameTooltip && createPortal(<div className={`account-model-tooltip${theme === "dark" ? " theme-dark" : ""}`} role="tooltip" style={{ left: modelNameTooltip.left, top: modelNameTooltip.top }}>{modelNameTooltip.name}</div>, document.body)}
    </div>
  );
}

export default App;

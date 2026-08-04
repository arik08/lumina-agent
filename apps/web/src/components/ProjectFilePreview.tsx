import { FileText, LoaderCircle } from "lucide-react";
import { type RefObject, useEffect, useRef, useState } from "react";
import type { ArtifactDownload, ProjectFileDetail } from "../api-types";
import { projectFilesApi } from "../feature-api";
import { ArtifactHtmlPreview } from "./ArtifactHtmlPreview";
import { MarkdownResponse } from "./ConversationTurn";

export type ProjectFilePreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; kind: "text"; text: string; truncated: boolean }
  | { status: "ready"; kind: "html"; source: string }
  | { status: "ready"; kind: "image" | "pdf" | "video" | "audio"; url: string }
  | { status: "unsupported"; mimeType: string }
  | { status: "error"; message: string };

const textExtensions = new Set([
  "css", "csv", "html", "htm", "ini", "js", "json", "jsx", "log", "md", "markdown", "py", "sql", "svg", "toml", "ts", "tsx", "txt", "xml", "yaml", "yml",
]);

function classifyPreview(detail: ProjectFileDetail, blob: Blob) {
  const mimeType = (blob.type || detail.mimeType).toLocaleLowerCase("en-US");
  const extension = detail.displayName.split(".").at(-1)?.toLocaleLowerCase("en-US") ?? "";
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType === "application/pdf") return "pdf";
  if (mimeType === "text/html" || extension === "html" || extension === "htm") return "html";
  if (mimeType.startsWith("video/")) return "video";
  if (mimeType.startsWith("audio/")) return "audio";
  if (mimeType.startsWith("text/") || textExtensions.has(extension) || mimeType.includes("json") || mimeType.includes("xml")) return "text";
  return "unsupported";
}

function looksLikeStandaloneHtml(value: string) {
  const normalized = value.trimStart().toLocaleLowerCase("en-US");
  return ["<!doctype html", "<html", "<head", "<body"].every((marker) => normalized.includes(marker));
}

function injectArtifactPreviewBridge(value: string) {
  const bridgePath = "/artifact-preview-bridge.js";
  if (value.includes(bridgePath)) return value;
  const bridge = `<script src="${new URL(bridgePath, window.location.origin).href}"></script>`;
  return /<\/body\s*>/i.test(value)
    ? value.replace(/<\/body\s*>/i, `${bridge}</body>`)
    : `${value}${bridge}`;
}

export function isMarkdownFile(detail: ProjectFileDetail) {
  const extension = detail.displayName.split(".").at(-1)?.toLocaleLowerCase("en-US");
  return extension === "md" || extension === "markdown" || detail.mimeType.toLocaleLowerCase("en-US") === "text/markdown";
}

export function saveProjectFileDownload(download: ArtifactDownload) {
  const url = URL.createObjectURL(download.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = download.fileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function useProjectFilePreview(projectId: string | null, detail: ProjectFileDetail | null) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [preview, setPreview] = useState<ProjectFilePreviewState>({ status: "idle" });

  useEffect(() => {
    if (!projectId || !detail) {
      setPreview({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setPreview({ status: "loading" });
    projectFilesApi.download(projectId, detail.id, undefined, controller.signal)
      .then(async (download) => {
        const kind = classifyPreview(detail, download.blob);
        if (kind === "html" || kind === "text") {
          const text = await download.blob.text();
          if (looksLikeStandaloneHtml(text)) {
            setPreview({ status: "ready", kind: "html", source: injectArtifactPreviewBridge(text) });
            return;
          }
          const limit = 240_000;
          setPreview({ status: "ready", kind: "text", text: text.slice(0, limit), truncated: text.length > limit });
          return;
        }
        if (kind === "unsupported") {
          setPreview({ status: "unsupported", mimeType: download.blob.type || detail.mimeType });
          return;
        }
        objectUrl = URL.createObjectURL(download.blob);
        setPreview({ status: "ready", kind, url: objectUrl });
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setPreview({ status: "error", message: caught instanceof Error ? caught.message : "파일 요청을 처리하지 못했습니다." });
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [detail, projectId]);

  return { frameRef, preview };
}

interface ProjectFilePreviewContentProps {
  detail: ProjectFileDetail;
  frameRef: RefObject<HTMLIFrameElement | null>;
  markdownSource: boolean;
  preview: ProjectFilePreviewState;
}

export function ProjectFilePreviewContent({ detail, frameRef, markdownSource, preview }: ProjectFilePreviewContentProps) {
  if (preview.status === "loading" || preview.status === "idle") {
    return <div className="feature-state"><LoaderCircle className="is-running" size={15} /> Preview 준비 중</div>;
  }
  if (preview.status === "error") {
    return <div className="file-preview-message"><strong>Preview를 열지 못했습니다.</strong><span>{preview.message}</span></div>;
  }
  if (preview.status === "unsupported") {
    return <div className="file-preview-message"><FileText size={28} /><strong>브라우저 Preview를 지원하지 않는 형식입니다.</strong><span>{preview.mimeType || "알 수 없는 파일 형식"} · 다운로드해서 확인해 주세요.</span></div>;
  }
  if (preview.kind === "text") {
    return <>{isMarkdownFile(detail) && !markdownSource
      ? <div className="file-preview-markdown conversation-response-typography"><MarkdownResponse text={preview.text} /></div>
      : <pre>{preview.text}</pre>}
    {preview.truncated && <div className="file-preview-truncated">Preview는 앞부분만 표시합니다.</div>}</>;
  }
  if (preview.kind === "image") return <img src={preview.url} alt={`${detail.displayName} Preview`} loading="lazy" decoding="async" />;
  if (preview.kind === "pdf") return <iframe src={preview.url} title={`${detail.displayName} PDF Preview`} />;
  if (preview.kind === "html") return <ArtifactHtmlPreview frameRef={frameRef} source={preview.source} previewUrl={null} title={`${detail.displayName} HTML Preview`} />;
  if (preview.kind === "video") return <video src={preview.url} controls />;
  return <audio src={preview.url} controls />;
}

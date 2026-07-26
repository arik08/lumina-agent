import { LoaderCircle } from "lucide-react";
import { useEffect, useState, type RefObject } from "react";
import "./ArtifactHtmlPreview.css";

const artifactPreviewHeightMessage = "lumina:artifact-preview-height";

function withAutoHeightBridge(source: string) {
  const bridge = `<script src="/artifact-preview-bridge.js"></script><script>(()=>{const publish=()=>parent.postMessage({type:"${artifactPreviewHeightMessage}",height:Math.ceil(Math.max(document.documentElement.scrollHeight,document.body?.scrollHeight||0))},"*");addEventListener("load",publish);new ResizeObserver(publish).observe(document.documentElement);setTimeout(publish,0)})()</script>`;
  if (/<\/body\s*>/i.test(source)) return source.replace(/<\/body\s*>/i, `${bridge}</body>`);
  if (/<\/html\s*>/i.test(source)) return source.replace(/<\/html\s*>/i, `${bridge}</html>`);
  return `${source}${bridge}`;
}

export function useArtifactPreviewBridge(frameRef: RefObject<HTMLIFrameElement | null>) {
  useEffect(() => {
    let renderQueue = Promise.resolve();
    const receiveMermaidRequest = (event: MessageEvent) => {
      const target = frameRef.current?.contentWindow;
      if (event.source !== target || event.data?.type !== "lumina:artifact-mermaid-request") return;
      const requestId = typeof event.data.requestId === "string" ? event.data.requestId : "";
      const mermaidSource = typeof event.data.source === "string" ? event.data.source : "";
      if (!requestId || !mermaidSource) return;
      renderQueue = renderQueue.then(async () => {
        try {
          const { renderMermaidSvg } = await import("./InteractiveResponse");
          const { svg } = await renderMermaidSvg(mermaidSource);
          target?.postMessage({ type: "lumina:artifact-mermaid-result", requestId, svg }, "*");
        } catch {
          target?.postMessage({ type: "lumina:artifact-mermaid-result", requestId, svg: null }, "*");
        }
      });
    };
    window.addEventListener("message", receiveMermaidRequest);
    return () => window.removeEventListener("message", receiveMermaidRequest);
  }, [frameRef]);
}

export function ArtifactHtmlPreview({
  frameRef,
  source,
  previewUrl,
  title,
  autoHeight = false,
}: {
  frameRef: RefObject<HTMLIFrameElement | null>;
  source: string | null;
  previewUrl: string | null;
  title: string;
  autoHeight?: boolean;
}) {
  const [frameContent, setFrameContent] = useState<
    { src: string; srcDoc?: never } | { src?: never; srcDoc: string } | null
  >(null);
  const [loaded, setLoaded] = useState(false);
  const [frameHeight, setFrameHeight] = useState<number | null>(null);
  useArtifactPreviewBridge(frameRef);

  useEffect(() => {
    setLoaded(false);
    setFrameHeight(null);
    setFrameContent(null);
    const frame = requestAnimationFrame(() => {
      const previewSource = source ?? "";
      setFrameContent(previewUrl ? { src: previewUrl } : {
        srcDoc: autoHeight ? withAutoHeightBridge(previewSource) : previewSource,
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [autoHeight, previewUrl, source]);

  useEffect(() => {
    if (!autoHeight) return;
    const receiveHeight = (event: MessageEvent) => {
      if (
        event.source !== frameRef.current?.contentWindow
        || event.data?.type !== artifactPreviewHeightMessage
        || typeof event.data.height !== "number"
        || !Number.isFinite(event.data.height)
      ) return;
      setFrameHeight(Math.min(1_000_000, Math.max(1, Math.ceil(event.data.height))));
    };
    window.addEventListener("message", receiveHeight);
    return () => window.removeEventListener("message", receiveHeight);
  }, [autoHeight, frameRef]);

  return <div className={`artifact-preview-shell ${autoHeight ? "is-auto-height" : ""}`} aria-busy={!loaded}>
    {!loaded && <div className="artifact-preview-loading" role="progressbar" aria-label="HTML 미리보기 준비 중">
      <LoaderCircle className="is-running" size={15} />
      <span>HTML 미리보기를 준비하고 있습니다.</span>
      <i aria-hidden="true" />
    </div>}
    {frameContent && <iframe
      ref={frameRef}
      className={`artifact-preview-frame ${autoHeight ? "is-auto-height" : ""}`}
      title={title}
      sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads allow-popups allow-popups-to-escape-sandbox"
      src={frameContent.src}
      srcDoc={frameContent.srcDoc}
      scrolling={autoHeight ? "no" : undefined}
      style={autoHeight ? { height: `${frameHeight ?? 520}px` } : undefined}
      onLoad={() => setLoaded(true)}
    />}
  </div>;
}

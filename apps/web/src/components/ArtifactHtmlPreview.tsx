import { LoaderCircle } from "lucide-react";
import { useEffect, useState, type RefObject } from "react";
import "./ArtifactHtmlPreview.css";

export function ArtifactHtmlPreview({
  frameRef,
  source,
  previewUrl,
  title,
}: {
  frameRef: RefObject<HTMLIFrameElement | null>;
  source: string | null;
  previewUrl: string | null;
  title: string;
}) {
  const [frameContent, setFrameContent] = useState<
    { src: string; srcDoc?: never } | { src?: never; srcDoc: string } | null
  >(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    setFrameContent(null);
    const frame = requestAnimationFrame(() => {
      setFrameContent(previewUrl ? { src: previewUrl } : { srcDoc: source ?? "" });
    });
    return () => cancelAnimationFrame(frame);
  }, [previewUrl, source]);

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

  return <div className="artifact-preview-shell" aria-busy={!loaded}>
    {!loaded && <div className="artifact-preview-loading" role="progressbar" aria-label="HTML 미리보기 준비 중">
      <LoaderCircle className="is-running" size={15} />
      <span>HTML 미리보기를 준비하고 있습니다.</span>
      <i aria-hidden="true" />
    </div>}
    {frameContent && <iframe
      ref={frameRef}
      className="artifact-preview-frame"
      title={title}
      sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads allow-popups allow-popups-to-escape-sandbox"
      src={frameContent.src}
      srcDoc={frameContent.srcDoc}
      onLoad={() => setLoaded(true)}
    />}
  </div>;
}

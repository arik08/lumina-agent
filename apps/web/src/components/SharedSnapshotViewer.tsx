import {
  AlertCircle,
  ArrowLeft,
  Check,
  Copy,
  Download,
  FileCode2,
  FileText,
  LoaderCircle,
  LockKeyhole,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { SharedConversationSnapshot } from "../api-types";
import { copyText } from "../clipboard";
import { sanitizeAssistantResponse } from "../assistant-response";

interface SharedSnapshotViewerProps {
  artifactId?: string | null;
  artifactVersion?: number | null;
  token: string;
  theme: "light" | "dark";
}

type SharedArtifact = SharedConversationSnapshot["artifacts"][number];

function sharedConversationUrl() {
  const url = new URL(window.location.href);
  url.searchParams.delete("artifact");
  url.searchParams.delete("version");
  return url.toString();
}

function hasTextSource(mimeType: string) {
  return mimeType.startsWith("text/")
    || mimeType === "application/json"
    || mimeType === "application/javascript"
    || mimeType === "application/xml";
}

export function SharedSnapshotViewer({
  artifactId = null,
  artifactVersion = null,
  token,
  theme,
}: SharedSnapshotViewerProps) {
  const [snapshot, setSnapshot] = useState<SharedConversationSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [invalid, setInvalid] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadRevision, setLoadRevision] = useState(0);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [sharedArtifactBlob, setSharedArtifactBlob] = useState<Blob | null>(null);
  const [sharedArtifactFileName, setSharedArtifactFileName] = useState("");
  const [sharedArtifactUrl, setSharedArtifactUrl] = useState<string | null>(null);
  const [sharedArtifactSource, setSharedArtifactSource] = useState<string | null>(null);
  const [sharedArtifactLoading, setSharedArtifactLoading] = useState(false);
  const [sharedArtifactError, setSharedArtifactError] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (copyStatus === "idle") return;
    const timer = window.setTimeout(() => setCopyStatus("idle"), 1600);
    return () => window.clearTimeout(timer);
  }, [copyStatus]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setInvalid(false);
    setLoadError(null);
    api.sharing.get(token, controller.signal)
      .then(setSnapshot)
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
          setInvalid(true);
          return;
        }
        setLoadError(error instanceof Error ? error.message : "공유 대화를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [loadRevision, token]);

  const sharedArtifact = artifactId
    ? snapshot?.artifacts.find((artifact) => artifact.id === artifactId) ?? null
    : null;
  const selectedArtifactVersion = sharedArtifact
    ? artifactVersion ?? sharedArtifact.version
    : null;

  useEffect(() => {
    if (!artifactId || !sharedArtifact || selectedArtifactVersion === null) {
      setSharedArtifactBlob(null);
      setSharedArtifactFileName("");
      setSharedArtifactUrl(null);
      setSharedArtifactSource(null);
      setSharedArtifactError(null);
      setSharedArtifactLoading(false);
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setSharedArtifactLoading(true);
    setSharedArtifactError(null);
    setSharedArtifactBlob(null);
    setSharedArtifactUrl(null);
    setSharedArtifactSource(null);
    setCopyStatus("idle");
    api.sharing.downloadArtifact(token, artifactId, selectedArtifactVersion, controller.signal)
      .then(async (download) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(download.blob);
        setSharedArtifactBlob(download.blob);
        setSharedArtifactFileName(download.fileName);
        setSharedArtifactUrl(objectUrl);
        if (hasTextSource(sharedArtifact.mimeType)) {
          setSharedArtifactSource(await download.blob.text());
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setSharedArtifactError(error instanceof Error ? error.message : "Artifact를 열 수 없습니다.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setSharedArtifactLoading(false);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [artifactId, selectedArtifactVersion, sharedArtifact?.mimeType, token]);

  const downloadArtifact = async (artifact: SharedArtifact) => {
    setDownloadingId(artifact.id);
    try {
      const version = artifact.id === artifactId && selectedArtifactVersion !== null
        ? selectedArtifactVersion
        : artifact.version;
      const download = artifact.id === artifactId && sharedArtifactBlob
        ? { blob: sharedArtifactBlob, fileName: sharedArtifactFileName || artifact.displayName }
        : await api.sharing.downloadArtifact(token, artifact.id, version);
      const url = URL.createObjectURL(download.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = download.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloadingId(null);
    }
  };

  const downloadAttachment = async (attachment: SharedConversationSnapshot["attachments"][number]) => {
    setDownloadingId(attachment.id);
    try {
      const download = await api.sharing.downloadAttachment(token, attachment.id);
      const url = URL.createObjectURL(download.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = download.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloadingId(null);
    }
  };

  const copyArtifactContents = async () => {
    if (sharedArtifactSource === null) return;
    try {
      await copyText(sharedArtifactSource);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  };

  if (loading) {
    return <main className={`shared-viewer-state ${theme === "dark" ? "theme-dark" : ""}`}><LoaderCircle className="is-running" size={19} /><span>공유 snapshot을 확인하고 있습니다.</span></main>;
  }
  if (invalid) {
    return (
      <main className={`shared-viewer-state is-error ${theme === "dark" ? "theme-dark" : ""}`}>
        <AlertCircle size={22} />
        <h1>공유된 대화를 열 수 없습니다</h1>
        <p>주소가 잘못되었거나, 공유가 취소 또는 만료되었을 수 있습니다.</p>
        <button type="button" onClick={() => { window.location.href = "/"; }}><ArrowLeft size={15} /> Lumina로 돌아가기</button>
      </main>
    );
  }
  if (loadError || !snapshot) {
    return (
      <main className={`shared-viewer-state is-error ${theme === "dark" ? "theme-dark" : ""}`}>
        <AlertCircle size={22} />
        <h1>공유 대화를 불러오지 못했습니다</h1>
        <p>{loadError ?? "Backend 연결을 확인한 뒤 다시 시도해 주세요."}</p>
        <button type="button" onClick={() => setLoadRevision((revision) => revision + 1)}>다시 시도</button>
      </main>
    );
  }

  if (artifactId) {
    if (!sharedArtifact || selectedArtifactVersion === null) {
      return (
        <main className={`shared-viewer-state is-error ${theme === "dark" ? "theme-dark" : ""}`}>
          <AlertCircle size={22} />
          <h1>공유된 Artifact를 열 수 없습니다</h1>
          <p>이 Artifact가 공유 snapshot에 포함되지 않았거나 링크가 잘못되었습니다.</p>
          <button type="button" onClick={() => { window.location.href = sharedConversationUrl(); }}><ArrowLeft size={15} /> 공유 대화 보기</button>
        </main>
      );
    }
    const canCopyContents = hasTextSource(sharedArtifact.mimeType) && sharedArtifactSource !== null;
    const copyLabel = copyStatus === "copied" ? "내용 복사됨" : copyStatus === "failed" ? "복사 실패" : "내용 복사";
    return (
      <main className={`shared-viewer shared-artifact-viewer ${theme === "dark" ? "theme-dark" : ""}`}>
        <header className="shared-artifact-header">
          <strong>{sharedArtifact.displayName}</strong>
          <nav aria-label="공유 Artifact 작업">
            {canCopyContents && (
              <button className="tooltip-control" type="button" aria-label={copyLabel} data-tooltip={copyLabel} onClick={() => void copyArtifactContents()}>
                {copyStatus === "copied" ? <Check size={16} /> : <Copy size={16} />}
              </button>
            )}
            <button className="tooltip-control" type="button" aria-label="Artifact 다운로드" data-tooltip="다운로드" disabled={!sharedArtifactBlob || downloadingId === sharedArtifact.id} onClick={() => void downloadArtifact(sharedArtifact)}>
              {downloadingId === sharedArtifact.id ? <LoaderCircle className="is-running" size={17} /> : <Download size={17} />}
            </button>
          </nav>
        </header>
        <section className="shared-artifact-body">
          {sharedArtifactLoading && <div className="shared-artifact-status"><LoaderCircle className="is-running" size={18} /> Artifact를 불러오고 있습니다.</div>}
          {sharedArtifactError && <div className="shared-artifact-status is-error"><AlertCircle size={18} /> {sharedArtifactError}</div>}
          {!sharedArtifactLoading && !sharedArtifactError && sharedArtifactUrl && (
            sharedArtifact.mimeType === "text/html" && sharedArtifactSource !== null
              ? <iframe className="shared-artifact-frame" title={sharedArtifact.displayName} sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads" srcDoc={sharedArtifactSource} />
              : sharedArtifact.mimeType === "application/pdf"
                ? <object className="shared-artifact-frame" data={sharedArtifactUrl} type="application/pdf" aria-label={`${sharedArtifact.displayName} PDF 미리보기`} />
                : sharedArtifact.mimeType.startsWith("image/")
                  ? <div className="shared-artifact-image"><img src={sharedArtifactUrl} alt={sharedArtifact.displayName} loading="lazy" decoding="async" /></div>
                  : sharedArtifactSource !== null
                    ? <pre className="shared-artifact-source"><code>{sharedArtifactSource}</code></pre>
                    : <div className="shared-artifact-status"><FileCode2 size={22} /><strong>{sharedArtifact.displayName}</strong><span>이 형식은 브라우저 미리보기를 지원하지 않습니다. 다운로드하여 확인해 주세요.</span></div>
          )}
        </section>
      </main>
    );
  }

  return (
    <main className={`shared-viewer ${theme === "dark" ? "theme-dark" : ""}`}>
      <header className="shared-viewer-header">
        <button type="button" aria-label="Lumina로 돌아가기" onClick={() => { window.location.href = "/"; }}><ArrowLeft size={17} /></button>
        <div><strong>{snapshot.conversation.title}</strong><span>{snapshot.conversation.ownerDisplayName ?? "Lumina 사용자"} 님이 공유</span></div>
        <span className="read-only-mark"><LockKeyhole size={14} /> 읽기 전용</span>
      </header>
      <div className="shared-viewer-scroll">
        <section className="shared-notice"><LockKeyhole size={15} /><span>{new Date(snapshot.share.sharedAt).toLocaleString("ko-KR")} 시점까지 고정된 snapshot입니다.</span></section>
        <section className="shared-messages" aria-label="공유된 대화">
          {snapshot.messages.map((message) => message.role === "user" ? (
            <div className="shared-user-message" key={message.id}>{message.text}</div>
          ) : message.role === "assistant" ? (
            <div className="shared-assistant-message" key={message.id}><Sparkles size={15} /><p>{sanitizeAssistantResponse(message.text, snapshot.artifacts.length > 0)}</p></div>
          ) : null)}
        </section>
        {(snapshot.attachments.length > 0 || snapshot.artifacts.length > 0) && (
          <section className="shared-files">
            <h2>함께 공유된 파일</h2>
            {snapshot.attachments.map((attachment) => (
              <div className="shared-file-row" key={attachment.id}>
                <FileText size={16} />
                <span><strong>{attachment.filename}</strong><small>{attachment.mimeType} · {(attachment.size / 1024).toFixed(1)}KB</small></span>
                <button type="button" aria-label={`${attachment.filename} 다운로드`} disabled={downloadingId === attachment.id} onClick={() => void downloadAttachment(attachment)}>{downloadingId === attachment.id ? <LoaderCircle className="is-running" size={15} /> : <Download size={15} />}</button>
              </div>
            ))}
            {snapshot.artifacts.map((artifact) => (
              <div className="shared-file-row" key={artifact.id}>
                <FileCode2 size={16} />
                <span><strong>{artifact.displayName}</strong><small>{artifact.kind.toUpperCase()} · v{artifact.version}</small></span>
                <button type="button" aria-label={`${artifact.displayName} 다운로드`} disabled={downloadingId === artifact.id} onClick={() => void downloadArtifact(artifact)}>{downloadingId === artifact.id ? <LoaderCircle className="is-running" size={15} /> : <Download size={15} />}</button>
              </div>
            ))}
          </section>
        )}
      </div>
    </main>
  );
}

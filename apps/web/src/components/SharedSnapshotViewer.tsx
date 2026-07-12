import { AlertCircle, ArrowLeft, Download, FileCode2, FileText, LoaderCircle, LockKeyhole, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { SharedConversationSnapshot } from "../api-types";

interface SharedSnapshotViewerProps {
  embedded?: boolean;
  token: string;
  theme: "light" | "dark";
}

export function SharedSnapshotViewer({ embedded = false, token, theme }: SharedSnapshotViewerProps) {
  const [snapshot, setSnapshot] = useState<SharedConversationSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [invalid, setInvalid] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api.sharing.get(token, controller.signal)
      .then(setSnapshot)
      .catch((error) => {
        if (!controller.signal.aborted) setInvalid(error instanceof ApiError && error.status === 404);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [token]);

  const downloadArtifact = async (artifact: SharedConversationSnapshot["artifacts"][number]) => {
    setDownloadingId(artifact.id);
    try {
      const download = await api.sharing.downloadArtifact(token, artifact.id, artifact.version);
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

  if (loading) {
    return <main className={`shared-viewer-state ${embedded ? "is-embedded" : ""} ${theme === "dark" ? "theme-dark" : ""}`}><LoaderCircle className="is-running" size={19} /><span>공유 snapshot을 확인하고 있습니다.</span></main>;
  }
  if (invalid || !snapshot) {
    return (
      <main className={`shared-viewer-state is-error ${embedded ? "is-embedded" : ""} ${theme === "dark" ? "theme-dark" : ""}`}>
        <AlertCircle size={22} />
        <h1>공유된 대화를 열 수 없습니다</h1>
        <p>주소가 잘못되었거나, 공유가 취소 또는 만료되었을 수 있습니다.</p>
        <button type="button" onClick={() => { window.location.href = "/"; }}><ArrowLeft size={15} /> Lumina로 돌아가기</button>
      </main>
    );
  }

  return (
    <main className={`shared-viewer ${embedded ? "is-embedded" : ""} ${theme === "dark" ? "theme-dark" : ""}`}>
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
            <div className="shared-assistant-message" key={message.id}><Sparkles size={15} /><p>{message.text}</p></div>
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

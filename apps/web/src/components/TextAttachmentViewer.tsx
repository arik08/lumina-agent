import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { attachmentContentUrl } from "../api";
import type { AttachmentSummary } from "../api-types";
import { SyntaxCode } from "./SyntaxCode";

export function TextAttachmentViewer({
  attachment,
  onClose,
}: {
  attachment: AttachmentSummary;
  onClose: () => void;
}) {
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setContent("");
    setError(null);
    void fetch(attachmentContentUrl(attachment.id), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then(setContent)
      .catch((fetchError: unknown) => {
        if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
        setError("텍스트 첨부 내용을 불러오지 못했습니다.");
      });
    return () => controller.abort();
  }, [attachment.id]);

  return (
    <>
      <button className="text-attachment-backdrop" type="button" aria-label="텍스트 첨부 닫기" onClick={onClose} />
      <div className="text-attachment-popover" role="dialog" aria-label={`${attachment.fileName} 내용`}>
        <button className="text-attachment-close" type="button" aria-label="텍스트 첨부 닫기" onClick={onClose}><X size={18} /></button>
        {error
          ? <p role="alert">{error}</p>
          : content
            ? <SyntaxCode value={content} fileName={attachment.fileName} mimeType={attachment.mimeType} />
            : <p>내용을 불러오는 중...</p>}
      </div>
    </>
  );
}

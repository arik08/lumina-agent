import { X } from "lucide-react";
import { attachmentContentUrl } from "../api";

export function ImageAttachmentViewer({
  attachment,
  onClose,
}: {
  attachment: { id: string; fileName: string };
  onClose: () => void;
}) {
  return (
    <div className="image-attachment-viewer" role="dialog" aria-modal="true" aria-label={`${attachment.fileName} 이미지 보기`} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <button type="button" aria-label="이미지 닫기" onClick={onClose}><X size={18} /></button>
      <img src={attachmentContentUrl(attachment.id)} alt={attachment.fileName} />
    </div>
  );
}

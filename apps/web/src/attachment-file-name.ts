export function imageAttachmentFileName(originalName: string, attachedAt = new Date()): string {
  const extensionIndex = originalName.lastIndexOf(".");
  const extension = extensionIndex > 0 ? originalName.slice(extensionIndex).toLowerCase() : "";
  const time = [attachedAt.getHours(), attachedAt.getMinutes(), attachedAt.getSeconds()]
    .map((value) => String(value).padStart(2, "0"))
    .join("");
  return `img_${time}${extension}`;
}

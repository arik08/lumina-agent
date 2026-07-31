type ClipboardWriter = {
  writeText: (text: string) => Promise<void>;
};

type ImageClipboardWriter = {
  write: (items: ClipboardItems) => Promise<void>;
};

type CopyTextOptions = {
  clipboard?: ClipboardWriter | null;
  legacyCopy?: (text: string) => boolean;
};

function availableClipboard(): ClipboardWriter | null {
  if (typeof navigator === "undefined" || typeof navigator.clipboard?.writeText !== "function") return null;
  return navigator.clipboard;
}

function legacyCopyText(text: string) {
  if (typeof document === "undefined" || !document.body || typeof document.execCommand !== "function") return false;
  const textarea = document.createElement("textarea");
  const activeElement = typeof HTMLElement !== "undefined" && document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;
  textarea.value = text;
  textarea.readOnly = true;
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "-9999px";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);
  textarea.focus({ preventScroll: true });
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  try {
    return document.execCommand("copy");
  } finally {
    textarea.remove();
    activeElement?.focus({ preventScroll: true });
  }
}

export async function copyText(text: string, options: CopyTextOptions = {}) {
  const clipboard = Object.prototype.hasOwnProperty.call(options, "clipboard")
    ? options.clipboard ?? null
    : availableClipboard();
  let clipboardError: unknown;
  if (clipboard) {
    try {
      await clipboard.writeText(text);
      return;
    } catch (error) {
      clipboardError = error;
    }
  }
  try {
    if ((options.legacyCopy ?? legacyCopyText)(text)) return;
  } catch (error) {
    clipboardError ??= error;
  }
  if (clipboardError instanceof Error) throw clipboardError;
  throw new Error("Clipboard copy failed.");
}

export function canCopyPngToClipboard() {
  const clipboard = typeof navigator !== "undefined"
    ? navigator.clipboard as (Clipboard & ImageClipboardWriter) | undefined
    : undefined;
  return (
    typeof window !== "undefined"
    && window.isSecureContext !== false
    && typeof clipboard?.write === "function"
    && typeof ClipboardItem !== "undefined"
  );
}

export async function deliverPngCapture(
  png: Promise<Blob>,
  downloadFallback: (blob: Blob) => void | Promise<void>,
): Promise<"copied" | "downloaded"> {
  const clipboard = typeof navigator !== "undefined"
    ? navigator.clipboard as (Clipboard & ImageClipboardWriter) | undefined
    : undefined;
  if (canCopyPngToClipboard() && clipboard) {
    await clipboard.write([
      new ClipboardItem({
        "image/png": png,
      }),
    ]);
    return "copied";
  }
  await downloadFallback(await png);
  return "downloaded";
}

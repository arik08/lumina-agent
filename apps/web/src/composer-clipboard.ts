const clipboardBlockSelector = [
  "address",
  "article",
  "blockquote",
  "div",
  "dl",
  "dt",
  "dd",
  "figcaption",
  "figure",
  "footer",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "header",
  "li",
  "main",
  "ol",
  "p",
  "pre",
  "section",
  "tr",
  "ul",
].join(",");

function comparableClipboardText(value: string) {
  return value.replace(/\s+/g, "");
}

export function clipboardTextWithLineBreaks(plainText: string, htmlText: string) {
  if (/[\r\n]/.test(plainText) || !htmlText || typeof DOMParser === "undefined") return plainText;

  const parsed = new DOMParser().parseFromString(htmlText, "text/html");
  parsed.body.querySelectorAll("br").forEach((element) => element.replaceWith(parsed.createTextNode("\n")));
  parsed.body.querySelectorAll(clipboardBlockSelector).forEach((element) => {
    element.after(parsed.createTextNode("\n"));
  });
  const recovered = (parsed.body.textContent ?? "")
    .replace(/\u00a0/g, " ")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  if (!recovered.includes("\n")) return plainText;
  if (plainText && comparableClipboardText(recovered) !== comparableClipboardText(plainText)) return plainText;
  return recovered;
}

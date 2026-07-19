type RgbColor = { red: number; green: number; blue: number; alpha: number };

const minimumTextContrast = 4.5;
const lightText = "#ffffff";
const darkText = "#20242c";
const maximumContrastDarkText = "#000000";

function parseCssColor(value: string): RgbColor | null {
  const hex = value.trim().match(/^#([\da-f]{3}|[\da-f]{6})$/i)?.[1];
  if (hex) {
    const normalized = hex.length === 3 ? [...hex].map((digit) => `${digit}${digit}`).join("") : hex;
    return {
      red: Number.parseInt(normalized.slice(0, 2), 16),
      green: Number.parseInt(normalized.slice(2, 4), 16),
      blue: Number.parseInt(normalized.slice(4, 6), 16),
      alpha: 1,
    };
  }

  const rgb = value.trim().match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/i);
  if (!rgb) return null;
  const alpha = rgb[4]?.endsWith("%") ? Number.parseFloat(rgb[4]) / 100 : Number.parseFloat(rgb[4] ?? "1");
  return {
    red: Number.parseFloat(rgb[1]),
    green: Number.parseFloat(rgb[2]),
    blue: Number.parseFloat(rgb[3]),
    alpha,
  };
}

function relativeLuminance(color: RgbColor) {
  const channel = (value: number) => {
    const normalized = value / 255;
    return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(color.red) + 0.7152 * channel(color.green) + 0.0722 * channel(color.blue);
}

export function mermaidTextContrastRatio(foreground: string, background: string) {
  const foregroundColor = parseCssColor(foreground);
  const backgroundColor = parseCssColor(background);
  if (!foregroundColor || !backgroundColor || foregroundColor.alpha < 1 || backgroundColor.alpha < 1) return null;
  const brighter = Math.max(relativeLuminance(foregroundColor), relativeLuminance(backgroundColor));
  const darker = Math.min(relativeLuminance(foregroundColor), relativeLuminance(backgroundColor));
  return (brighter + 0.05) / (darker + 0.05);
}

export function readableMermaidTextColor(foreground: string, background: string) {
  const currentContrast = mermaidTextContrastRatio(foreground, background);
  if (currentContrast === null || currentContrast >= minimumTextContrast) return null;

  const lightContrast = mermaidTextContrastRatio(lightText, background) ?? 0;
  const darkContrast = mermaidTextContrastRatio(darkText, background) ?? 0;
  if (lightContrast >= minimumTextContrast || darkContrast >= minimumTextContrast) {
    return lightContrast > darkContrast ? lightText : darkText;
  }
  return maximumContrastDarkText;
}

export function ensureMermaidNodeTextContrast(svg: SVGSVGElement) {
  for (const node of svg.querySelectorAll<SVGGElement>("g.node")) {
    const shape = node.querySelector<SVGGraphicsElement>(":scope > rect, :scope > polygon, :scope > circle, :scope > ellipse, :scope > path");
    const label = node.querySelector<SVGElement | HTMLElement>(".label text, .label tspan, .label span, .label div, .label");
    if (!shape || !label) continue;

    const shapeStyle = getComputedStyle(shape);
    if (Number.parseFloat(shapeStyle.fillOpacity || "1") < 1) continue;
    const labelStyle = getComputedStyle(label);
    const foreground = label instanceof SVGElement ? labelStyle.fill : labelStyle.color;
    const replacement = readableMermaidTextColor(foreground, shapeStyle.fill);
    if (!replacement) continue;

    node.dataset.luminaContrastAdjusted = "true";
    const labelRoot = node.querySelector<SVGElement>(".label");
    labelRoot?.style.setProperty("color", replacement, "important");
    for (const element of node.querySelectorAll<SVGElement>(".label text, .label tspan")) {
      element.style.setProperty("fill", replacement, "important");
      element.style.setProperty("color", replacement, "important");
    }
    for (const element of node.querySelectorAll<HTMLElement>(".label span, .label div")) {
      element.style.setProperty("color", replacement, "important");
    }
  }
}

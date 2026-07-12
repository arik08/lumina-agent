#!/usr/bin/env node
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(new URL("../node-runtime/package.json", import.meta.url));
const pptxgenModule = require("pptxgenjs");
const pptxgen = pptxgenModule.default || pptxgenModule;

const output = process.argv[2] || path.join("outputs", "pptx_writer_smoke.pptx");

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "MyHarness";
pptx.subject = "pptx-writer smoke deck";
pptx.title = "PPTX Writer Smoke Deck";
pptx.company = "MyHarness";
pptx.lang = "ko-KR";
pptx.theme = {
  headFontFace: "Aptos Display",
  bodyFontFace: "Aptos",
  lang: "ko-KR",
};

let slide = pptx.addSlide();
slide.background = { color: "FFFFFF" };
slide.addText("PPTX Writer Smoke Deck", {
  x: 0.75,
  y: 0.8,
  w: 11.8,
  h: 0.6,
  fontFace: "Aptos Display",
  fontSize: 34,
  bold: true,
  color: "1F2937",
  margin: 0,
});
slide.addText("Editable title, body text, and native table check", {
  x: 0.78,
  y: 1.55,
  w: 11.5,
  h: 0.35,
  fontSize: 16,
  color: "4B5563",
  margin: 0,
});
slide.addShape(pptx.ShapeType.rect, {
  x: 0.75,
  y: 2.35,
  w: 11.8,
  h: 0.05,
  fill: { color: "2563EB" },
  line: { color: "2563EB" },
});

slide = pptx.addSlide();
slide.background = { color: "FFFFFF" };
slide.addText("QA Targets", {
  x: 0.75,
  y: 0.55,
  w: 11.8,
  h: 0.5,
  fontSize: 28,
  bold: true,
  color: "111827",
  margin: 0,
});
slide.addTable(
  [
    [
      { text: "Gate", options: { bold: true } },
      { text: "Expected", options: { bold: true } },
    ],
    ["Text", "Extractable and editable"],
    ["Layout", "No template prompts"],
    ["Review", "QA script returns OK"],
  ],
  {
    x: 0.8,
    y: 1.45,
    w: 11.1,
    h: 2.1,
    border: { type: "solid", color: "CBD5E1", pt: 1 },
    fill: { color: "F8FAFC" },
    fontFace: "Aptos",
    fontSize: 14,
    color: "1F2937",
    margin: 0.08,
  },
);

await mkdir(path.dirname(output), { recursive: true });
await pptx.writeFile({ fileName: output });
console.log(output);

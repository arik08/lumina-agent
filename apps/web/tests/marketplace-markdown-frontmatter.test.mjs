import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { markdownBodyAfterFrontmatter, splitMarkdownFrontmatter } from "../src/components/markdownFrontmatter.ts";

const marketplacePath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);
const syntaxCodePath = new URL("../src/components/SyntaxCode.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("Skill Markdown preview preserves YAML trigger metadata separately from the body", () => {
  const frontmatter = splitMarkdownFrontmatter("---\nname: visual-artifact\ndescription: Preview metadata\n---\n\n# Instructions\n\nBody");

  assert.ok(frontmatter);
  assert.equal(frontmatter.opening, "---");
  assert.equal(frontmatter.yaml, "name: visual-artifact\ndescription: Preview metadata");
  assert.equal(frontmatter.closing, "---");
  assert.equal(markdownBodyAfterFrontmatter(frontmatter.body), "# Instructions\n\nBody");
});

test("ordinary or incomplete Markdown separators remain visible", () => {
  const thematicBreak = "Introduction\n\n---\n\nNext section";
  const incompleteFrontmatter = "---\nname: visual-artifact\n# Instructions";

  assert.equal(splitMarkdownFrontmatter(thematicBreak), null);
  assert.equal(splitMarkdownFrontmatter(incompleteFrontmatter), null);
});

test("Marketplace preview and source highlighting share the frontmatter boundary", async () => {
  const [marketplace, syntaxCode, styles] = await Promise.all([
    readFile(marketplacePath, "utf8"),
    readFile(syntaxCodePath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(marketplace, /aria-label="Skill 트리거 메타데이터"/);
  assert.match(marketplace, /<SyntaxCode value=\{frontmatter\.yaml\} language="yaml"/);
  assert.match(marketplace, /<hr \/>[\s\S]*?<SyntaxCode[\s\S]*?<hr \/>/);
  assert.match(marketplace, /<ReactMarkdown skipHtml remarkPlugins=\{\[remarkGfm\]\}>\{markdown\}<\/ReactMarkdown>/);
  assert.match(syntaxCode, /splitMarkdownFrontmatter\(value\)/);
  assert.match(styles, /\.skill-markdown-preview \.skill-frontmatter-preview pre code \{ white-space: pre-wrap; word-break: break-word; \}/);
});

test("Skill source and rendered views share a resizable inline expanded-view control", async () => {
  const [marketplace, styles] = await Promise.all([
    readFile(marketplacePath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(marketplace, /className="skill-content-view-actions"/);
  assert.match(marketplace, /current === "source" \? "rendered" : "source"/);
  assert.match(marketplace, /skillContentView === "source" \? <Eye size=\{14\} \/> : <Code2 size=\{14\} \/>/);
  assert.match(marketplace, /useState<"source" \| "rendered">\("rendered"\)/);
  assert.match(marketplace, /skillContentExpanded \? "원래 크기로 보기" : "확대해서 보기"/);
  assert.match(marketplace, /skillContentExpanded \? <Minimize2 size=\{14\} \/> : <Maximize2 size=\{14\} \/>/);
  assert.match(marketplace, /storageKey="lumina:marketplace-file-explorer-width"/);
  assert.match(marketplace, /ariaLabel="패키지 파일 탐색기 너비 조절"/);
  assert.match(marketplace, /skillContentExpanded \? renderPackageBrowser\(\) : <>/);
  assert.doesNotMatch(marketplace, /setEditMode\(false\);\s*setSkillContentExpanded\(false\);/);
  assert.doesNotMatch(marketplace, /className="skill-content-view-toggle"/);
  assert.doesNotMatch(styles, /\.marketplace-file-browser\.is-expanded \{[^}]*position: fixed;/);
  assert.match(styles, /\.feature-detail\.is-skill-content-expanded \{ overflow: hidden; padding: 0; \}/);
  assert.match(styles, /\.marketplace-file-browser\.is-expanded \{[^}]*height: 100%;/);
  assert.match(styles, /\.marketplace-file-browser\.is-expanded \.skill-file-content \{ height: auto; max-height: none; \}/);
});

test("Marketplace package browser uses viewport space and keeps scrolling inside the file panes", async () => {
  const [marketplace, styles] = await Promise.all([
    readFile(marketplacePath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(marketplace, /selected \? "has-skill-package" : ""/);
  assert.match(styles, /\.feature-detail\.has-skill-package \{[^}]*grid-template-rows: auto minmax\(0, 1fr\);[^}]*overflow: hidden;/);
  assert.match(styles, /\.marketplace-package-detail \{[^}]*min-height: 0;[^}]*grid-template-rows: auto minmax\(0, 1fr\);/);
  assert.match(styles, /\.marketplace-file-browser > aside \{[^}]*min-height: 0;[^}]*overflow: auto;/);
  assert.match(styles, /\.marketplace-file-browser > section \{[^}]*grid-template-rows: 34px minmax\(0, 1fr\);[^}]*overflow: hidden;/);
  assert.match(styles, /\.skill-file-content \{ min-height: 0; max-height: none; overflow: auto;/);
  assert.doesNotMatch(styles, /\.marketplace-file-browser \{[^}]*min-height: \d+px;/);
});

test("Marketplace type tabs live inside the top header", async () => {
  const [marketplace, styles] = await Promise.all([
    readFile(marketplacePath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(marketplace, /<header className="feature-header">[\s\S]*?<div className="feature-kind-tabs" role="tablist" aria-label="Marketplace 유형">[\s\S]*?<\/header>/);
  assert.doesNotMatch(marketplace, /<\/header>\s*<div className="feature-kind-tabs"/);
  assert.match(styles, /\.feature-header \.feature-kind-tabs \{ align-self: stretch;/);
  assert.match(styles, /\.feature-kind-tabs button \{[^}]*height: 45px;/);
  assert.doesNotMatch(styles, /\.feature-kind-tabs button(?:\[aria-selected="true"\])? \{[^}]*border-bottom/);
  assert.doesNotMatch(marketplace, /승인 MCP · 설치 · Secret binding/);
});

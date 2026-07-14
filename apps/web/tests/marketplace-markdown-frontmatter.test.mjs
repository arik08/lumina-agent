import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { stripMarkdownFrontmatter } from "../src/components/markdownFrontmatter.ts";

const marketplacePath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);
const syntaxCodePath = new URL("../src/components/SyntaxCode.tsx", import.meta.url);

test("Skill Markdown preview removes a leading YAML frontmatter block", () => {
  assert.equal(
    stripMarkdownFrontmatter("---\nname: visual-artifact\ndescription: Preview metadata\n---\n\n# Instructions\n\nBody"),
    "# Instructions\n\nBody",
  );
  assert.equal(
    stripMarkdownFrontmatter("\uFEFF---\r\nname: visual-artifact\r\n---\r\nBody"),
    "Body",
  );
});

test("ordinary or incomplete Markdown separators remain visible", () => {
  const thematicBreak = "Introduction\n\n---\n\nNext section";
  const incompleteFrontmatter = "---\nname: visual-artifact\n# Instructions";

  assert.equal(stripMarkdownFrontmatter(thematicBreak), thematicBreak);
  assert.equal(stripMarkdownFrontmatter(incompleteFrontmatter), incompleteFrontmatter);
});

test("Marketplace preview and source highlighting share the frontmatter boundary", async () => {
  const [marketplace, syntaxCode] = await Promise.all([
    readFile(marketplacePath, "utf8"),
    readFile(syntaxCodePath, "utf8"),
  ]);

  assert.match(marketplace, /stripMarkdownFrontmatter\(detailFiles\[activeFile\]/);
  assert.match(syntaxCode, /splitMarkdownFrontmatter\(value\)/);
});

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/ArtifactLibraryView.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("artifact library filters by available file extensions and sorts the visible rows", async () => {
  const [view, styles] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(view, /import \{ SelectMenu, type SelectMenuOption \} from "\.\/SelectMenu";/);
  assert.match(view, /\{ value: ALL_EXTENSIONS, label: "전체" \}/);
  assert.match(view, /ariaLabel="파일 확장자 필터"/);
  assert.match(view, /\{ value: "latest", label: "최신순" \}/);
  assert.match(view, /\{ value: "alphabetical", label: "알파벳순" \}/);
  assert.match(view, /getArtifactExtension\(item\.displayName\) === extension/);
  assert.match(view, /artifactNameCollator\.compare\(left\.displayName, right\.displayName\)/);
  assert.match(view, /Date\.parse\(right\.updatedAt\) - Date\.parse\(left\.updatedAt\)/);
  assert.match(styles, /\.artifact-library-toolbar \.feature-search \{[^}]*flex: 1 1 360px;/);
  assert.match(styles, /\.artifact-library-controls \{[^}]*margin-left: auto;/);
  assert.match(styles, /\.lumina-select\.artifact-extension-select \{[^}]*min-width: 88px;/);
  assert.match(styles, /\.lumina-select\.artifact-sort-select \{[^}]*min-width: 104px;/);
});

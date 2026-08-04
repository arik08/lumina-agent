import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const marketplacePath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);

test("editable Skill packages expose file-repository context actions", async () => {
  const marketplace = await readFile(marketplacePath, "utf8");

  assert.match(marketplace, /if \(!selected\?\.canEdit\)/);
  assert.match(marketplace, /onContextMenu=\{\(event\) => openSkillTreeContextMenu\(event, node\)\}/);
  assert.match(marketplace, /aria-label="패키지 파일 탐색기 메뉴"/);
  assert.match(marketplace, /<FolderPlus size=\{14\} \/> 새 폴더/);
  assert.match(marketplace, /<Pencil size=\{14\} \/> 이름 변경/);
  assert.match(marketplace, /contextDeletePath === skillTreeContextMenu\.node\.path \? "한 번 더 눌러 삭제" : "삭제"/);
  assert.match(marketplace, /\[`\$\{folderPath\}\/\.gitkeep`\]: ""/);
  assert.match(marketplace, /node\.kind !== "file" \|\| node\.name !== "\.gitkeep"/);
  assert.match(marketplace, /skillTreeContextMenu\.node\.path !== "SKILL\.md"/);
  assert.match(marketplace, /if \(!editMode\) void beginPackageEdit\(\)/);
});

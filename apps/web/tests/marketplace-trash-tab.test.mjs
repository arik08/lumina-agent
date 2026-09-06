import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);

test("trash tab keeps its retention tooltip without a separate info icon", async () => {
  const view = await readFile(viewPath, "utf8");
  const trashTab = view.match(/<button className="tooltip-control"[^>]*data-tooltip="삭제한 Skill은 30일 동안 보관되며 그 전에 복원할 수 있습니다\."[^>]*>[\s\S]*?<\/button>/)?.[0] ?? "";

  assert.match(trashTab, /<Trash2 size=\{14\} \/> 삭제됨 <span>\{counts\.trashed\}<\/span>/);
  assert.doesNotMatch(trashTab, /<Info\b/);
});

test("permanent deletion is admin-only and requires an inline password confirmation", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /skillView === "trash"[\s\S]*?canManage && <form className="marketplace-permanent-delete"/);
  assert.match(view, /type="password" aria-label="관리자 비밀번호"/);
  assert.match(view, /permanentDeleteConfirmId === selected\.id \? "영구 삭제" : "바로 삭제"/);
  assert.match(view, /api\.extensions\.permanentlyDelete\(selected\.id, adminPassword\)/);
  assert.doesNotMatch(view, /window\.confirm/);
});

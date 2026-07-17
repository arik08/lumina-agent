import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("login screen exposes registration request fields without the session note", async () => {
  const [screen, api] = await Promise.all([
    read("../src/components/LoginScreen.tsx"),
    read("../src/api.ts"),
  ]);
  assert.doesNotMatch(screen, /인증된 세션은 오늘 자정까지 유지됩니다/);
  assert.match(screen, /placeholder="POSCO_ID"/);
  assert.match(screen, /placeholder="\*{8}"/);
  assert.match(screen, />\s*회원가입\s*</);
  for (const label of ["가입 이메일", "이름", "소속", "신청 역할", "가입 비밀번호", "비밀번호 확인"]) {
    assert.match(screen, new RegExp(`aria(?:-label|Label)="${label}"`));
  }
  assert.match(api, /"\/auth\/register"/);
});

test("admin user list offers direct approval for invited accounts", async () => {
  const adminView = await read("../src/components/AdminView.tsx");
  assert.match(adminView, /user\.status === "invited"/);
  assert.match(adminView, />승인<\/button>/);
  assert.match(adminView, /status: "active"/);
});

test("admin user save closes the inline editor before the request", async () => {
  const adminView = await read("../src/components/AdminView.tsx");
  assert.match(
    adminView,
    /const saveUser[\s\S]*?if \(destructive && !userChangeArmed\)[\s\S]*?setSelectedUser\(null\);\s*setSaving\(true\);/,
  );
  assert.match(
    adminView,
    /className="admin-user-inline-edit"[\s\S]*?onKeyDown=\{\(event\) => \{ if \(event\.key !== "Enter"\) return; event\.preventDefault\(\); void saveUser\(\); \}\}/,
  );
  assert.doesNotMatch(adminView, /document\.activeElement/);
});

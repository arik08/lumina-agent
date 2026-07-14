import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const componentPaths = {
  marketplace: new URL("../src/components/MarketplaceView.tsx", import.meta.url),
  library: new URL("../src/components/ArtifactLibraryView.tsx", import.meta.url),
  schedules: new URL("../src/components/SchedulesView.tsx", import.meta.url),
  memory: new URL("../src/components/MemoryView.tsx", import.meta.url),
};

test("primary feature headers explain what each menu is for", async () => {
  const sources = Object.fromEntries(await Promise.all(
    Object.entries(componentPaths).map(async ([name, path]) => [name, await readFile(path, "utf8")]),
  ));

  assert.match(sources.marketplace, /<h1>마켓스토어<\/h1><div className="feature-kind-tabs"[\s\S]*?<\/div><span>탐색·설치·관리<\/span>/);
  assert.match(sources.library, /<h1>Artifact Library<\/h1><span>\{items\.length\}개 · 생성된 결과물 검색·미리보기<\/span>/);
  assert.match(sources.schedules, /<h1>예약 작업<\/h1><span>\{tasks\.length\}개 · 반복·지정 시각 작업 관리<\/span>/);
  assert.match(sources.memory, /<h1>Memory<\/h1><span>개인·Project 학습 내용 검토/);
});

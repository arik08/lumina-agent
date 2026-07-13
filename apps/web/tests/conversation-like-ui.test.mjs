import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const stylesSource = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const workspaceSource = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");

test("conversation like is available below favorite and drives the sidebar heart and filter", () => {
  const favoritePosition = appSource.indexOf('conversation.isFavorite ? "즐겨찾기 해제"');
  const likePosition = appSource.indexOf('conversation.isLiked ? "좋아요 취소"', favoritePosition);

  assert.ok(favoritePosition >= 0 && likePosition > favoritePosition);
  assert.match(appSource, /conversation\.isLiked \? <Heart className="session-like"/);
  assert.match(appSource, /className="session-like-button"[\s\S]*toggleLikedConversation\(conversation\.id\)/);
  assert.match(appSource, /className="session-row session-title-button"[\s\S]*selectConversation\(conversation\.id\)/);
  assert.match(appSource, /!likedSessionsOnly \|\| conversation\.isLiked/);
  assert.match(appSource, /session-heading-actions[\s\S]*liked-sessions-filter[\s\S]*bulk-session-open/);
  assert.match(appSource, /liked-sessions-filter[\s\S]*setLikedSessionsOnly\(\(active\) => !active\)/);
  assert.match(appSource, /aria-label=\{likedSessionsOnly \? "전체 보기" : "좋아요만 보기"\}/);
  assert.match(appSource, /likedSessionsOnly \? "좋아요" : "최근 항목"/);
  assert.doesNotMatch(appSource, /세션 관리 닫기[\s\S]{0,300}setLikedSessionsOnly/);
  assert.match(workspaceSource, /isLiked: !conversation\.isLiked/);
  assert.doesNotMatch(workspaceSource, /좋아요로 표시했습니다|좋아요 표시를 해제했습니다/);
});

test("session titles keep the same horizontal position in management mode", () => {
  assert.match(stylesSource, /\.session-item\.is-bulk \.session-row \{ padding-left: 7px; \}/);
});

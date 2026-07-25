import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const recentItemsSource = await readFile(new URL("../src/components/SidebarRecentItems.tsx", import.meta.url), "utf8");
const stylesSource = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const workspaceSource = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");

test("conversation like is available below favorite and drives the sidebar heart and filter", () => {
  const favoritePosition = recentItemsSource.indexOf('openMenuItem.isFavorite ? "즐겨찾기 해제"');
  const likePosition = recentItemsSource.indexOf('openMenuItem.isLiked ? "좋아요 취소"', favoritePosition);

  assert.ok(favoritePosition >= 0 && likePosition > favoritePosition);
  assert.match(recentItemsSource, /item\.isLiked \? <Heart className="session-like"/);
  assert.match(recentItemsSource, /className="session-like-button"[\s\S]*onToggleLiked\(item\.id\)/);
  assert.match(recentItemsSource, /className="session-row session-title-button"[\s\S]*onSelect\(item\.id\)/);
  assert.match(recentItemsSource, /!likedOnly \|\| item\.isLiked/);
  assert.match(recentItemsSource, /session-heading-actions[\s\S]*session-title-filter-toggle[\s\S]*liked-sessions-filter[\s\S]*bulk-session-open/);
  assert.match(recentItemsSource, /liked-sessions-filter[\s\S]*setLikedOnly\(\(active\) => !active\)/);
  assert.match(appSource, /const conversationSidebarItems = useMemo\([\s\S]*normalizedConversationTitleFilter \? conversationTitleResults : workspace\.conversations/);
  assert.match(appSource, /const deepAnalysisSidebarItems = useMemo\([\s\S]*deepAnalysisTitleFilter[\s\S]*deepAnalysisMissions[\s\S]*includes\(normalizedQuery\)/);
  assert.match(appSource, /items=\{deepAnalysisSidebarItems\}[\s\S]*<SidebarRecentItems[\s\S]*items=\{conversationSidebarItems\}/);
  assert.match(workspaceSource, /isLiked: !conversation\.isLiked/);
  assert.doesNotMatch(workspaceSource, /좋아요로 표시했습니다|좋아요 표시를 해제했습니다/);
});

test("session titles keep the same horizontal position in management mode", () => {
  assert.match(stylesSource, /\.session-item\.is-bulk \.session-row \{ padding-left: 7px; \}/);
});

test("title filtering is shared by chat and deep analysis with always-visible heading actions", () => {
  assert.match(recentItemsSource, /aria-label="세션 제목 검색"/);
  assert.match(recentItemsSource, /aria-label="세션 제목 필터 해제"/);
  assert.match(recentItemsSource, /aria-label=\{titleFilterAriaLabel\}/);
  assert.match(appSource, /titleQuery: normalizedConversationTitleFilter/);
  assert.match(appSource, /items=\{deepAnalysisSidebarItems\}[\s\S]*titleFilterQuery=\{deepAnalysisTitleFilter\}/);
  assert.match(appSource, /titleFilterAriaLabel="심층분석 제목으로 필터링"/);
  assert.match(appSource, /items=\{conversationSidebarItems\}[\s\S]*titleFilterQuery=\{conversationTitleFilter\}/);
  assert.match(appSource, /titleFilterAriaLabel="채팅 세션 제목으로 필터링"/);
  assert.doesNotMatch(appSource, /ConversationSearchDialog|conversationSearchOpen|aria-label="대화 검색"/);
  assert.match(workspaceSource, /setConversations\(\(items\) => \[\.\.\.items\.filter[\s\S]*conversation\]\.sort/);
  assert.doesNotMatch(workspaceSource, /setConversations\(\(items\) => \[conversation, \.\.\.items\.filter/);
  assert.match(stylesSource, /\.session-heading-action,\s*\.bulk-session-open \{ opacity: 1; pointer-events: auto; transform: translateX\(0\); \}/);
  assert.doesNotMatch(stylesSource, /\.session-heading:hover \.(?:session-heading-action|bulk-session-open)/);
});

test("always-visible recent-item actions keep breathing room in the heading", () => {
  assert.match(stylesSource, /\.session-heading \{ height: 32px; padding-right: 2px; \}/);
  assert.match(stylesSource, /\.session-heading > div \{ display: flex; align-items: center; gap: 4px; \}/);
});

test("shared recent-item submenus close when another area is pressed", () => {
  assert.match(recentItemsSource, /document\.addEventListener\("pointerdown", closeOutsideSubmenu\)/);
  assert.match(recentItemsSource, /menuRef\.current\?\.contains\(target\) \|\| menuTriggerRef\.current\?\.contains\(target\)/);
  assert.match(recentItemsSource, /setMenuId\(null\);[\s\S]*setMoveMenuId\(null\);[\s\S]*setDeleteArmedId\(null\);/);
});

test("recent-item menu uses a viewport-aware global layer above the account footer", () => {
  assert.match(recentItemsSource, /createPortal\([\s\S]*className=\{`session-options-menu session-options-menu-global/);
  assert.match(recentItemsSource, /querySelector<HTMLElement>\("\.sidebar-footer"\)/);
  assert.match(recentItemsSource, /menuRect\.height > availableBelow && availableAbove > availableBelow/);
  assert.match(recentItemsSource, /document\.body/);
  assert.match(stylesSource, /\.session-options-menu-global \{ position: fixed; z-index: 500; \}/);
});

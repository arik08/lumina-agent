import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnSource = await readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8");
const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const workspaceSource = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");
const styles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

test("answer ratings use accessible selected states and semantic colors", () => {
  assert.match(turnSource, /aria-label="좋아요" aria-pressed=\{answerRating === "like"\}/);
  assert.match(turnSource, /aria-label="싫어요" aria-pressed=\{answerRating === "dislike"\}/);
  assert.match(turnSource, /answerRating === "like" \? "is-like"/);
  assert.match(turnSource, /answerRating === "dislike" \? "is-dislike"/);
  assert.match(styles, /answer-rating-control\.is-like[\s\S]*?color: var\(--cobalt\)/);
  assert.match(styles, /answer-rating-control\.is-dislike[\s\S]*?color: var\(--danger\)/);
});

test("answer ratings toggle off on a second click and failures restore the previous state", () => {
  assert.match(turnSource, /const nextRating = answerRating === value \? null : value/);
  assert.match(turnSource, /setAnswerRating\(nextRating\)/);
  assert.match(turnSource, /if \(nextRating === null\) \{[\s\S]*?await api\.messages\.deleteRating\(finalMessage\.id\)/);
  assert.match(turnSource, /await api\.messages\.putRating\(finalMessage\.id, nextRating\)/);
  assert.match(turnSource, /setAnswerRating\(previousRating\)[\s\S]*?onToast\("평가를 기록하지 못했습니다\."\)/);
  assert.doesNotMatch(turnSource, /좋아요를 기록했습니다|싫어요를 기록했습니다/);
});

test("answer interaction states restore from the server message and cached session", () => {
  assert.match(turnSource, /finalMessage\?\.feedback\?\.find\(\(item\) => item\.kind === "rating"\)\?\.value/);
  assert.match(turnSource, /finalMessage\?\.knowledgeSaved/);
  assert.match(turnSource, /reportSubmitted = Boolean\(finalMessage\?\.feedback\?\.some\(\(item\) => item\.kind === "report"\)\)/);
  assert.match(turnSource, /onMessageInteractionChange\(finalMessage\.conversationId, finalMessage\.id, \{ feedback \}\)/);
  assert.match(turnSource, /aria-pressed=\{reportSubmitted\}/);
  assert.match(appSource, /onMessageInteractionChange=\{workspace\.updateMessageInteraction\}/);
  assert.match(workspaceSource, /currentFeedback\.filter\(\(item\) => item\.kind !== "rating"\)/);
  assert.match(workspaceSource, /nextMessage\.knowledgeSaved = patch\.knowledgeSaved/);
});

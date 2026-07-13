import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnSource = await readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

test("answer ratings use accessible selected states and semantic colors", () => {
  assert.match(turnSource, /aria-label="좋아요" aria-pressed=\{answerRating === "like"\}/);
  assert.match(turnSource, /aria-label="싫어요" aria-pressed=\{answerRating === "dislike"\}/);
  assert.match(turnSource, /answerRating === "like" \? "is-like"/);
  assert.match(turnSource, /answerRating === "dislike" \? "is-dislike"/);
  assert.match(styles, /answer-rating-control\.is-like[\s\S]*?color: var\(--success\)/);
  assert.match(styles, /answer-rating-control\.is-dislike[\s\S]*?color: var\(--danger\)/);
});

test("answer rating success is shown inline without a toast and failures remain visible", () => {
  assert.match(turnSource, /setAnswerRating\(value\)/);
  assert.match(turnSource, /setAnswerRating\(previousRating\)[\s\S]*?onToast\("평가를 기록하지 못했습니다\."\)/);
  assert.doesNotMatch(turnSource, /좋아요를 기록했습니다|싫어요를 기록했습니다/);
});

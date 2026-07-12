import { useCallback, useEffect, useRef, useState } from "react";

const streamStartBufferMs = 180;
const streamRevealDurationMs = 420;
const frameFallbackMs = 34;
const minRevealRate = 1 / 96;
const maxRevealRate = 0.5;
const chunkSampleSize = 3;
const minChunkIntervalMs = 24;
const maxChunkIntervalMs = 600;
const nearBottomPx = 140;
const streamingRejoinPx = 360;

export function useStreamingText(targetText: string, streaming: boolean) {
  const [visibleText, setVisibleText] = useState(() => (streaming ? "" : targetText));
  const visibleRef = useRef(visibleText);
  const pendingRef = useRef("");
  const startTimerRef = useRef<number | null>(null);
  const animationRef = useRef<number | null>(null);
  const fallbackRef = useRef<number | null>(null);
  const deadlineRef = useRef<number | null>(null);
  const lastFrameAtRef = useRef<number | null>(null);
  const revealBudgetRef = useRef(0);
  const revealRateRef = useRef(0);
  const displayStartedRef = useRef(false);
  const recentChunksRef = useRef<Array<{ chars: number; intervalMs: number }>>([]);
  const lastChunkAtRef = useRef<number | null>(null);

  const clearScheduled = useCallback(() => {
    if (startTimerRef.current !== null) window.clearTimeout(startTimerRef.current);
    if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    if (fallbackRef.current !== null) window.clearTimeout(fallbackRef.current);
    if (deadlineRef.current !== null) window.clearTimeout(deadlineRef.current);
    startTimerRef.current = null;
    animationRef.current = null;
    fallbackRef.current = null;
    deadlineRef.current = null;
    lastFrameAtRef.current = null;
    revealBudgetRef.current = 0;
    revealRateRef.current = 0;
  }, []);

  const flushAll = useCallback(() => {
    clearScheduled();
    if (!pendingRef.current) return;
    displayStartedRef.current = true;
    visibleRef.current += pendingRef.current;
    pendingRef.current = "";
    setVisibleText(visibleRef.current);
  }, [clearScheduled]);

  const retune = useCallback(() => {
    const pendingLength = Array.from(pendingRef.current).length;
    if (!pendingLength) return;
    const samples = recentChunksRef.current;
    const totalChars = samples.reduce((total, sample) => total + sample.chars, 0);
    const totalIntervalMs = samples.reduce((total, sample) => total + sample.intervalMs, 0);
    const averageChars = samples.length ? totalChars / samples.length : 0;
    const baseRate = totalChars > 0 && totalIntervalMs > 0 ? totalChars / totalIntervalMs : null;
    const backlogBoost = baseRate === null
      ? 1
      : 1 + Math.min(2.5, Math.max(0, pendingLength - averageChars * 2) / Math.max(averageChars * 4, 1));
    const targetRate = Math.max(
      minRevealRate,
      Math.min(
        maxRevealRate,
        baseRate === null ? Math.max(1 / 16, pendingLength / streamRevealDurationMs) : baseRate * 0.9 * backlogBoost,
      ),
    );
    revealRateRef.current = revealRateRef.current > 0
      ? revealRateRef.current * 0.7 + targetRate * 0.3
      : targetRate;
    if (deadlineRef.current !== null) window.clearTimeout(deadlineRef.current);
    deadlineRef.current = window.setTimeout(flushAll, streamRevealDurationMs);
  }, [flushAll]);

  const flushFrameRef = useRef<(timestamp?: number) => void>(() => undefined);
  const scheduleFrame = useCallback(() => {
    if (animationRef.current !== null || fallbackRef.current !== null) return;
    if (document.hidden) {
      flushAll();
      return;
    }
    animationRef.current = window.requestAnimationFrame((timestamp) => {
      animationRef.current = null;
      if (fallbackRef.current !== null) window.clearTimeout(fallbackRef.current);
      fallbackRef.current = null;
      flushFrameRef.current(timestamp);
    });
    fallbackRef.current = window.setTimeout(() => {
      fallbackRef.current = null;
      if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
      flushFrameRef.current(performance.now());
    }, frameFallbackMs);
  }, [flushAll]);

  flushFrameRef.current = (timestamp = performance.now()) => {
    const pending = pendingRef.current;
    if (!pending) return;
    displayStartedRef.current = true;
    const elapsed = lastFrameAtRef.current === null
      ? 16
      : Math.max(8, Math.min(64, timestamp - lastFrameAtRef.current));
    lastFrameAtRef.current = timestamp;
    if (revealRateRef.current <= 0) retune();
    revealBudgetRef.current += elapsed * revealRateRef.current;
    if (revealBudgetRef.current < 1) {
      scheduleFrame();
      return;
    }
    const chars = Array.from(pending);
    const revealCount = Math.max(1, Math.min(chars.length, Math.floor(revealBudgetRef.current)));
    revealBudgetRef.current = Math.max(0, revealBudgetRef.current - revealCount);
    visibleRef.current += chars.slice(0, revealCount).join("");
    pendingRef.current = chars.slice(revealCount).join("");
    setVisibleText(visibleRef.current);
    if (pendingRef.current) scheduleFrame();
  };

  const scheduleReveal = useCallback(() => {
    if (displayStartedRef.current) {
      scheduleFrame();
      return;
    }
    if (startTimerRef.current !== null) return;
    startTimerRef.current = window.setTimeout(() => {
      startTimerRef.current = null;
      scheduleFrame();
    }, streamStartBufferMs);
  }, [scheduleFrame]);

  useEffect(() => {
    if (!streaming) {
      clearScheduled();
      pendingRef.current = "";
      displayStartedRef.current = false;
      recentChunksRef.current = [];
      lastChunkAtRef.current = null;
      visibleRef.current = targetText;
      setVisibleText((current) => current === targetText ? current : targetText);
      return;
    }
    const queued = visibleRef.current + pendingRef.current;
    if (queued === targetText) return;
    if (targetText.startsWith(queued)) {
      const nextChunk = targetText.slice(queued.length);
      const now = performance.now();
      const chars = Array.from(nextChunk).length;
      if (displayStartedRef.current && chars > 0 && lastChunkAtRef.current !== null) {
        recentChunksRef.current = [
          ...recentChunksRef.current,
          {
            chars,
            intervalMs: Math.max(minChunkIntervalMs, Math.min(maxChunkIntervalMs, now - lastChunkAtRef.current)),
          },
        ].slice(-chunkSampleSize);
      }
      if (displayStartedRef.current && chars > 0) lastChunkAtRef.current = now;
      pendingRef.current += nextChunk;
      retune();
      scheduleReveal();
      return;
    }
    clearScheduled();
    pendingRef.current = "";
    displayStartedRef.current = true;
    recentChunksRef.current = [];
    lastChunkAtRef.current = null;
    visibleRef.current = targetText;
    setVisibleText(targetText);
  }, [clearScheduled, retune, scheduleReveal, streaming, targetText]);

  useEffect(() => clearScheduled, [clearScheduled]);

  return { visibleText, revealing: streaming || visibleText !== targetText };
}

export function useConversationAutoFollow(active: boolean, conversationId: string | null) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const followingRef = useRef(true);
  const animationRef = useRef<number | null>(null);
  const userIntentUntilRef = useRef(0);

  const stop = useCallback(() => {
    followingRef.current = false;
    if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    animationRef.current = null;
  }, []);

  const follow = useCallback((immediate = false) => {
    const container = containerRef.current;
    if (!container || !followingRef.current) return;
    if (animationRef.current !== null) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (immediate || reduceMotion || document.hidden) {
      container.scrollTop = container.scrollHeight;
      return;
    }
    const step = () => {
      const current = containerRef.current;
      if (!current || !followingRef.current) {
        animationRef.current = null;
        return;
      }
      const target = Math.max(0, current.scrollHeight - current.clientHeight);
      const distance = target - current.scrollTop;
      current.scrollTop += Math.max(1, distance * 0.2);
      if (distance <= 1) {
        current.scrollTop = target;
        animationRef.current = null;
        return;
      }
      animationRef.current = window.requestAnimationFrame(step);
    };
    animationRef.current = window.requestAnimationFrame(step);
  }, []);

  useEffect(() => {
    followingRef.current = true;
    window.requestAnimationFrame(() => follow(true));
  }, [conversationId, follow]);

  useEffect(() => {
    if (active && Date.now() > userIntentUntilRef.current) followingRef.current = true;
    if (active) follow();
  }, [active, follow]);

  useEffect(() => {
    const container = containerRef.current;
    const content = container?.firstElementChild;
    if (!container || !content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => follow());
    observer.observe(content);
    return () => observer.disconnect();
  }, [conversationId, follow]);

  useEffect(() => () => {
    if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
  }, []);

  const onScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const distance = container.scrollHeight - container.clientHeight - container.scrollTop;
    if (distance <= nearBottomPx) {
      followingRef.current = true;
      return;
    }
    if (distance > streamingRejoinPx) stop();
  }, [stop]);

  const onUserIntent = useCallback(() => {
    userIntentUntilRef.current = Date.now() + 900;
    stop();
  }, [stop]);

  const onWheel = useCallback((deltaY: number) => {
    if (deltaY < 0) onUserIntent();
  }, [onUserIntent]);

  const onPointerDown = useCallback(() => {
    userIntentUntilRef.current = Date.now() + 900;
  }, []);

  const jumpToLatest = useCallback(() => {
    followingRef.current = true;
    const container = containerRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, []);

  return {
    containerRef,
    onScroll,
    onUserIntent,
    onWheel,
    onPointerDown,
    jumpToLatest,
    follow,
    notifyGrowth: follow,
  };
}

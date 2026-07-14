import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

const streamStartBufferMs = 180;
const streamRevealDurationMs = 420;
const visibleFrameIntervalMs = 50;
const frameFallbackMs = 100;
const streamCatchUpDeadlineMs = 1_200;
const minRevealRate = 1 / 96;
const maxRevealRate = 0.5;
const chunkSampleSize = 3;
const minChunkIntervalMs = 24;
const maxChunkIntervalMs = 600;
const nearBottomPx = 140;
const streamingRejoinPx = 360;
const jumpButtonThresholdPx = 40;
const exactBottomPx = 2;
const scrollPositionStoragePrefix = "lumina:conversation-scroll:";

type ConversationScrollPosition = {
  top: number;
  atBottom: boolean;
};

function readConversationScrollPosition(conversationId: string) {
  try {
    const stored = sessionStorage.getItem(`${scrollPositionStoragePrefix}${conversationId}`);
    if (!stored) return null;
    const parsed = JSON.parse(stored) as Partial<ConversationScrollPosition>;
    if (!Number.isFinite(parsed.top) || typeof parsed.atBottom !== "boolean") return null;
    return { top: Math.max(0, parsed.top as number), atBottom: parsed.atBottom };
  } catch {
    return null;
  }
}

function writeConversationScrollPosition(conversationId: string, position: ConversationScrollPosition) {
  try {
    sessionStorage.setItem(`${scrollPositionStoragePrefix}${conversationId}`, JSON.stringify(position));
  } catch {
    // Browsing modes that disable storage should not break conversation navigation.
  }
}

function smoothRevealCount(pendingLength: number, desiredCount: number) {
  if (!pendingLength || desiredCount <= 0) return 0;
  const maxTickChars = pendingLength >= 1_400
    ? 24
    : pendingLength >= 700
      ? 16
      : pendingLength >= 220
        ? 12
        : pendingLength >= 40
          ? 8
          : 4;
  return Math.min(pendingLength, Math.max(1, Math.min(maxTickChars, desiredCount)));
}

export function useStreamingText(targetText: string, streaming: boolean) {
  const [visibleText, setVisibleText] = useState(() => (streaming ? "" : targetText));
  const visibleRef = useRef(visibleText);
  const pendingRef = useRef("");
  const startTimerRef = useRef<number | null>(null);
  const frameTimerRef = useRef<number | null>(null);
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
    if (frameTimerRef.current !== null) window.clearTimeout(frameTimerRef.current);
    if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    if (fallbackRef.current !== null) window.clearTimeout(fallbackRef.current);
    if (deadlineRef.current !== null) window.clearTimeout(deadlineRef.current);
    startTimerRef.current = null;
    frameTimerRef.current = null;
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
    deadlineRef.current = window.setTimeout(
      flushAll,
      Math.max(streamCatchUpDeadlineMs, streamRevealDurationMs * 3),
    );
  }, [flushAll]);

  const flushFrameRef = useRef<(timestamp?: number) => void>(() => undefined);
  const scheduleFrame = useCallback(() => {
    if (frameTimerRef.current !== null || animationRef.current !== null || fallbackRef.current !== null) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) {
      flushAll();
      return;
    }
    if (document.hidden) {
      flushAll();
      return;
    }
    frameTimerRef.current = window.setTimeout(() => {
      frameTimerRef.current = null;
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
    }, visibleFrameIntervalMs);
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
    const revealCount = smoothRevealCount(chars.length, Math.floor(revealBudgetRef.current));
    if (revealCount <= 0) {
      scheduleFrame();
      return;
    }
    revealBudgetRef.current = Math.max(0, revealBudgetRef.current - revealCount);
    visibleRef.current += chars.slice(0, revealCount).join("");
    pendingRef.current = chars.slice(revealCount).join("");
    setVisibleText(visibleRef.current);
    if (pendingRef.current) scheduleFrame();
  };

  const scheduleReveal = useCallback(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) {
      flushAll();
      return;
    }
    if (displayStartedRef.current) {
      scheduleFrame();
      return;
    }
    if (startTimerRef.current !== null) return;
    startTimerRef.current = window.setTimeout(() => {
      startTimerRef.current = null;
      scheduleFrame();
    }, streamStartBufferMs);
  }, [flushAll, scheduleFrame]);

  useEffect(() => {
    if (!streaming) {
      recentChunksRef.current = [];
      lastChunkAtRef.current = null;
      const queued = visibleRef.current + pendingRef.current;
      if (queued === targetText) {
        if (pendingRef.current) {
          retune();
          scheduleReveal();
        }
        return;
      }
      if (targetText.startsWith(visibleRef.current)) {
        pendingRef.current = targetText.slice(visibleRef.current.length);
        retune();
        scheduleReveal();
        return;
      }
      clearScheduled();
      pendingRef.current = "";
      displayStartedRef.current = false;
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

export function useConversationAutoFollow(
  active: boolean,
  conversationId: string | null,
  contentReady: boolean,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const followingRef = useRef(true);
  const animationRef = useRef<number | null>(null);
  const userIntentUntilRef = useRef(0);
  const activeRef = useRef(active);
  const savedPositionsRef = useRef(new Map<string, ConversationScrollPosition>());
  const saveTimersRef = useRef(new Map<string, number>());
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  activeRef.current = active;

  const flushPosition = useCallback((targetConversationId: string) => {
    const timer = saveTimersRef.current.get(targetConversationId);
    if (timer !== undefined) window.clearTimeout(timer);
    saveTimersRef.current.delete(targetConversationId);
    const position = savedPositionsRef.current.get(targetConversationId);
    if (position) writeConversationScrollPosition(targetConversationId, position);
  }, []);

  const rememberPosition = useCallback((targetConversationId: string, container: HTMLDivElement) => {
    const distance = container.scrollHeight - container.clientHeight - container.scrollTop;
    savedPositionsRef.current.set(targetConversationId, {
      top: Math.max(0, container.scrollTop),
      atBottom: distance <= exactBottomPx,
    });
    const existingTimer = saveTimersRef.current.get(targetConversationId);
    if (existingTimer !== undefined) window.clearTimeout(existingTimer);
    saveTimersRef.current.set(targetConversationId, window.setTimeout(() => {
      flushPosition(targetConversationId);
    }, 120));
  }, [flushPosition]);

  const updateJumpVisibility = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const distance = container.scrollHeight - container.clientHeight - container.scrollTop;
    setShowJumpToLatest(distance > jumpButtonThresholdPx);
  }, []);

  const stop = useCallback(() => {
    followingRef.current = false;
    if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    animationRef.current = null;
  }, []);

  const follow = useCallback((immediate = false, animateWhenHidden = false, force = false) => {
    const container = containerRef.current;
    if (!container || (!activeRef.current && !force) || !followingRef.current) return;
    if (animationRef.current !== null) return;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (immediate || reduceMotion || (document.hidden && !animateWhenHidden)) {
      container.scrollTop = container.scrollHeight;
      setShowJumpToLatest(false);
      return;
    }
    let previousFrameAt = performance.now();
    let followVelocity = 0;
    let lastTarget = Math.max(0, container.scrollHeight - container.clientHeight);
    let targetStableMs = 0;
    const step = (now: number) => {
      const current = containerRef.current;
      if (!current || !followingRef.current) {
        animationRef.current = null;
        return;
      }
      const target = Math.max(0, current.scrollHeight - current.clientHeight);
      const elapsed = Math.min(64, Math.max(8, now - previousFrameAt));
      previousFrameAt = now;
      if (Math.abs(target - lastTarget) > 0.5) {
        lastTarget = target;
        targetStableMs = 0;
      } else {
        targetStableMs += elapsed;
      }
      const distance = target - current.scrollTop;
      const dt = elapsed / 1_000;
      const responseMs = 340;
      const omega = (1_000 / responseMs) * 2.25;
      const acceleration = distance * omega * omega - followVelocity * 2 * omega;
      const maxAcceleration = Math.max(12_000, Math.min(42_000, current.clientHeight * 70));
      followVelocity += Math.max(-maxAcceleration, Math.min(maxAcceleration, acceleration)) * dt;
      const maxVelocity = Math.max(520, Math.min(4_200, current.clientHeight * 4 + Math.abs(distance) * 3));
      followVelocity = Math.max(0, Math.min(maxVelocity, followVelocity));
      const nextTop = current.scrollTop + followVelocity * dt;
      current.scrollTop = Math.max(current.scrollTop, Math.min(target, nextTop));
      const remaining = target - current.scrollTop;
      if (targetStableMs > 120 && remaining <= Math.max(1, followVelocity * dt)) {
        current.scrollTop = target;
        setShowJumpToLatest(false);
        animationRef.current = null;
        return;
      }
      animationRef.current = window.requestAnimationFrame(step);
    };
    animationRef.current = window.requestAnimationFrame(step);
  }, []);

  useLayoutEffect(() => {
    if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    animationRef.current = null;
    followingRef.current = false;
    setShowJumpToLatest(false);
    if (!conversationId || !contentReady) return undefined;

    const container = containerRef.current;
    if (!container) return undefined;
    const stored = savedPositionsRef.current.get(conversationId)
      ?? readConversationScrollPosition(conversationId);
    const maximumTop = Math.max(0, container.scrollHeight - container.clientHeight);
    const targetTop = stored
      ? stored.atBottom ? maximumTop : Math.min(stored.top, maximumTop)
      : maximumTop;
    container.scrollTop = targetTop;
    const restoredPosition = {
      top: targetTop,
      atBottom: maximumTop - targetTop <= exactBottomPx,
    };
    savedPositionsRef.current.set(conversationId, restoredPosition);
    followingRef.current = restoredPosition.atBottom;
    setShowJumpToLatest(maximumTop - targetTop > jumpButtonThresholdPx);

    return () => flushPosition(conversationId);
  }, [contentReady, conversationId, flushPosition]);

  useEffect(() => {
    if (active) follow();
  }, [active, follow]);

  useEffect(() => {
    const container = containerRef.current;
    const content = container?.firstElementChild;
    if (!container || !content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const remembered = conversationId ? savedPositionsRef.current.get(conversationId) : null;
      if (!activeRef.current && conversationId && remembered?.atBottom) {
        const maximumTop = Math.max(0, container.scrollHeight - container.clientHeight);
        container.scrollTop = maximumTop;
        savedPositionsRef.current.set(conversationId, { top: maximumTop, atBottom: true });
      }
      updateJumpVisibility();
      follow();
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [conversationId, follow, updateJumpVisibility]);

  useEffect(() => () => {
    if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    for (const targetConversationId of savedPositionsRef.current.keys()) flushPosition(targetConversationId);
  }, []);

  const onScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const distance = container.scrollHeight - container.clientHeight - container.scrollTop;
    if (conversationId) rememberPosition(conversationId, container);
    updateJumpVisibility();
    if (distance <= nearBottomPx) {
      followingRef.current = true;
      return;
    }
    if (distance > streamingRejoinPx && Date.now() <= userIntentUntilRef.current) stop();
  }, [conversationId, rememberPosition, stop, updateJumpVisibility]);

  const onUserIntent = useCallback(() => {
    userIntentUntilRef.current = Date.now() + 900;
    stop();
  }, [stop]);

  const onWheel = useCallback((deltaY: number) => {
    if (deltaY < 0) onUserIntent();
  }, [onUserIntent]);

  const onPointerDown = useCallback(() => {
    onUserIntent();
  }, [onUserIntent]);

  const jumpToLatest = useCallback(() => {
    followingRef.current = true;
    follow(false, true, true);
  }, [follow]);

  return {
    containerRef,
    onScroll,
    onUserIntent,
    onWheel,
    onPointerDown,
    jumpToLatest,
    showJumpToLatest,
    follow,
    notifyGrowth: follow,
  };
}

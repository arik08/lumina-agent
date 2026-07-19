import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

const streamStartBufferMs = 40;
const maxVisualLagMs = 180;
const renderCommitReserveMs = 80;
const visibleFrameIntervalMs = 15;
const frameFallbackMs = 100;
const streamSettleDurationMs = 180;
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

function commonPrefixLength(left: string, right: string) {
  const limit = Math.min(left.length, right.length);
  let index = 0;
  while (index < limit && left[index] === right[index]) index += 1;
  return index;
}

function smoothBufferedRevealCount(pendingLength: number, remainingMs: number) {
  if (pendingLength <= 0) return 0;
  const remainingFrames = Math.max(1, Math.ceil(remainingMs / visibleFrameIntervalMs));
  return Math.min(pendingLength, Math.max(1, Math.ceil(pendingLength / remainingFrames)));
}

export function useStreamingText(targetText: string, streaming: boolean) {
  const [visibleText, setVisibleText] = useState(() => (streaming ? "" : targetText));
  const [settling, setSettling] = useState(false);
  const visibleRef = useRef(visibleText);
  const pendingRef = useRef(targetText);
  const startTimerRef = useRef<number | null>(null);
  const frameTimerRef = useRef<number | null>(null);
  const animationRef = useRef<number | null>(null);
  const fallbackRef = useRef<number | null>(null);
  const lastFrameAtRef = useRef(0);
  const pendingStartedAtRef = useRef<number | null>(null);
  const displayStartedRef = useRef(false);
  const settleTimerRef = useRef<number | null>(null);

  const clearScheduled = useCallback(() => {
    if (startTimerRef.current !== null) window.clearTimeout(startTimerRef.current);
    if (frameTimerRef.current !== null) window.clearTimeout(frameTimerRef.current);
    if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    if (fallbackRef.current !== null) window.clearTimeout(fallbackRef.current);
    startTimerRef.current = null;
    frameTimerRef.current = null;
    animationRef.current = null;
    fallbackRef.current = null;
  }, []);

  const flushAll = useCallback((timestamp = performance.now()) => {
    clearScheduled();
    displayStartedRef.current = true;
    lastFrameAtRef.current = timestamp;
    const nextText = pendingRef.current;
    if (visibleRef.current === nextText) return;
    visibleRef.current = nextText;
    pendingStartedAtRef.current = null;
    setVisibleText(nextText);
  }, [clearScheduled]);

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
    const elapsed = performance.now() - lastFrameAtRef.current;
    const delay = Math.max(0, visibleFrameIntervalMs - elapsed);
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
    }, delay);
  }, [flushAll]);

  flushFrameRef.current = (timestamp = performance.now()) => {
    displayStartedRef.current = true;
    lastFrameAtRef.current = timestamp;
    const target = pendingRef.current;
    if (visibleRef.current === target) {
      pendingStartedAtRef.current = null;
      return;
    }
    if (!target.startsWith(visibleRef.current)) {
      visibleRef.current = target.slice(0, commonPrefixLength(visibleRef.current, target));
    }
    const pendingStartedAt = pendingStartedAtRef.current ?? timestamp;
    pendingStartedAtRef.current = pendingStartedAt;
    const pendingCharacters = Array.from(target.slice(visibleRef.current.length));
    const remainingMs = Math.max(
      visibleFrameIntervalMs,
      pendingStartedAt + maxVisualLagMs - renderCommitReserveMs - timestamp,
    );
    const revealCount = smoothBufferedRevealCount(pendingCharacters.length, remainingMs);
    visibleRef.current += pendingCharacters.slice(0, revealCount).join("");
    setVisibleText(visibleRef.current);
    if (visibleRef.current !== pendingRef.current) scheduleFrame();
    else pendingStartedAtRef.current = null;
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
    pendingRef.current = targetText;
    if (!targetText.startsWith(visibleRef.current)) {
      clearScheduled();
      visibleRef.current = targetText.slice(0, commonPrefixLength(visibleRef.current, targetText));
      displayStartedRef.current = visibleRef.current.length > 0;
      setVisibleText((current) => current === visibleRef.current ? current : visibleRef.current);
    }
    if (visibleRef.current !== targetText) {
      pendingStartedAtRef.current ??= performance.now();
      scheduleReveal();
    } else {
      pendingStartedAtRef.current = null;
    }
  }, [clearScheduled, scheduleReveal, streaming, targetText]);

  useEffect(() => clearScheduled, [clearScheduled]);

  useEffect(() => {
    if (streaming || visibleText !== targetText || !displayStartedRef.current) {
      if (settleTimerRef.current !== null) window.clearTimeout(settleTimerRef.current);
      settleTimerRef.current = null;
      setSettling(false);
      return;
    }
    setSettling(true);
    settleTimerRef.current = window.setTimeout(() => {
      settleTimerRef.current = null;
      displayStartedRef.current = false;
      setSettling(false);
    }, streamSettleDurationMs);
    return () => {
      if (settleTimerRef.current !== null) window.clearTimeout(settleTimerRef.current);
      settleTimerRef.current = null;
    };
  }, [streaming, targetText, visibleText]);

  return { visibleText, revealing: streaming || visibleText !== targetText || settling, settling };
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
  const conversationIdRef = useRef(conversationId);
  const programmaticScrollMarkerRef = useRef(0);
  const programmaticScrollUntilRef = useRef(0);
  const savedPositionsRef = useRef(new Map<string, ConversationScrollPosition>());
  const saveTimersRef = useRef(new Map<string, number>());
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  activeRef.current = active;
  conversationIdRef.current = conversationId;

  const flushPosition = useCallback((targetConversationId: string) => {
    const timer = saveTimersRef.current.get(targetConversationId);
    if (timer !== undefined) window.clearTimeout(timer);
    saveTimersRef.current.delete(targetConversationId);
    const position = savedPositionsRef.current.get(targetConversationId);
    if (position) writeConversationScrollPosition(targetConversationId, position);
  }, []);

  const rememberPosition = useCallback((targetConversationId: string, top: number, distance: number) => {
    savedPositionsRef.current.set(targetConversationId, {
      top: Math.max(0, top),
      atBottom: distance <= exactBottomPx,
    });
    const existingTimer = saveTimersRef.current.get(targetConversationId);
    if (existingTimer !== undefined) window.clearTimeout(existingTimer);
    saveTimersRef.current.set(targetConversationId, window.setTimeout(() => {
      flushPosition(targetConversationId);
    }, 120));
  }, [flushPosition]);

  const updateJumpVisibility = useCallback((knownDistance?: number) => {
    const container = containerRef.current;
    if (!container) return;
    const distance = knownDistance ?? container.scrollHeight - container.clientHeight - container.scrollTop;
    setShowJumpToLatest(!followingRef.current && distance > jumpButtonThresholdPx);
  }, []);

  const setProgrammaticScrollTop = useCallback((container: HTMLDivElement, top: number, atBottom: boolean) => {
    const marker = programmaticScrollMarkerRef.current + 1;
    programmaticScrollMarkerRef.current = marker;
    programmaticScrollUntilRef.current = performance.now() + 80;
    container.dataset.programmaticScroll = "true";
    container.scrollTop = top;
    const targetConversationId = conversationIdRef.current;
    if (targetConversationId) {
      savedPositionsRef.current.set(targetConversationId, { top, atBottom });
    }
    window.requestAnimationFrame(() => {
      if (programmaticScrollMarkerRef.current === marker) {
        delete container.dataset.programmaticScroll;
      }
    });
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
      const target = Math.max(0, container.scrollHeight - container.clientHeight);
      setProgrammaticScrollTop(container, target, true);
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
      const maxAcceleration = Math.max(18_000, Math.min(90_000, current.clientHeight * 110));
      followVelocity += Math.max(-maxAcceleration, Math.min(maxAcceleration, acceleration)) * dt;
      const maxVelocity = Math.max(700, Math.min(9_000, current.clientHeight * 7 + Math.abs(distance) * 4));
      followVelocity = Math.max(0, Math.min(maxVelocity, followVelocity));
      const maxFrameScrollDistance = Math.max(32, Math.min(96, current.clientHeight * 0.12));
      const frameScrollDistance = Math.min(maxFrameScrollDistance, followVelocity * dt);
      const nextTop = current.scrollTop + frameScrollDistance;
      setProgrammaticScrollTop(current, Math.max(current.scrollTop, Math.min(target, nextTop)), false);
      const remaining = target - current.scrollTop;
      if (targetStableMs > 120 && remaining <= Math.max(1, frameScrollDistance)) {
        setProgrammaticScrollTop(current, target, true);
        setShowJumpToLatest(false);
        animationRef.current = null;
        return;
      }
      animationRef.current = window.requestAnimationFrame(step);
    };
    animationRef.current = window.requestAnimationFrame(step);
  }, [setProgrammaticScrollTop]);

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
    setProgrammaticScrollTop(container, targetTop, maximumTop - targetTop <= exactBottomPx);
    const restoredPosition = {
      top: targetTop,
      atBottom: maximumTop - targetTop <= exactBottomPx,
    };
    savedPositionsRef.current.set(conversationId, restoredPosition);
    followingRef.current = restoredPosition.atBottom;
    setShowJumpToLatest(maximumTop - targetTop > jumpButtonThresholdPx);

    return () => flushPosition(conversationId);
  }, [contentReady, conversationId, flushPosition, setProgrammaticScrollTop]);

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
        setProgrammaticScrollTop(container, maximumTop, true);
      }
      updateJumpVisibility();
      follow();
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [conversationId, follow, setProgrammaticScrollTop, updateJumpVisibility]);

  useEffect(() => () => {
    if (animationRef.current !== null) window.cancelAnimationFrame(animationRef.current);
    if (containerRef.current) delete containerRef.current.dataset.programmaticScroll;
    for (const targetConversationId of savedPositionsRef.current.keys()) flushPosition(targetConversationId);
  }, []);

  const onScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    if (container.dataset.programmaticScroll === "true" || performance.now() <= programmaticScrollUntilRef.current) return;
    const scrollTop = container.scrollTop;
    const distance = container.scrollHeight - container.clientHeight - scrollTop;
    if (conversationId) rememberPosition(conversationId, scrollTop, distance);
    if (distance <= nearBottomPx) {
      followingRef.current = true;
      setShowJumpToLatest(false);
      return;
    }
    if (distance > streamingRejoinPx && Date.now() <= userIntentUntilRef.current) stop();
    updateJumpVisibility(distance);
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
    setShowJumpToLatest(false);
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
  };
}

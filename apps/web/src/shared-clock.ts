import { useCallback, useSyncExternalStore } from "react";

interface ClockState {
  current: number;
  listeners: Set<() => void>;
  timer: number | null;
}

const clocks = new Map<number, ClockState>();

function clockState(resolutionMs: number) {
  const resolution = Math.max(50, Math.round(resolutionMs));
  let state = clocks.get(resolution);
  if (!state) {
    state = { current: Date.now(), listeners: new Set(), timer: null };
    clocks.set(resolution, state);
  }
  return { resolution, state };
}

function subscribe(resolutionMs: number, listener: () => void) {
  const { resolution, state } = clockState(resolutionMs);
  state.listeners.add(listener);
  state.current = Date.now();
  if (state.timer === null) {
    state.timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      state.current = Date.now();
      state.listeners.forEach((notify) => notify());
    }, resolution);
  }
  return () => {
    state.listeners.delete(listener);
    if (state.listeners.size === 0 && state.timer !== null) {
      window.clearInterval(state.timer);
      state.timer = null;
    }
  };
}

function snapshot(resolutionMs: number) {
  return clockState(resolutionMs).state.current;
}

export function useSharedNow(active: boolean, resolutionMs = 1_000) {
  const subscribeActive = useCallback(
    (listener: () => void) => active ? subscribe(resolutionMs, listener) : () => {},
    [active, resolutionMs],
  );
  const getSnapshot = useCallback(() => snapshot(resolutionMs), [resolutionMs]);
  return useSyncExternalStore(subscribeActive, getSnapshot, getSnapshot);
}

import { useCallback, useSyncExternalStore } from "react";
import type { RunSnapshot } from "./api-types";

export type RunArtifactProgress = RunSnapshot["artifactProgress"];

const progressByRun = new Map<string, RunArtifactProgress>();
const listeners = new Map<string, Set<() => void>>();

function sameProgress(left: RunArtifactProgress, right: RunArtifactProgress) {
  return left?.tokens === right?.tokens
    && left?.lines === right?.lines
    && left?.estimated === right?.estimated
    && left?.targetTokens === right?.targetTokens
    && left?.modelOutputTokens === right?.modelOutputTokens;
}

export function setRunArtifactProgress(runId: string, progress: RunArtifactProgress) {
  const current = progressByRun.get(runId) ?? null;
  if (sameProgress(current, progress)) return;
  if (progress) progressByRun.set(runId, progress);
  else progressByRun.delete(runId);
  listeners.get(runId)?.forEach((listener) => listener());
}

export function useRunArtifactProgress(
  runId: string | null,
  fallback: RunArtifactProgress,
) {
  const subscribe = useCallback((listener: () => void) => {
    if (!runId) return () => undefined;
    const runListeners = listeners.get(runId) ?? new Set<() => void>();
    runListeners.add(listener);
    listeners.set(runId, runListeners);
    return () => {
      runListeners.delete(listener);
      if (runListeners.size === 0) listeners.delete(runId);
    };
  }, [runId]);
  const getSnapshot = useCallback(
    () => runId ? progressByRun.get(runId) ?? fallback : fallback,
    [fallback, runId],
  );
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

import { useCallback, useSyncExternalStore } from "react";
import type { RunSnapshot } from "./api-types";

export type RunAssistantDraft = RunSnapshot["assistantDraft"];

const drafts = new Map<string, RunAssistantDraft>();
const listeners = new Map<string, Set<() => void>>();
const pendingRunIds = new Set<string>();
let pendingFrame: number | null = null;

function flush() {
  pendingFrame = null;
  const runIds = [...pendingRunIds];
  pendingRunIds.clear();
  runIds.forEach((runId) => listeners.get(runId)?.forEach((listener) => listener()));
}

function emit(runId: string) {
  pendingRunIds.add(runId);
  if (pendingFrame !== null) return;
  if (typeof requestAnimationFrame === "function") {
    pendingFrame = requestAnimationFrame(flush);
  } else {
    pendingFrame = -1;
    queueMicrotask(flush);
  }
}

export function setRunAssistantDraft(runId: string, draft: RunAssistantDraft) {
  const current = drafts.get(runId) ?? null;
  if (current?.messageId === draft?.messageId && current?.text === draft?.text) return;
  if (draft) drafts.set(runId, draft);
  else drafts.delete(runId);
  emit(runId);
}

export function appendRunAssistantDraft(runId: string, messageId: string, delta: string) {
  if (!delta) return;
  const current = drafts.get(runId);
  drafts.set(runId, {
    messageId,
    text: `${current?.messageId === messageId ? current.text : ""}${delta}`,
  });
  emit(runId);
}

export function advanceRunAssistantDraft(runId: string, draft: NonNullable<RunAssistantDraft>) {
  const current = drafts.get(runId);
  if (current?.messageId === draft.messageId && current.text.length > draft.text.length) return;
  setRunAssistantDraft(runId, draft);
}

export function useRunAssistantDraft(runId: string | null, fallback: RunAssistantDraft) {
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
    () => runId ? drafts.get(runId) ?? fallback : fallback,
    [fallback, runId],
  );
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

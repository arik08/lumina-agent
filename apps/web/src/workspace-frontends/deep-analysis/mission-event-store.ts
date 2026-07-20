import { useCallback, useSyncExternalStore } from "react";
import type { DeepAnalysisMissionEvent } from "../../api-types";

const emptyEvents: DeepAnalysisMissionEvent[] = [];
const eventLimit = 1_000;
const missionCacheLimit = 24;
const eventsByMission = new Map<string, DeepAnalysisMissionEvent[]>();
const listenersByMission = new Map<string, Set<() => void>>();

function outputProgressKey(event: DeepAnalysisMissionEvent) {
  if (event.type !== "node_output_delta") return null;
  const nodeIdentity = event.payload.nodeKey ?? event.payload.nodeId ?? event.payload.runId ?? "mission";
  return `${event.type}:${String(nodeIdentity)}`;
}

export function compactMissionEvents(events: DeepAnalysisMissionEvent[]) {
  const seenOutputProgress = new Set<string>();
  const compacted: DeepAnalysisMissionEvent[] = [];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const progressKey = outputProgressKey(event);
    if (progressKey) {
      if (seenOutputProgress.has(progressKey)) continue;
      seenOutputProgress.add(progressKey);
    }
    compacted.push(event);
  }
  return compacted.reverse().slice(-eventLimit);
}

function touchMission(missionId: string, events: DeepAnalysisMissionEvent[]) {
  eventsByMission.delete(missionId);
  eventsByMission.set(missionId, events);
  while (eventsByMission.size > missionCacheLimit) {
    const oldestMissionId = eventsByMission.keys().next().value;
    if (typeof oldestMissionId !== "string") break;
    eventsByMission.delete(oldestMissionId);
    listenersByMission.delete(oldestMissionId);
  }
}

function emit(missionId: string) {
  listenersByMission.get(missionId)?.forEach((listener) => listener());
}

export function setMissionEvents(missionId: string, events: DeepAnalysisMissionEvent[]) {
  const current = eventsByMission.get(missionId) ?? emptyEvents;
  const currentSequences = new Set(current.map((event) => event.sequence));
  const next = events.length === 0
    ? emptyEvents
    : compactMissionEvents([
        ...current,
        ...events.filter((event) => !currentSequences.has(event.sequence)),
      ].sort((left, right) => left.sequence - right.sequence));
  touchMission(missionId, next);
  emit(missionId);
}

export function appendMissionEvent(missionId: string, event: DeepAnalysisMissionEvent) {
  const current = eventsByMission.get(missionId) ?? emptyEvents;
  if (current.some((item) => item.sequence === event.sequence)) return;
  const progressKey = outputProgressKey(event);
  const previousProgressIndex = progressKey
    ? current.findIndex((item) => outputProgressKey(item) === progressKey)
    : -1;
  const next = previousProgressIndex >= 0
    ? [...current.slice(0, previousProgressIndex), ...current.slice(previousProgressIndex + 1), event]
    : [...current, event];
  touchMission(missionId, next.slice(-eventLimit));
  emit(missionId);
}

function subscribe(missionId: string | null, listener: () => void) {
  if (!missionId) return () => undefined;
  const listeners = listenersByMission.get(missionId) ?? new Set<() => void>();
  listeners.add(listener);
  listenersByMission.set(missionId, listeners);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) listenersByMission.delete(missionId);
  };
}

export function useMissionEvents(missionId: string | null) {
  const subscribeToMission = useCallback(
    (listener: () => void) => subscribe(missionId, listener),
    [missionId],
  );
  const getSnapshot = useCallback(
    () => missionId ? eventsByMission.get(missionId) ?? emptyEvents : emptyEvents,
    [missionId],
  );
  return useSyncExternalStore(subscribeToMission, getSnapshot, getSnapshot);
}

export function useMissionEventCount(missionId: string | null) {
  const subscribeToMission = useCallback(
    (listener: () => void) => subscribe(missionId, listener),
    [missionId],
  );
  const getSnapshot = useCallback(
    () => missionId ? eventsByMission.get(missionId)?.length ?? 0 : 0,
    [missionId],
  );
  return useSyncExternalStore(subscribeToMission, getSnapshot, getSnapshot);
}

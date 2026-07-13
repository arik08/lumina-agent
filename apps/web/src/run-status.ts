import type { RunEvent, RunStatus } from "./api-types";

const TERMINAL_RUN_STATUSES: ReadonlySet<RunStatus> = new Set([
  "completed",
  "failed",
  "cancelled",
  "limit_reached",
  "interrupted",
]);

type TerminalRunEventType = "run_completed" | "run_failed" | "run_cancelled" | "run_interrupted";
type TerminalRunEvent = Extract<RunEvent, { type: TerminalRunEventType }>;

const TERMINAL_RUN_EVENT_TYPES: ReadonlySet<RunEvent["type"]> = new Set([
  "run_completed",
  "run_failed",
  "run_cancelled",
  "run_interrupted",
]);

export function isTerminalRunStatus(status: RunStatus | null | undefined): status is RunStatus {
  return status !== null && status !== undefined && TERMINAL_RUN_STATUSES.has(status);
}

export function isTerminalRunEvent(event: RunEvent): event is TerminalRunEvent {
  return TERMINAL_RUN_EVENT_TYPES.has(event.type);
}

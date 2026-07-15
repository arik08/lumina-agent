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

export function shouldCollapseRunWorkDetails(status: RunStatus | null | undefined): boolean {
  return status === "completed";
}

export type RunActivityOutcome = "running" | "completed" | "stopped" | "failed";

export function runActivityOutcome(status: RunStatus | null | undefined): RunActivityOutcome {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "cancelled" || status === "interrupted" || status === "limit_reached") return "stopped";
  return "running";
}

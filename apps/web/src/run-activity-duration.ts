export interface ProgressStageBoundary {
  id: string;
  createdAt: string;
}

export interface ProgressStageTiming {
  startedAtMs: number;
  finishedAtMs: number;
  durationMs: number;
}

export interface TimedExecution {
  startedAt: string | null;
  completedAt: string | null;
}

export function progressStageTimingById(
  stages: ProgressStageBoundary[],
  timelineStartedAtMs: number,
  timelineFinishedAtMs: number,
) {
  const timings = new Map<string, ProgressStageTiming>();

  stages.forEach((stage, index) => {
    const stageCreatedAtMs = new Date(stage.createdAt).getTime();
    const firstStageStartedAtMs = Number.isFinite(timelineStartedAtMs)
      && timelineStartedAtMs <= stageCreatedAtMs
      ? timelineStartedAtMs
      : stageCreatedAtMs;
    const startedAtMs = index === 0 ? firstStageStartedAtMs : stageCreatedAtMs;
    const nextStageCreatedAtMs = stages[index + 1]
      ? new Date(stages[index + 1].createdAt).getTime()
      : timelineFinishedAtMs;

    if (!Number.isFinite(startedAtMs) || !Number.isFinite(nextStageCreatedAtMs) || nextStageCreatedAtMs < startedAtMs) return;
    timings.set(stage.id, {
      startedAtMs,
      finishedAtMs: nextStageCreatedAtMs,
      durationMs: nextStageCreatedAtMs - startedAtMs,
    });
  });

  return timings;
}

export function progressStageDurationById(
  stages: ProgressStageBoundary[],
  timelineStartedAtMs: number,
  timelineFinishedAtMs: number,
) {
  const durations = new Map<string, number>();
  progressStageTimingById(stages, timelineStartedAtMs, timelineFinishedAtMs).forEach((timing, id) => {
    durations.set(id, timing.durationMs);
  });
  return durations;
}

export function mergedToolActiveDurationMs(
  executions: TimedExecution[],
  intervalStartedAtMs: number,
  intervalFinishedAtMs: number,
) {
  const intervals = executions.flatMap((execution) => {
    if (!execution.startedAt) return [];
    const startedAtMs = Math.max(intervalStartedAtMs, new Date(execution.startedAt).getTime());
    const completedAtMs = execution.completedAt
      ? new Date(execution.completedAt).getTime()
      : intervalFinishedAtMs;
    const finishedAtMs = Math.min(intervalFinishedAtMs, completedAtMs);
    return Number.isFinite(startedAtMs) && Number.isFinite(finishedAtMs) && finishedAtMs >= startedAtMs
      ? [{ startedAtMs, finishedAtMs }]
      : [];
  }).sort((left, right) => left.startedAtMs - right.startedAtMs);

  const merged: Array<{ startedAtMs: number; finishedAtMs: number }> = [];
  for (const interval of intervals) {
    const previous = merged.at(-1);
    if (!previous || interval.startedAtMs > previous.finishedAtMs) {
      merged.push({ ...interval });
    } else {
      previous.finishedAtMs = Math.max(previous.finishedAtMs, interval.finishedAtMs);
    }
  }

  return merged.reduce((total, interval) => total + interval.finishedAtMs - interval.startedAtMs, 0);
}

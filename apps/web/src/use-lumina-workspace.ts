import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { imageAttachmentFileName } from "./attachment-file-name";
import { createClientId } from "./client-id";
import type {
  AuthSession,
  AttachmentSummary,
  ChatMessage,
  ConversationListItem,
  CurrentSettings,
  ModelSummary,
  PromptReference,
  ProjectSummary,
  ProviderSummary,
  RunActionRequest,
  RunEvent,
  RunMutationResponse,
  RunSnapshot,
  RunStatus,
  SidebarRunStatus,
  ToolExecution,
  TurnSet,
  UserInputAnswer,
} from "./api-types";
import { isTerminalRunEvent, isTerminalRunStatus } from "./run-status";

export type StreamState = "idle" | "connecting" | "connected" | "reconnecting";
export type RunControlAction = "pause" | "resume" | "cancel" | "retry_step" | "approve" | "reject";
export type PendingCommandAction = "steer_queued" | "cancel_command";

export interface ConversationRuntime {
  turnSets: TurnSet[];
  snapshots: Record<string, RunSnapshot>;
  lastSequences: Record<string, number>;
  loaded: boolean;
  loading: boolean;
  error: string | null;
  streamState: StreamState;
}

const UNTITLED_CONVERSATION_TITLES = new Set(["제목 없음", "새 작업"]);
const PROVISIONAL_TITLE_MAX_LENGTH = 60;
const ACTIVE_RUN_RECONCILIATION_INTERVAL_MS = 15_000;

function isUntouchedConversation(conversation: ConversationListItem) {
  return UNTITLED_CONVERSATION_TITLES.has(conversation.title)
    && conversation.activeRunId === null
    && conversation.lastRunStatus === null
    && conversation.lastSequence === 0;
}

function provisionalConversationTitle(messageText: string) {
  const normalized = messageText.trim().replace(/\s+/g, " ");
  if (normalized.length <= PROVISIONAL_TITLE_MAX_LENGTH) return normalized;
  return `${normalized.slice(0, PROVISIONAL_TITLE_MAX_LENGTH - 1).trimEnd()}…`;
}

function emptyRuntime(): ConversationRuntime {
  return {
    turnSets: [],
    snapshots: {},
    lastSequences: {},
    loaded: false,
    loading: false,
    error: null,
    streamState: "idle",
  };
}

function sidebarStatus(status: RunStatus): SidebarRunStatus {
  if (status === "queued") return "queued";
  if (status === "awaiting_approval") return "approval";
  if (status === "awaiting_input") return "input";
  if (status === "completed") return "completed";
  if (status === "failed" || status === "limit_reached" || status === "interrupted") return "failed";
  if (status === "cancelled") return "cancelled";
  return "running";
}

function upsertById<T extends { id: string }>(items: T[], value: T) {
  const index = items.findIndex((item) => item.id === value.id);
  if (index < 0) return [...items, value];
  const next = [...items];
  next[index] = value;
  return next;
}

function upsertTool(items: ToolExecution[], execution: ToolExecution) {
  const index = items.findIndex((item) => item.id === execution.id || item.callId === execution.callId);
  if (index < 0) return [...items, execution];
  const next = [...items];
  next[index] = execution;
  return next;
}

function ensureTurnSet(runtime: ConversationRuntime, runId: string, message?: ChatMessage | null) {
  const existing = runtime.turnSets.find((turnSet) => turnSet.runId === runId);
  if (existing) {
    if (!message || existing.messages.some((item) => item.id === message.id)) return runtime.turnSets;
    return runtime.turnSets.map((turnSet) =>
      turnSet.runId === runId ? { ...turnSet, messages: [...turnSet.messages, message] } : turnSet,
    );
  }
  return [
    ...runtime.turnSets,
    {
      id: runId,
      runId,
      messages: message ? [message] : [],
      plan: null,
      activities: [],
      toolExecutions: [],
      artifacts: [],
      createdAt: message?.createdAt ?? new Date().toISOString(),
      completedAt: null,
    },
  ];
}

function apiMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "요청을 처리하지 못했습니다.";
}

export function useLuminaWorkspace() {
  const [authSession, setAuthSession] = useState<AuthSession | null | undefined>(undefined);
  const [bootError, setBootError] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProjectId, setActiveProjectIdState] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationListItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [settings, setSettings] = useState<CurrentSettings | null>(null);
  const [providers, setProviders] = useState<ProviderSummary[]>([]);
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [providerModels, setProviderModels] = useState<Record<string, ModelSummary[]>>({});
  const [runtimes, setRuntimes] = useState<Record<string, ConversationRuntime>>({});
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [sending, setSending] = useState(false);
  const [runActionBusy, setRunActionBusy] = useState(false);
  const [composerAttachments, setComposerAttachments] = useState<AttachmentSummary[]>([]);
  const [uploadingAttachments, setUploadingAttachments] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const clearNotice = useCallback(() => setNotice(null), []);

  const activeProjectIdRef = useRef<string | null>(null);
  const conversationsRef = useRef<ConversationListItem[]>([]);
  const settingsRef = useRef<CurrentSettings | null>(null);
  const runtimesRef = useRef<Record<string, ConversationRuntime>>({});
  const composerAttachmentsRef = useRef<AttachmentSummary[]>([]);
  const creatingConversationRef = useRef(false);
  const streamsRef = useRef(new Map<string, () => void>());
  const hydratingRef = useRef(new Set<string>());
  const reconcilingRunIdsRef = useRef(new Set<string>());
  const reconciliationTimersRef = useRef(new Set<number>());

  useEffect(() => {
    activeProjectIdRef.current = activeProjectId;
  }, [activeProjectId]);
  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);
  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);
  useEffect(() => {
    runtimesRef.current = runtimes;
  }, [runtimes]);
  useEffect(() => {
    composerAttachmentsRef.current = composerAttachments;
  }, [composerAttachments]);

  const closeStreams = useCallback(() => {
    streamsRef.current.forEach((close) => close());
    streamsRef.current.clear();
    hydratingRef.current.clear();
    reconcilingRunIdsRef.current.clear();
    reconciliationTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    reconciliationTimersRef.current.clear();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    api.auth.getSession(controller.signal)
      .then((session) => {
        setAuthSession(session);
        setBootError(null);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setAuthSession(null);
        if (!(error instanceof ApiError && error.status === 401)) {
          setBootError("서버에 연결하지 못했습니다. Backend 실행 상태를 확인해 주세요.");
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => () => closeStreams(), [closeStreams]);

  const refreshConversations = useCallback(async (projectId?: string | null) => {
    const targetProjectId = projectId ?? activeProjectIdRef.current;
    if (!targetProjectId) return [];
    const page = await api.conversations.list({ projectId: targetProjectId, limit: 60 });
    setConversations(page.items);
    setActiveConversationId((current) =>
      current && page.items.some((item) => item.id === current) ? current : (page.items[0]?.id ?? null),
    );
    return page.items;
  }, []);

  const loadConversation = useCallback(async (conversationId: string, force = false) => {
    const cached = runtimesRef.current[conversationId];
    if (!force && (cached?.loaded || cached?.loading)) return;
    setRuntimes((current) => ({
      ...current,
      [conversationId]: { ...(current[conversationId] ?? emptyRuntime()), loading: true, error: null },
    }));
    try {
      const page = await api.conversations.getTurnSets(conversationId, undefined, 3);
      setRuntimes((current) => ({
        ...current,
        [conversationId]: {
          ...(current[conversationId] ?? emptyRuntime()),
          turnSets: page.turnSets,
          loaded: true,
          loading: false,
          error: null,
        },
      }));
      const runIds = page.turnSets.flatMap((turnSet) => turnSet.runId ? [turnSet.runId] : []);
      if (runIds.length > 0) {
        const snapshotResults = await Promise.allSettled(runIds.map((runId) => api.runs.getSnapshot(runId)));
        const restoredSnapshots = snapshotResults.flatMap((result) => result.status === "fulfilled" ? [result.value] : []);
        setRuntimes((current) => {
          const runtime = current[conversationId] ?? emptyRuntime();
          const snapshots = { ...runtime.snapshots };
          const lastSequences = { ...runtime.lastSequences };
          restoredSnapshots.forEach((snapshot) => {
            const existing = snapshots[snapshot.runId];
            if (!existing || snapshot.lastSequence >= existing.lastSequence) snapshots[snapshot.runId] = snapshot;
            lastSequences[snapshot.runId] = Math.max(lastSequences[snapshot.runId] ?? 0, snapshot.lastSequence);
          });
          return { ...current, [conversationId]: { ...runtime, snapshots, lastSequences } };
        });
      }
    } catch (error) {
      setRuntimes((current) => ({
        ...current,
        [conversationId]: {
          ...(current[conversationId] ?? emptyRuntime()),
          loading: false,
          error: apiMessage(error),
        },
      }));
    }
  }, []);

  const mergeRunMutation = useCallback((mutation: RunMutationResponse) => {
    const { run, message } = mutation;
    setRuntimes((current) => {
      const runtime = current[run.conversationId] ?? emptyRuntime();
      const turnSets = ensureTurnSet(runtime, run.runId, message).map((turnSet) => ({
        ...turnSet,
        messages: turnSet.messages.filter((item) => !(
          item.status === "pending" && item.metadata?.command_type === "queue_next"
        )),
      }));
      return {
        ...current,
        [run.conversationId]: {
          ...runtime,
          turnSets: turnSets.map((turnSet) =>
            turnSet.runId === run.runId
              ? {
                  ...turnSet,
                  plan: run.plan,
                  toolExecutions: run.toolExecutions,
                  artifacts: run.artifacts,
                  completedAt: run.finishedAt,
                }
              : turnSet,
          ),
          snapshots: { ...runtime.snapshots, [run.runId]: run },
          lastSequences: { ...runtime.lastSequences, [run.runId]: run.lastSequence },
          loaded: true,
        },
      };
    });
    setConversations((items) => items.map((item) =>
      item.id === run.conversationId
        ? {
            ...item,
            title: run.conversationTitle ?? item.title,
            revision: run.conversationRevision === null ? item.revision : String(run.conversationRevision),
            activeRunId: isTerminalRunStatus(run.status) ? null : run.runId,
            lastRunStatus: sidebarStatus(run.status),
            lastSequence: run.lastSequence,
            updatedAt: new Date().toISOString(),
          }
        : item,
    ));
  }, []);

  const applyRunEvent = useCallback((event: RunEvent) => {
    setRuntimes((current) => {
      const runtime = current[event.conversationId] ?? emptyRuntime();
      const previousSequence = runtime.lastSequences[event.runId] ?? 0;
      if (event.sequence <= previousSequence) return current;
      const snapshot = runtime.snapshots[event.runId];
      if (!snapshot) return current;

      let nextSnapshot: RunSnapshot = { ...snapshot, lastSequence: event.sequence };
      let turnSets = ensureTurnSet(runtime, event.runId);

      if (event.type === "run_started" || event.type === "run_status_changed") {
        nextSnapshot.status = event.payload.status;
      } else if (event.type === "assistant_text_delta") {
        const previousDraft = nextSnapshot.assistantDraft;
        nextSnapshot.assistantDraft = {
          messageId: event.payload.messageId,
          text: `${previousDraft?.text ?? ""}${event.payload.delta}`,
        };
      } else if (event.type === "progress_summary") {
        nextSnapshot.activities = [
          ...nextSnapshot.activities,
          {
            id: event.payload.id,
            type: "progress_summary",
            sequence: event.sequence,
            text: event.payload.text,
            phase: event.payload.phase,
            createdAt: event.createdAt,
          },
        ];
      } else if (event.type === "output_intent_classified") {
        nextSnapshot.outputIntent = event.payload;
        if (event.payload.fileCreationRequested === false) {
          nextSnapshot.artifactProgress = null;
          nextSnapshot.artifactUsage = null;
        }
      } else if (event.type === "skill_selected") {
        nextSnapshot.activities = [
          ...nextSnapshot.activities.filter((activity) => activity.id !== event.payload.activity.id),
          { ...event.payload.activity, sequence: event.sequence },
        ];
      } else if (event.type === "assistant_turn_completed") {
        turnSets = ensureTurnSet({ ...runtime, turnSets }, event.runId, event.payload.message);
        nextSnapshot.assistantDraft = null;
      } else if (event.type === "artifact_progress") {
        nextSnapshot.artifactProgress = event.payload;
        nextSnapshot.artifactUsage = event.payload;
      } else if (event.type === "work_plan_updated") {
        nextSnapshot.workPlan = event.payload.steps;
      } else if (event.type === "plan_step_changed" && nextSnapshot.plan) {
        nextSnapshot.plan = {
          ...nextSnapshot.plan,
          steps: upsertById(nextSnapshot.plan.steps, event.payload.step),
        };
      } else if (event.type === "tool_started" || event.type === "tool_progress" || event.type === "tool_completed") {
        nextSnapshot.toolExecutions = upsertTool(nextSnapshot.toolExecutions, event.payload.execution);
        const existingActivity = nextSnapshot.activities.findIndex(
          (activity) => activity.type === "tool" && (
            activity.execution.id === event.payload.execution.id
            || activity.execution.callId === event.payload.execution.callId
          ),
        );
        if (existingActivity >= 0) {
          nextSnapshot.activities = nextSnapshot.activities.map((activity, index) =>
            index === existingActivity && activity.type === "tool"
              ? { ...activity, execution: event.payload.execution }
              : activity,
          );
        } else {
          nextSnapshot.activities = [
            ...nextSnapshot.activities,
            {
              id: `tool:${event.payload.execution.id}`,
              type: "tool",
              sequence: event.sequence,
              execution: event.payload.execution,
            },
          ];
        }
      } else if (event.type === "approval_requested") {
        nextSnapshot.pendingApprovals = upsertById(nextSnapshot.pendingApprovals, event.payload.approval);
      } else if (event.type === "approval_resolved") {
        nextSnapshot.pendingApprovals = nextSnapshot.pendingApprovals.filter((item) => item.id !== event.payload.approval.id);
      } else if (event.type === "input_requested" || event.type === "input_submitted") {
        const request = event.payload.request;
        nextSnapshot.inputRequests = upsertById(nextSnapshot.inputRequests ?? [], request);
        const existingActivity = nextSnapshot.activities.findIndex(
          (activity) => activity.type === "input_request" && activity.request.id === request.id,
        );
        if (existingActivity >= 0) {
          nextSnapshot.activities = nextSnapshot.activities.map((activity, index) =>
            index === existingActivity && activity.type === "input_request"
              ? { ...activity, request }
              : activity,
          );
        } else {
          nextSnapshot.activities = [
            ...nextSnapshot.activities,
            {
              id: `input:${request.id}`,
              type: "input_request",
              sequence: event.sequence,
              request,
            },
          ];
        }
      } else if (event.type === "artifact_created") {
        nextSnapshot.artifacts = upsertById(nextSnapshot.artifacts, event.payload.artifact);
        nextSnapshot.artifactProgress = null;
      } else if (isTerminalRunEvent(event)) {
        nextSnapshot.status = event.payload.status;
        nextSnapshot.finishedAt = event.payload.finishedAt;
        nextSnapshot.artifactProgress = null;
      } else if (
        event.type === "steer_received"
        || event.type === "steer_waiting_safe_boundary"
        || event.type === "steer_applied"
        || event.type === "steer_cancelled"
        || event.type === "queued_message_added"
        || event.type === "queued_message_cancelled"
        || event.type === "queued_message_promoted_to_run"
      ) {
        const command = event.payload.command;
        if (command) {
          nextSnapshot.pendingCommands = command.status === "applied" || command.status === "cancelled" || command.status === "failed" || command.status === "promoted"
            ? nextSnapshot.pendingCommands.filter((item) => item.id !== command.id)
            : upsertById(nextSnapshot.pendingCommands, command);
        }
      }

      turnSets = turnSets.map((turnSet) =>
        turnSet.runId === event.runId
          ? {
              ...turnSet,
              plan: nextSnapshot.plan,
              toolExecutions: nextSnapshot.toolExecutions,
              artifacts: nextSnapshot.artifacts,
              completedAt: nextSnapshot.finishedAt,
            }
          : turnSet,
      );
      return {
        ...current,
        [event.conversationId]: {
          ...runtime,
          turnSets,
          snapshots: { ...runtime.snapshots, [event.runId]: nextSnapshot },
          lastSequences: { ...runtime.lastSequences, [event.runId]: event.sequence },
        },
      };
    });

    const status = event.type === "run_started" || event.type === "run_status_changed"
      ? event.payload.status
      : isTerminalRunEvent(event)
        ? event.payload.status
        : null;
    const titleUpdate = event.type === "conversation_title_updated" ? event.payload : null;
    setConversations((items) => items.map((item) =>
      item.id === event.conversationId
        ? {
            ...item,
            title: titleUpdate?.title ?? item.title,
            revision: titleUpdate ? String(titleUpdate.revision) : item.revision,
            activeRunId: isTerminalRunStatus(status) ? null : (item.activeRunId ?? event.runId),
            lastRunStatus: status ? sidebarStatus(status) : item.lastRunStatus,
            lastSequence: Math.max(item.lastSequence, event.sequence),
            updatedAt: new Date().toISOString(),
          }
        : item,
    ));

    const terminal = isTerminalRunEvent(event);
    if (terminal) {
      void loadConversation(event.conversationId, true);
      const retryDelays = [40, 220, 650];
      const reconcile = (attempt: number) => {
        const timer = window.setTimeout(() => {
          reconciliationTimersRef.current.delete(timer);
          void refreshConversations()
            .then((items) => {
              const conversation = items.find((item) => item.id === event.conversationId);
              if (conversation?.activeRunId && conversation.activeRunId !== event.runId) {
                void loadConversation(event.conversationId, true);
                return;
              }
              if (attempt + 1 < retryDelays.length) reconcile(attempt + 1);
            })
            .catch((error) => setNotice(apiMessage(error)));
        }, retryDelays[attempt]);
        reconciliationTimersRef.current.add(timer);
      };
      reconcile(0);
      const closeTimer = window.setTimeout(() => {
        reconciliationTimersRef.current.delete(closeTimer);
        const latestSnapshot = runtimesRef.current[event.conversationId]?.snapshots[event.runId];
        if (latestSnapshot && !isTerminalRunStatus(latestSnapshot.status)) return;
        streamsRef.current.get(event.runId)?.();
        streamsRef.current.delete(event.runId);
        setRuntimes((current) => {
          const runtime = current[event.conversationId] ?? emptyRuntime();
          const hasAnotherActiveRun = Object.values(runtime.snapshots).some(
            (snapshot) => snapshot.runId !== event.runId && !isTerminalRunStatus(snapshot.status),
          );
          return {
            ...current,
            [event.conversationId]: {
              ...runtime,
              streamState: hasAnotherActiveRun ? runtime.streamState : "idle",
            },
          };
        });
      }, 1200);
      reconciliationTimersRef.current.add(closeTimer);
    } else if (event.type === "queued_message_promoted_to_run") {
      const timer = window.setTimeout(() => {
        reconciliationTimersRef.current.delete(timer);
        void refreshConversations().catch((error) => setNotice(apiMessage(error)));
      }, 0);
      reconciliationTimersRef.current.add(timer);
    }
  }, [loadConversation, refreshConversations]);

  const mergeAuthoritativeRunSnapshot = useCallback((snapshot: RunSnapshot) => {
    const terminal = isTerminalRunStatus(snapshot.status);
    setRuntimes((current) => {
      const runtime = current[snapshot.conversationId] ?? emptyRuntime();
      const existing = runtime.snapshots[snapshot.runId];
      if (existing && !terminal && existing.lastSequence > snapshot.lastSequence) return current;
      const snapshots = { ...runtime.snapshots, [snapshot.runId]: snapshot };
      const turnSets = ensureTurnSet(runtime, snapshot.runId).map((turnSet) =>
        turnSet.runId === snapshot.runId
          ? {
              ...turnSet,
              plan: snapshot.plan,
              toolExecutions: snapshot.toolExecutions,
              artifacts: snapshot.artifacts,
              completedAt: snapshot.finishedAt,
            }
          : turnSet,
      );
      const hasAnotherActiveRun = Object.values(snapshots).some(
        (candidate) => candidate.runId !== snapshot.runId && !isTerminalRunStatus(candidate.status),
      );
      return {
        ...current,
        [snapshot.conversationId]: {
          ...runtime,
          turnSets,
          snapshots,
          lastSequences: {
            ...runtime.lastSequences,
            [snapshot.runId]: Math.max(runtime.lastSequences[snapshot.runId] ?? 0, snapshot.lastSequence),
          },
          streamState: terminal && !hasAnotherActiveRun ? "idle" : runtime.streamState,
        },
      };
    });
    setConversations((items) => items.map((item) =>
      item.id === snapshot.conversationId
        ? {
            ...item,
            activeRunId: terminal
              ? (item.activeRunId === snapshot.runId ? null : item.activeRunId)
              : (item.activeRunId ?? snapshot.runId),
            lastRunStatus: item.activeRunId && item.activeRunId !== snapshot.runId
              ? item.lastRunStatus
              : sidebarStatus(snapshot.status),
            lastSequence: Math.max(item.lastSequence, snapshot.lastSequence),
          }
        : item,
    ));
    if (terminal) {
      streamsRef.current.get(snapshot.runId)?.();
      streamsRef.current.delete(snapshot.runId);
    }
  }, []);

  const reconcileRunSnapshot = useCallback(async (runId: string) => {
    if (reconcilingRunIdsRef.current.has(runId)) return;
    reconcilingRunIdsRef.current.add(runId);
    try {
      mergeAuthoritativeRunSnapshot(await api.runs.getSnapshot(runId));
    } catch {
      // The SSE reconnect path keeps retrying. A later interval or focus event
      // will reconcile the authoritative state when the Backend is reachable.
    } finally {
      reconcilingRunIdsRef.current.delete(runId);
    }
  }, [mergeAuthoritativeRunSnapshot]);

  const openSnapshotStream = useCallback((snapshot: RunSnapshot) => {
    if (isTerminalRunStatus(snapshot.status) || streamsRef.current.has(snapshot.runId)) return;
    setRuntimes((current) => ({
      ...current,
      [snapshot.conversationId]: {
        ...(current[snapshot.conversationId] ?? emptyRuntime()),
        streamState: "connecting",
      },
    }));
    const close = api.runs.openStream(snapshot.runId, snapshot.lastSequence, {
      onOpen: () => setRuntimes((current) => ({
        ...current,
        [snapshot.conversationId]: {
          ...(current[snapshot.conversationId] ?? emptyRuntime()),
          streamState: "connected",
        },
      })),
      onEvent: applyRunEvent,
      onError: () => {
        setRuntimes((current) => ({
          ...current,
          [snapshot.conversationId]: {
            ...(current[snapshot.conversationId] ?? emptyRuntime()),
            streamState: "reconnecting",
          },
        }));
        void reconcileRunSnapshot(snapshot.runId);
      },
    });
    streamsRef.current.set(snapshot.runId, close);
  }, [applyRunEvent, reconcileRunSnapshot]);

  const hydrateRun = useCallback(async (runId: string, conversationId: string) => {
    if (streamsRef.current.has(runId) || hydratingRef.current.has(runId)) return;
    hydratingRef.current.add(runId);
    try {
      const snapshot = await api.runs.getSnapshot(runId);
      setRuntimes((current) => {
        const runtime = current[conversationId] ?? emptyRuntime();
        return {
          ...current,
          [conversationId]: {
            ...runtime,
            turnSets: ensureTurnSet(runtime, runId).map((turnSet) =>
              turnSet.runId === runId
                ? { ...turnSet, plan: snapshot.plan, toolExecutions: snapshot.toolExecutions, artifacts: snapshot.artifacts }
                : turnSet,
            ),
            snapshots: { ...runtime.snapshots, [runId]: snapshot },
            lastSequences: { ...runtime.lastSequences, [runId]: snapshot.lastSequence },
          },
        };
      });
      openSnapshotStream(snapshot);
    } catch (error) {
      setNotice(apiMessage(error));
    } finally {
      hydratingRef.current.delete(runId);
    }
  }, [openSnapshotStream]);

  useEffect(() => {
    conversations.forEach((conversation) => {
      if (conversation.activeRunId) void hydrateRun(conversation.activeRunId, conversation.id);
    });
  }, [conversations, hydrateRun]);

  useEffect(() => {
    if (!authSession) return;
    const reconcileActiveRuns = () => {
      const runIds = new Set<string>();
      Object.values(runtimesRef.current).forEach((runtime) => {
        Object.values(runtime.snapshots).forEach((snapshot) => {
          if (!isTerminalRunStatus(snapshot.status)) runIds.add(snapshot.runId);
        });
      });
      conversationsRef.current.forEach((conversation) => {
        if (conversation.activeRunId) runIds.add(conversation.activeRunId);
      });
      runIds.forEach((runId) => void reconcileRunSnapshot(runId));
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") reconcileActiveRuns();
    };
    const interval = window.setInterval(reconcileActiveRuns, ACTIVE_RUN_RECONCILIATION_INTERVAL_MS);
    window.addEventListener("focus", reconcileActiveRuns);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", reconcileActiveRuns);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [authSession, reconcileRunSnapshot]);

  useEffect(() => {
    if (!activeConversationId) return;
    void loadConversation(activeConversationId);
  }, [activeConversationId, loadConversation]);

  useEffect(() => {
    if (!authSession) return;
    let cancelled = false;
    setLoadingWorkspace(true);
    api.projects.list()
      .then((items) => {
        if (cancelled) return;
        setProjects(items);
        const preferred = items.find((item) => item.isDefault) ?? items[0];
        setActiveProjectIdState(preferred?.id ?? null);
      })
      .catch((error) => {
        if (!cancelled) setNotice(apiMessage(error));
      })
      .finally(() => {
        if (!cancelled) setLoadingWorkspace(false);
      });
    return () => {
      cancelled = true;
    };
  }, [authSession]);

  useEffect(() => {
    if (!authSession || !activeProjectId) return;
    const controller = new AbortController();
    setLoadingWorkspace(true);
    Promise.all([
      api.settings.getCurrent(activeProjectId, controller.signal),
      api.providers.list(activeProjectId, controller.signal),
      api.conversations.list({ projectId: activeProjectId, limit: 60 }, controller.signal),
    ])
      .then(([currentSettings, providerItems, conversationPage]) => {
        setSettings(currentSettings);
        setProviders(providerItems);
        setConversations(conversationPage.items);
        setActiveConversationId((current) =>
          current && conversationPage.items.some((item) => item.id === current)
            ? current
            : (conversationPage.items[0]?.id ?? null),
        );
      })
      .catch((error) => {
        if (!controller.signal.aborted) setNotice(apiMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingWorkspace(false);
      });
    return () => controller.abort();
  }, [activeProjectId, authSession]);

  useEffect(() => {
    const providerId = settings?.execution.providerId;
    if (!providerId) return;
    const controller = new AbortController();
    api.providers.listModels(providerId, activeProjectId ?? undefined, controller.signal)
      .then(setModels)
      .catch((error) => {
        if (!controller.signal.aborted) setNotice(apiMessage(error));
      });
    return () => controller.abort();
  }, [activeProjectId, settings?.execution.providerId]);

  useEffect(() => {
    if (!activeProjectId || providers.length === 0) return;
    const controller = new AbortController();
    const providerIds = providers
      .filter((provider) => provider.id !== "mock")
      .map((provider) => provider.id);
    Promise.all(
      providerIds.map(async (providerId) => [
        providerId,
        await api.providers.listModels(providerId, activeProjectId, controller.signal),
      ] as const),
    )
      .then((entries) => setProviderModels(Object.fromEntries(entries)))
      .catch((error) => {
        if (!controller.signal.aborted) setNotice(apiMessage(error));
      });
    return () => controller.abort();
  }, [activeProjectId, providers]);

  const refreshProviderCatalog = useCallback(async () => {
    const projectId = activeProjectIdRef.current;
    if (!projectId) return;
    try {
      const providerItems = await api.providers.list(projectId);
      const entries = await Promise.all(
        providerItems
          .filter((provider) => provider.id !== "mock")
          .map(async (provider) => [
            provider.id,
            await api.providers.listModels(provider.id, projectId),
          ] as const),
      );
      const nextProviderModels = Object.fromEntries(entries);
      setProviders(providerItems);
      setProviderModels(nextProviderModels);
      const selectedProviderId = settingsRef.current?.execution.providerId;
      if (selectedProviderId) setModels(nextProviderModels[selectedProviderId] ?? []);
    } catch (error) {
      setNotice(apiMessage(error));
    }
  }, []);

  const persistSettings = useCallback(async (patch:
    Pick<CurrentSettings, "theme">
    | Pick<CurrentSettings, "outputMode">
    | Pick<CurrentSettings, "clarificationMode">
    | { execution: CurrentSettings["execution"] }
    | { modelCandidates: CurrentSettings["modelCandidates"] }
  ) => {
    const current = settingsRef.current;
    if (!current) return null;
    try {
      const next = await api.settings.updateCurrent(activeProjectIdRef.current ?? undefined, {
        ...patch,
        expectedRevision: current.revision,
      });
      setSettings(next);
      return next;
    } catch (error) {
      if (error instanceof ApiError && error.code === "settings_revision_conflict") {
        const latest = await api.settings.getCurrent(activeProjectIdRef.current ?? undefined);
        setSettings(latest);
      }
      setNotice(apiMessage(error));
      return null;
    }
  }, []);

  const selectProvider = useCallback(async (providerId: string) => {
    try {
      const providerModels = await api.providers.listModels(providerId, activeProjectIdRef.current ?? undefined);
      setModels(providerModels);
      const model = providerModels.find((item) => item.isDefault) ?? providerModels[0];
      if (!model) {
        setNotice("선택한 Provider에 사용할 수 있는 모델이 없습니다.");
        return;
      }
      const efforts = model.capabilities.effortOptions;
      const effortId = efforts.find((item) => item.id === "auto")?.id ?? efforts[0]?.id ?? null;
      await persistSettings({ execution: { providerId, modelKey: model.modelKey, effortId } });
    } catch (error) {
      setNotice(apiMessage(error));
    }
  }, [persistSettings]);

  const selectModel = useCallback(async (modelKey: string) => {
    const current = settingsRef.current;
    if (!current) return;
    const model = models.find((item) => item.modelKey === modelKey);
    if (!model) return;
    const effortIds = model.capabilities.effortOptions.map((item) => item.id);
    const effortId = current.execution.effortId && effortIds.includes(current.execution.effortId)
      ? current.execution.effortId
      : (effortIds.find((item) => item === "auto") ?? effortIds[0] ?? null);
    await persistSettings({ execution: { ...current.execution, modelKey, effortId } });
  }, [models, persistSettings]);

  const selectModelCandidate = useCallback(async (providerId: string, modelKey: string) => {
    const current = settingsRef.current;
    if (!current) return;
    const providerModel = providerModels[providerId]?.find((item) => item.modelKey === modelKey)
      ?? (providerId === current.execution.providerId
        ? models.find((item) => item.modelKey === modelKey)
        : undefined);
    if (!providerModel) return;
    const effortIds = providerModel.capabilities.effortOptions.map((item) => item.id);
    const effortId = current.execution.effortId && effortIds.includes(current.execution.effortId)
      ? current.execution.effortId
      : (effortIds.find((item) => item === "auto") ?? effortIds[0] ?? null);
    setModels(providerModels[providerId] ?? models);
    await persistSettings({ execution: { providerId, modelKey, effortId } });
  }, [models, persistSettings, providerModels]);

  const toggleModelCandidate = useCallback(async (providerId: string, modelKey: string) => {
    const current = settingsRef.current;
    if (!current) return;
    const candidates = new Set(current.modelCandidates[providerId] ?? []);
    if (candidates.has(modelKey)) candidates.delete(modelKey);
    else candidates.add(modelKey);
    const modelCandidates = { ...current.modelCandidates };
    if (candidates.size > 0) modelCandidates[providerId] = [...candidates];
    else delete modelCandidates[providerId];
    await persistSettings({ modelCandidates });
  }, [persistSettings]);

  const setModelCandidates = useCallback(async (providerId: string, modelKeys: string[]) => {
    const current = settingsRef.current;
    if (!current) return;
    const modelCandidates = { ...current.modelCandidates };
    if (modelKeys.length > 0) modelCandidates[providerId] = modelKeys;
    else delete modelCandidates[providerId];
    await persistSettings({ modelCandidates });
  }, [persistSettings]);

  const selectEffort = useCallback(async (effortId: string | null) => {
    const current = settingsRef.current;
    if (!current) return;
    await persistSettings({ execution: { ...current.execution, effortId } });
  }, [persistSettings]);

  const selectOutputMode = useCallback(async (outputMode: CurrentSettings["outputMode"]) => {
    await persistSettings({ outputMode });
  }, [persistSettings]);

  const selectClarificationMode = useCallback(async (
    clarificationMode: CurrentSettings["clarificationMode"],
  ) => persistSettings({ clarificationMode }), [persistSettings]);

  const toggleTheme = useCallback(async () => {
    const current = settingsRef.current;
    if (!current) return;
    await persistSettings({ theme: current.theme === "dark" ? "light" : "dark" });
  }, [persistSettings]);

  const setActiveProjectId = useCallback((projectId: string) => {
    setActiveProjectIdState(projectId);
    setActiveConversationId(null);
  }, []);

  const refreshProjects = useCallback(async () => {
    try {
      const items = await api.projects.list();
      setProjects(items);
      return items;
    } catch (error) {
      setNotice(apiMessage(error));
      return null;
    }
  }, []);

  const createProject = useCallback(async (name: string, description = "") => {
    try {
      const project = await api.projects.create({ name, description });
      setProjects((items) => [...items, project]);
      setActiveProjectId(project.id);
      return project;
    } catch (error) {
      setNotice(apiMessage(error));
      return null;
    }
  }, [setActiveProjectId]);

  const updateProjectDetails = useCallback(async (
    projectId: string,
    changes: { name?: string; description?: string; concept?: string },
  ) => {
    try {
      const project = await api.projects.update(projectId, changes);
      setProjects((items) => items.map((item) => item.id === project.id ? project : item));
      return project;
    } catch (error) {
      setNotice(apiMessage(error));
      return null;
    }
  }, []);

  const archiveProject = useCallback(async (projectId: string) => {
    try {
      await api.projects.archive(projectId);
      const remaining = projects.filter((item) => item.id !== projectId);
      const next = remaining.find((item) => item.isDefault) ?? remaining[0] ?? null;
      setProjects(remaining);
      setActiveProjectIdState(next?.id ?? null);
      setActiveConversationId(null);
      return true;
    } catch (error) {
      setNotice(apiMessage(error));
      return false;
    }
  }, [projects]);

  const createConversation = useCallback(async (title = "제목 없음") => {
    const projectId = activeProjectIdRef.current;
    if (!projectId) return null;
    const mostRecent = conversationsRef.current.find((conversation) => conversation.projectId === projectId);
    if (mostRecent && isUntouchedConversation(mostRecent)) {
      setActiveConversationId(mostRecent.id);
      return mostRecent;
    }
    if (creatingConversationRef.current) return null;
    creatingConversationRef.current = true;
    try {
      const conversation = await api.conversations.create({ projectId, title });
      const nextConversations = [conversation, ...conversationsRef.current];
      conversationsRef.current = nextConversations;
      setConversations(nextConversations);
      setActiveConversationId(conversation.id);
      setRuntimes((current) => ({ ...current, [conversation.id]: { ...emptyRuntime(), loaded: true } }));
      return conversation;
    } catch (error) {
      setNotice(apiMessage(error));
      return null;
    } finally {
      creatingConversationRef.current = false;
    }
  }, []);

  const startNewConversation = useCallback(() => {
    setActiveConversationId(null);
  }, []);

  const openConversation = useCallback((conversation: ConversationListItem) => {
    if (conversation.projectId !== activeProjectIdRef.current) {
      setActiveProjectIdState(conversation.projectId);
    }
    setConversations((items) => [conversation, ...items.filter((item) => item.id !== conversation.id)]);
    setActiveConversationId(conversation.id);
  }, []);

  const renameConversation = useCallback(async (conversationId: string, title: string) => {
    const conversation = conversationsRef.current.find((item) => item.id === conversationId);
    if (!conversation) return null;
    try {
      const updated = await api.conversations.update(conversationId, {
        title,
        expectedRevision: conversation.revision,
      });
      setConversations((items) => items.map((item) => item.id === updated.id ? updated : item));
      return updated;
    } catch (error) {
      setNotice(apiMessage(error));
      await refreshConversations();
      return null;
    }
  }, [refreshConversations]);

  const toggleFavoriteConversation = useCallback(async (conversationId: string) => {
    const conversation = conversationsRef.current.find((item) => item.id === conversationId);
    if (!conversation) return null;
    try {
      const updated = await api.conversations.update(conversationId, {
        isFavorite: !conversation.isFavorite,
        expectedRevision: conversation.revision,
      });
      await refreshConversations();
      return updated;
    } catch (error) {
      setNotice(apiMessage(error));
      await refreshConversations();
      return null;
    }
  }, [refreshConversations]);

  const toggleLikedConversation = useCallback(async (conversationId: string) => {
    const conversation = conversationsRef.current.find((item) => item.id === conversationId);
    if (!conversation) return null;
    try {
      const updated = await api.conversations.update(conversationId, {
        isLiked: !conversation.isLiked,
        expectedRevision: conversation.revision,
      });
      setConversations((items) => items.map((item) => item.id === updated.id ? updated : item));
      return updated;
    } catch (error) {
      setNotice(apiMessage(error));
      await refreshConversations();
      return null;
    }
  }, [refreshConversations]);

  const moveConversation = useCallback(async (conversationId: string, projectId: string) => {
    try {
      await api.conversations.move(conversationId, projectId);
      const remaining = conversationsRef.current.filter((item) => item.id !== conversationId);
      setConversations(remaining);
      setActiveConversationId((current) => current === conversationId ? (remaining[0]?.id ?? null) : current);
      return true;
    } catch (error) {
      setNotice(apiMessage(error));
      return false;
    }
  }, []);

  const deleteConversation = useCallback(async (conversationId: string) => {
    try {
      await api.conversations.delete(conversationId);
      const remaining = conversationsRef.current.filter((item) => item.id !== conversationId);
      setConversations(remaining);
      setActiveConversationId((current) => current === conversationId ? (remaining[0]?.id ?? null) : current);
      return true;
    } catch (error) {
      setNotice(apiMessage(error));
      return false;
    }
  }, []);

  const moveConversations = useCallback(async (conversationIds: string[], projectId: string) => {
    const succeeded: string[] = [];
    for (const conversationId of conversationIds) {
      try {
        await api.conversations.move(conversationId, projectId);
        succeeded.push(conversationId);
      } catch {
        // Continue so one protected or running session does not block the rest.
      }
    }
    await refreshConversations();
    const failedCount = conversationIds.length - succeeded.length;
    if (failedCount) setNotice(`${succeeded.length}개 세션을 이동했고 ${failedCount}개는 이동하지 못했습니다.`);
    return succeeded;
  }, [refreshConversations]);

  const deleteConversations = useCallback(async (conversationIds: string[]) => {
    const succeeded: string[] = [];
    for (const conversationId of conversationIds) {
      try {
        await api.conversations.delete(conversationId);
        succeeded.push(conversationId);
      } catch {
        // Continue so one protected or running session does not block the rest.
      }
    }
    await refreshConversations();
    const failedCount = conversationIds.length - succeeded.length;
    if (failedCount) setNotice(`${succeeded.length}개 세션을 삭제했고 ${failedCount}개는 삭제하지 못했습니다.`);
    return succeeded;
  }, [refreshConversations]);

  const branchConversation = useCallback(async (conversationId: string, anchorMessageId?: string | null) => {
    try {
      let resolvedAnchorMessageId = anchorMessageId;
      if (!resolvedAnchorMessageId) {
        let messages = runtimesRef.current[conversationId]?.turnSets.flatMap((turnSet) => turnSet.messages) ?? [];
        if (!messages.some((message) => message.role === "assistant" && message.status === "completed")) {
          const page = await api.conversations.getTurnSets(conversationId, undefined, 20);
          messages = page.turnSets.flatMap((turnSet) => turnSet.messages);
        }
        const anchor = [...messages].reverse().find((message) => message.role === "assistant" && message.status === "completed");
        if (!anchor) {
          setNotice("분기할 완료 답변이 없습니다.");
          return null;
        }
        resolvedAnchorMessageId = anchor.id;
      }
      const created = await api.conversations.branch(conversationId, resolvedAnchorMessageId);
      setConversations((items) => [created, ...items.filter((item) => item.id !== created.id)]);
      setRuntimes((current) => ({ ...current, [created.id]: emptyRuntime() }));
      setActiveConversationId(created.id);
      return created;
    } catch (error) {
      setNotice(apiMessage(error));
      return null;
    }
  }, []);

  const uploadFiles = useCallback(async (files: File[], source = "upload") => {
    if (!files.length) return [];
    let conversationId = activeConversationId;
    if (!conversationId) {
      const created = await createConversation();
      conversationId = created?.id ?? null;
    }
    if (!conversationId) return [];
    setUploadingAttachments(true);
    try {
      const uploaded = await Promise.all(
        files.map((file) => {
          const uploadFile = file.type.startsWith("image/")
            ? new File([file], imageAttachmentFileName(file.name), {
                type: file.type,
                lastModified: file.lastModified,
              })
            : file;
          return api.attachments.upload(conversationId, uploadFile, source);
        }),
      );
      setComposerAttachments((current) => [...current, ...uploaded]);
      return uploaded;
    } catch (error) {
      setNotice(apiMessage(error));
      return [];
    } finally {
      setUploadingAttachments(false);
    }
  }, [activeConversationId, createConversation]);

  const attachPastedText = useCallback(async (text: string) => {
    let conversationId = activeConversationId;
    if (!conversationId) {
      const created = await createConversation();
      conversationId = created?.id ?? null;
    }
    if (!conversationId) return null;
    setUploadingAttachments(true);
    try {
      const uploaded = await api.attachments.uploadPastedText(conversationId, text);
      setComposerAttachments((current) => [...current, uploaded]);
      return uploaded;
    } catch (error) {
      setNotice(apiMessage(error));
      return null;
    } finally {
      setUploadingAttachments(false);
    }
  }, [activeConversationId, createConversation]);

  const removeComposerAttachment = useCallback((attachmentId: string) => {
    setComposerAttachments((current) => current.filter((item) => item.id !== attachmentId));
  }, []);

  const sendMessage = useCallback(async (
    text: string,
    queueNext: boolean,
    promptReferences: PromptReference[] = [],
    targetOutputTokens?: number,
  ) => {
    const messageText = text.trim();
    if (!messageText || sending) return null;
    let conversationId = activeConversationId;
    let createdConversation: ConversationListItem | null = null;
    if (!conversationId) {
      const created = await createConversation();
      createdConversation = created;
      conversationId = created?.id ?? null;
    }
    const currentSettings = settingsRef.current;
    if (!conversationId || !currentSettings) return null;
    const listedConversation = conversationsRef.current.find((item) => item.id === conversationId) ?? createdConversation;
    const runtime = runtimesRef.current[conversationId];
    const activeSnapshot = Object.values(runtime?.snapshots ?? {}).find((snapshot) => !isTerminalRunStatus(snapshot.status));
    const activeRunId = listedConversation?.activeRunId ?? activeSnapshot?.runId ?? null;
    const shouldShowProvisionalTitle = Boolean(
      !activeRunId
      && listedConversation
      && UNTITLED_CONVERSATION_TITLES.has(listedConversation.title)
      && !runtime?.turnSets.some((turnSet) => turnSet.messages.some((message) => message.role === "user")),
    );
    const previousTitle = listedConversation?.title ?? null;
    if (shouldShowProvisionalTitle) {
      const provisionalTitle = provisionalConversationTitle(messageText);
      setConversations((items) => items.map((item) =>
        item.id === conversationId ? { ...item, title: provisionalTitle } : item,
      ));
    }
    const attachmentIds = composerAttachmentsRef.current
      .filter((item) => item.conversationId === conversationId)
      .map((item) => item.id);
    const input = {
      text: messageText,
      attachmentIds,
      promptReferences,
      outputMode: currentSettings.outputMode,
      ...(currentSettings.outputMode !== "chat" && targetOutputTokens
        ? { targetOutputTokens }
        : {}),
    };
    setSending(true);
    try {
      let mutation: RunMutationResponse;
      if (activeRunId) {
        mutation = await api.runs.action(activeRunId, {
          idempotencyKey: createClientId(),
          type: queueNext ? "queue_next" : "steer",
          message: input,
        });
      } else {
        mutation = await api.runs.start(conversationId, {
          idempotencyKey: createClientId(),
          message: input,
          execution: currentSettings.execution,
        });
      }
      mergeRunMutation(mutation);
      openSnapshotStream(mutation.run);
      setComposerAttachments((current) => current.filter((item) => item.conversationId !== conversationId));
      return queueNext ? "queue_next" : activeRunId ? "steer" : "run";
    } catch (error) {
      if (shouldShowProvisionalTitle && previousTitle) {
        setConversations((items) => items.map((item) =>
          item.id === conversationId ? { ...item, title: previousTitle } : item,
        ));
      }
      setNotice(apiMessage(error));
      return null;
    } finally {
      setSending(false);
    }
  }, [activeConversationId, createConversation, mergeRunMutation, openSnapshotStream, sending]);

  const runAction = useCallback(async (
    runId: string,
    action: RunControlAction,
    targetId?: string,
  ) => {
    if (runActionBusy || ["retry_step", "approve", "reject"].includes(action) && !targetId) return false;
    const payload: RunActionRequest = action === "retry_step"
      ? { idempotencyKey: createClientId(), type: action, stepId: targetId as string }
      : action === "approve" || action === "reject"
        ? { idempotencyKey: createClientId(), type: action, approvalId: targetId as string }
      : { idempotencyKey: createClientId(), type: action };
    setRunActionBusy(true);
    try {
      const mutation = await api.runs.action(runId, payload);
      const previous = runtimesRef.current[mutation.run.conversationId]?.snapshots[runId];
      if (previous && isTerminalRunStatus(previous.status) && !isTerminalRunStatus(mutation.run.status)) {
        streamsRef.current.get(runId)?.();
        streamsRef.current.delete(runId);
      }
      mergeRunMutation(mutation);
      openSnapshotStream(mutation.run);
      return true;
    } catch (error) {
      setNotice(apiMessage(error));
      return false;
    } finally {
      setRunActionBusy(false);
    }
  }, [mergeRunMutation, openSnapshotStream, runActionBusy]);

  const runPendingCommandAction = useCallback(async (
    runId: string,
    action: PendingCommandAction,
    commandId: string,
  ) => {
    if (runActionBusy) return false;
    setRunActionBusy(true);
    try {
      const mutation = await api.runs.action(runId, {
        idempotencyKey: createClientId(),
        type: action,
        commandId,
      });
      mergeRunMutation(mutation);
      openSnapshotStream(mutation.run);
      return true;
    } catch (error) {
      setNotice(apiMessage(error));
      return false;
    } finally {
      setRunActionBusy(false);
    }
  }, [mergeRunMutation, openSnapshotStream, runActionBusy]);

  const submitUserInput = useCallback(async (
    runId: string,
    inputRequestId: string,
    answers: UserInputAnswer[],
  ) => {
    if (runActionBusy) return false;
    setRunActionBusy(true);
    try {
      const mutation = await api.runs.action(runId, {
        idempotencyKey: createClientId(),
        type: "submit_user_input",
        inputRequestId,
        answers,
      });
      mergeRunMutation(mutation);
      openSnapshotStream(mutation.run);
      return true;
    } catch (error) {
      setNotice(apiMessage(error));
      return false;
    } finally {
      setRunActionBusy(false);
    }
  }, [mergeRunMutation, openSnapshotStream, runActionBusy]);

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } catch (error) {
      setNotice(apiMessage(error));
    } finally {
      closeStreams();
      setAuthSession(null);
      setProjects([]);
      setConversations([]);
      setRuntimes({});
      setSettings(null);
      setProviders([]);
      setModels([]);
      setProviderModels({});
      setActiveProjectIdState(null);
      setActiveConversationId(null);
    }
  }, [closeStreams]);

  const activeRuntime = activeConversationId ? runtimes[activeConversationId] ?? emptyRuntime() : emptyRuntime();
  const activeConversation = conversations.find((item) => item.id === activeConversationId) ?? null;
  const activeRun = useMemo(() => {
    if (!activeConversationId) return null;
    const snapshots = Object.values(activeRuntime.snapshots);
    if (activeConversation?.activeRunId && activeRuntime.snapshots[activeConversation.activeRunId]) {
      return activeRuntime.snapshots[activeConversation.activeRunId];
    }
    return snapshots.sort((a, b) => (b.startedAt ?? "").localeCompare(a.startedAt ?? ""))[0] ?? null;
  }, [activeConversation?.activeRunId, activeConversationId, activeRuntime.snapshots]);
  const selectedModel = models.find((item) => item.modelKey === settings?.execution.modelKey) ?? null;

  return {
    authSession,
    bootError,
    onAuthenticated: (session: AuthSession) => {
      setAuthSession(session);
      setBootError(null);
    },
    refreshAuthSession: async () => {
      setAuthSession(await api.auth.getSession());
    },
    logout,
    projects,
    activeProjectId,
    setActiveProjectId,
    createProject,
    refreshProjects,
    updateProjectDetails,
    archiveProject,
    conversations,
    activeConversation,
    activeConversationId,
    selectConversation: setActiveConversationId,
    openConversation,
    startNewConversation,
    createConversation,
    renameConversation,
    toggleFavoriteConversation,
    toggleLikedConversation,
    moveConversation,
    deleteConversation,
    moveConversations,
    deleteConversations,
    branchConversation,
    refreshConversations,
    activeRuntime,
    activeRun,
    loadConversation,
    settings,
    providers,
    models,
    providerModels,
    refreshProviderCatalog,
    selectedModel,
    selectProvider,
    selectModel,
    selectModelCandidate,
    toggleModelCandidate,
    setModelCandidates,
    selectEffort,
    selectOutputMode,
    selectClarificationMode,
    toggleTheme,
    sendMessage,
    sending,
    runAction,
    runActionBusy,
    runPendingCommandAction,
    submitUserInput,
    composerAttachments: composerAttachments.filter((item) => item.conversationId === activeConversationId),
    uploadingAttachments,
    uploadFiles,
    attachPastedText,
    removeComposerAttachment,
    loadingWorkspace,
    notice,
    clearNotice,
  };
}

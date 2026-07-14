import { createContext, useContext, useEffect, useRef, useState, type PropsWithChildren } from "react";
import { AlertCircle, LoaderCircle } from "lucide-react";
import { subscribeBackendTransportFailures } from "./api";

const HEALTH_CHECK_INTERVAL_MS = 1_500;
const RECOVERY_SUCCESS_THRESHOLD = 3;

export type BackendConnectionState = "checking" | "online" | "recovering" | "offline";

const BackendConnectionContext = createContext<BackendConnectionState>("checking");

export function useBackendConnectionState() {
  return useContext(BackendConnectionContext);
}

export function BackendConnectionGuard({ children }: PropsWithChildren) {
  const [disconnected, setDisconnected] = useState(false);
  const [connectionState, setConnectionState] = useState<BackendConnectionState>("checking");
  const disconnectedRef = useRef(false);
  const recoverySuccessCountRef = useRef(0);
  const reloadRequestedRef = useRef(false);

  useEffect(() => {
    let stopped = false;
    let timer: number | null = null;
    let controller: AbortController | null = null;

    const markDisconnected = () => {
      recoverySuccessCountRef.current = 0;
      disconnectedRef.current = true;
      setDisconnected(true);
      setConnectionState("offline");
    };

    const unsubscribeTransportFailures = subscribeBackendTransportFailures(markDisconnected);

    const check = async () => {
      controller = new AbortController();
      try {
        const response = await fetch("/api/health/ready", {
          cache: "no-store",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Backend readiness returned ${response.status}.`);
        if (disconnectedRef.current) {
          recoverySuccessCountRef.current += 1;
          setConnectionState("recovering");
          if (recoverySuccessCountRef.current < RECOVERY_SUCCESS_THRESHOLD) {
            // Keep polling until readiness has remained stable across multiple checks.
          } else if (!reloadRequestedRef.current) {
            reloadRequestedRef.current = true;
            window.location.reload();
            return;
          }
        } else {
          recoverySuccessCountRef.current = 0;
          setConnectionState("online");
        }
      } catch {
        if (stopped || controller.signal.aborted) return;
        markDisconnected();
      }
      if (!stopped) timer = window.setTimeout(check, HEALTH_CHECK_INTERVAL_MS);
    };

    void check();
    return () => {
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
      controller?.abort();
      unsubscribeTransportFailures();
    };
  }, []);

  return (
    <BackendConnectionContext.Provider value={connectionState}>
      {children}
      {disconnected && (
        <div className="backend-disconnected" role="alert" aria-live="assertive">
          <AlertCircle size={18} aria-hidden="true" />
          <div>
            <strong>시스템 접속이 끊겼습니다.</strong>
            <span>연결이 안정되면 자동으로 새로고침합니다.</span>
          </div>
          <LoaderCircle className="is-running" size={17} aria-hidden="true" />
        </div>
      )}
    </BackendConnectionContext.Provider>
  );
}

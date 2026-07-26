import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("backend recovery waits for consecutive readiness checks before reloading", async () => {
  const [guard, stylesheet] = await Promise.all([
    read("../src/BackendConnectionGuard.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(guard, /const RECOVERY_SUCCESS_THRESHOLD = 3/);
  assert.match(guard, /recoverySuccessCountRef\.current \+= 1/);
  assert.match(guard, /recoverySuccessCountRef\.current < RECOVERY_SUCCESS_THRESHOLD/);
  assert.match(guard, /recoverySuccessCountRef\.current = 0/);
  assert.match(guard, /window\.location\.reload\(\)/);
  assert.match(guard, /연결이 안정되면 자동으로 새로고침합니다/);
  assert.match(stylesheet, /\.backend-disconnected > \.is-running \{[^}]*color: var\(--danger\)/);
});

test("the global connection label follows readiness and API transport failures", async () => {
  const [app, api, guard, stylesheet] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/api.ts"),
    read("../src/BackendConnectionGuard.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(api, /async function fetchBackend/);
  assert.match(api, /reportBackendTransportFailure\(error\)/);
  assert.match(api, /subscribeBackendTransportFailures/);
  assert.match(api, /error instanceof DOMException && error\.name === "AbortError"/);
  assert.match(guard, /createContext<BackendConnectionState>\("checking"\)/);
  assert.match(guard, /subscribeBackendTransportFailures\(markDisconnected\)/);
  assert.match(guard, /setConnectionState\("online"\)/);
  assert.match(guard, /setConnectionState\("offline"\)/);
  assert.match(app, /backendConnectionState === "offline"[\s\S]*?"연결 끊김"/);
  assert.match(app, /backendConnectionState === "checking"[\s\S]*?"연결 확인 중"/);
  assert.match(app, /state-\$\{connectionIndicatorState\}/);
  assert.match(stylesheet, /\.connection-state\.state-offline/);
});

test("API contract mismatches do not masquerade as successful SPA responses", async () => {
  const api = await read("../src/api.ts");

  assert.match(api, /BACKEND_CONTRACT_MISMATCH_MESSAGE = "Frontend와 Backend 버전이 일치하지 않습니다\./);
  assert.match(api, /contentType\.includes\("text\/html"\)/);
  assert.match(api, /backendContractMismatch \? "backend_contract_mismatch" : "invalid_api_response"/);
  assert.match(api, /details: \{ contentType, path, method:/);
  assert.match(api, /response\.status === 404 && payload\.detail === "Not Found"/);
});

test("the backend recovery guard stays mounted around the top-level error screen", async () => {
  const [main, boundary, stylesheet] = await Promise.all([
    read("../src/main.tsx"),
    read("../src/AppErrorBoundary.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(main, /<BackendConnectionGuard>[\s\S]*<AppErrorBoundary>/);
  assert.doesNotMatch(main, /<AppErrorBoundary>[\s\S]*<BackendConnectionGuard>/);
  assert.match(boundary, /class AppErrorBoundary extends Component/);
  assert.match(boundary, /static getDerivedStateFromError/);
  assert.match(boundary, /componentDidCatch/);
  assert.match(boundary, /role="alert"/);
  assert.match(boundary, /화면 다시 불러오기/);
  assert.match(boundary, /window\.location\.reload\(\)/);
  assert.match(stylesheet, /\.app-error-boundary/);
});

test("terminal runs expose their reason and keep the copy action meaningful", async () => {
  const [app, apiTypes, runService, stylesheet] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/api-types.ts"),
    read("../../server/src/lumina/runs/service.py"),
    read("../src/styles.css"),
  ]);

  assert.match(runService, /"errorCode": run\.error_code/);
  assert.match(runService, /"errorMessage": run\.error_message/);
  assert.match(apiTypes, /errorCode: string \| null;\s+errorMessage: string \| null;/);
  assert.match(app, /const terminalReason = status && status !== "completed"/);
  assert.match(app, /const copyableAnswerText = sanitizedAssistantText \|\| terminalReason/);
  assert.match(app, /else await copyText\(terminalReason\)/);
  assert.doesNotMatch(app, /중단 사유를 복사했습니다/);
  assert.match(app, /disabled=\{!copyableAnswerText\}/);
  assert.match(app, /className="final-answer-error" role="alert"/);
  assert.match(stylesheet, /\.final-answer-error/);
});

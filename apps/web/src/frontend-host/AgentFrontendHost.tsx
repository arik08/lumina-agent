import { Suspense } from "react";
import type { AgentFrontendReference } from "../api-types";
import { SharedSnapshotViewer } from "../components/SharedSnapshotViewer";
import {
  DEFAULT_AGENT_FRONTEND,
  resolveBuiltinFrontendModule,
} from "./registry";

interface AgentFrontendHostProps {
  reference?: AgentFrontendReference;
}

function sharedRouteFromLocation() {
  const match = window.location.pathname.match(/^\/shared\/([^/]+)\/?$/);
  if (!match) return null;
  const params = new URLSearchParams(window.location.search);
  let token = match[1];
  try {
    token = decodeURIComponent(token);
  } catch {
    // Keep the opaque path segment so the API can reject malformed tokens.
  }
  const artifactId = params.get("artifact");
  const parsedVersion = Number(params.get("version"));
  return {
    artifactId,
    artifactVersion: artifactId && Number.isInteger(parsedVersion) && parsedVersion > 0
      ? parsedVersion
      : null,
    theme: params.get("theme") === "dark" ? "dark" as const : "light" as const,
    token,
  };
}

export function AgentFrontendHost({
  reference = DEFAULT_AGENT_FRONTEND,
}: AgentFrontendHostProps) {
  const sharedRoute = sharedRouteFromLocation();
  if (sharedRoute) {
    return <SharedSnapshotViewer {...sharedRoute} />;
  }
  const Frontend = resolveBuiltinFrontendModule(reference).component;
  return (
    <Suspense fallback={<div className="frontend-boot-loading" role="status">Lumina를 준비하고 있습니다.</div>}>
      <Frontend />
    </Suspense>
  );
}

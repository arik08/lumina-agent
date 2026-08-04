import { lazy, Suspense } from "react";
import type { AgentFrontendReference } from "../api-types";
import { SharedSnapshotViewer } from "../components/SharedSnapshotViewer";
import {
  DEFAULT_AGENT_FRONTEND,
  resolveBuiltinFrontendModule,
} from "./registry";

const ProjectFileStandalonePreview = lazy(() => import("../components/ProjectFileStandalonePreview").then(({ ProjectFileStandalonePreview }) => ({ default: ProjectFileStandalonePreview })));

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

function projectFilePreviewRouteFromLocation() {
  const match = window.location.pathname.match(/^\/project-files\/([^/]+)\/([^/]+)\/preview\/?$/);
  if (!match) return null;
  try {
    return { projectId: decodeURIComponent(match[1]), fileId: decodeURIComponent(match[2]) };
  } catch {
    return { projectId: match[1], fileId: match[2] };
  }
}

export function AgentFrontendHost({
  reference = DEFAULT_AGENT_FRONTEND,
}: AgentFrontendHostProps) {
  const sharedRoute = sharedRouteFromLocation();
  if (sharedRoute) {
    return <SharedSnapshotViewer {...sharedRoute} />;
  }
  const projectFilePreviewRoute = projectFilePreviewRouteFromLocation();
  if (projectFilePreviewRoute) {
    return <Suspense fallback={<div className="frontend-boot-loading" role="status">파일 미리보기를 준비하고 있습니다.</div>}><ProjectFileStandalonePreview {...projectFilePreviewRoute} /></Suspense>;
  }
  const Frontend = resolveBuiltinFrontendModule(reference).component;
  return (
    <Suspense fallback={<div className="frontend-boot-loading" role="status">Lumina를 준비하고 있습니다.</div>}>
      <Frontend />
    </Suspense>
  );
}

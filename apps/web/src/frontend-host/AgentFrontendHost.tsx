import { Suspense } from "react";
import type { AgentFrontendReference } from "../api-types";
import {
  DEFAULT_AGENT_FRONTEND,
  resolveBuiltinFrontendModule,
} from "./registry";

interface AgentFrontendHostProps {
  reference?: AgentFrontendReference;
}

export function AgentFrontendHost({
  reference = DEFAULT_AGENT_FRONTEND,
}: AgentFrontendHostProps) {
  const Frontend = resolveBuiltinFrontendModule(reference).component;
  return (
    <Suspense fallback={<div className="frontend-boot-loading" role="status">Lumina를 준비하고 있습니다.</div>}>
      <Frontend />
    </Suspense>
  );
}

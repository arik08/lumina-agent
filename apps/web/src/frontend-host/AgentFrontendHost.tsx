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
  return <Frontend />;
}

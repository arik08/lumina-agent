import { lazy, type ComponentType } from "react";
import type { AgentFrontendReference } from "../api-types";

export const DEFAULT_AGENT_FRONTEND: AgentFrontendReference = {
  id: "general",
  version: "1",
  frontendModule: "general-chat",
  frontendContract: "lumina-frontend-v1",
  fallback: false,
};

interface BuiltinFrontendModule {
  contract: string;
  component: ComponentType;
}

const builtinFrontendModules: Readonly<Record<string, BuiltinFrontendModule>> = {
  "general-chat": {
    contract: "lumina-frontend-v1",
    component: lazy(() => import("../agent-frontends/general-chat")),
  },
};

export function resolveBuiltinFrontendModule(reference: AgentFrontendReference) {
  const candidate = builtinFrontendModules[reference.frontendModule];
  if (candidate?.contract === reference.frontendContract) return candidate;
  return builtinFrontendModules[DEFAULT_AGENT_FRONTEND.frontendModule];
}

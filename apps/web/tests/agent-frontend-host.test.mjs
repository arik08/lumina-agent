import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const mainPath = new URL("../src/main.tsx", import.meta.url);
const registryPath = new URL("../src/frontend-host/registry.tsx", import.meta.url);
const hostPath = new URL("../src/frontend-host/AgentFrontendHost.tsx", import.meta.url);

test("the app enters through the explicit builtin frontend host", async () => {
  const [main, registry, host] = await Promise.all([
    readFile(mainPath, "utf8"),
    readFile(registryPath, "utf8"),
    readFile(hostPath, "utf8"),
  ]);

  assert.match(main, /<AgentFrontendHost\s*\/>/);
  assert.match(registry, /"general-chat"/);
  assert.match(registry, /lumina-frontend-v1/);
  assert.match(
    registry,
    /return builtinFrontendModules\[DEFAULT_AGENT_FRONTEND\.frontendModule\]/,
  );
  assert.match(registry, /component: lazy\(\(\) => import\("\.\.\/agent-frontends\/general-chat"\)\)/);
  assert.match(host, /resolveBuiltinFrontendModule\(reference\)/);
  assert.match(host, /<Suspense fallback=/);
});

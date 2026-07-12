import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const repositoryRoot = "../..";

function readPort(value: string | undefined, fallback: number, name: string): number {
  const port = Number(value || String(fallback));
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535.`);
  }
  return port;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repositoryRoot, "");
  const frontendPort = readPort(env.LUMINA_FRONTEND_PORT, 5252, "LUMINA_FRONTEND_PORT");
  const backendPort = readPort(env.LUMINA_BACKEND_PORT, 5253, "LUMINA_BACKEND_PORT");
  if (frontendPort === backendPort) {
    throw new Error("LUMINA_FRONTEND_PORT and LUMINA_BACKEND_PORT must use different ports.");
  }
  const backendTarget = `http://127.0.0.1:${backendPort}`;

  return {
    cacheDir: "../../.cache/vite",
    envDir: repositoryRoot,
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: frontendPort,
      strictPort: true,
      proxy: {
        "/api": {
          target: backendTarget,
          changeOrigin: true,
        },
        "/stream": {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
  };
});

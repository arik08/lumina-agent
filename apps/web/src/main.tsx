import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { BackendConnectionGuard } from "./BackendConnectionGuard";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <BackendConnectionGuard>
        <App />
      </BackendConnectionGuard>
    </AppErrorBoundary>
  </StrictMode>,
);

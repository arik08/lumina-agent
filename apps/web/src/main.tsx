import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { BackendConnectionGuard } from "./BackendConnectionGuard";
import { GlobalTooltipProvider } from "./components/GlobalTooltip";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <GlobalTooltipProvider>
        <BackendConnectionGuard>
          <App />
        </BackendConnectionGuard>
      </GlobalTooltipProvider>
    </AppErrorBoundary>
  </StrictMode>,
);

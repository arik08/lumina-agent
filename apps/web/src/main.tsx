import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { BackendConnectionGuard } from "./BackendConnectionGuard";
import { GlobalTooltipProvider } from "./components/GlobalTooltip";
import { installScrollbarActivity } from "./scrollbar-activity";
import "./styles.css";

const disposeScrollbarActivity = installScrollbarActivity();
import.meta.hot?.dispose(disposeScrollbarActivity);

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

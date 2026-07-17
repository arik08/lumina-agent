import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { BackendConnectionGuard } from "./BackendConnectionGuard";
import "./components/ArtifactLibraryView.css";
import { GlobalTooltipProvider } from "./components/GlobalTooltip";
import { AgentFrontendHost } from "./frontend-host/AgentFrontendHost";
import { installScrollbarActivity } from "./scrollbar-activity";
import "./styles.css";

const disposeScrollbarActivity = installScrollbarActivity();
import.meta.hot?.dispose(disposeScrollbarActivity);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <GlobalTooltipProvider>
        <BackendConnectionGuard>
          <AgentFrontendHost />
        </BackendConnectionGuard>
      </GlobalTooltipProvider>
    </AppErrorBoundary>
  </StrictMode>,
);

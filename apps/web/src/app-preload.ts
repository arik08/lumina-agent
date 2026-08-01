export type PreloadableAppView =
  | "deep-analysis"
  | "knowledge"
  | "marketplace"
  | "library"
  | "files"
  | "schedules"
  | "memory";

const viewLoaders: Record<PreloadableAppView, () => Promise<unknown>> = {
  "deep-analysis": () => import("./workspace-frontends/deep-analysis"),
  knowledge: () => import("./workspace-frontends/knowledge"),
  marketplace: () => import("./components/MarketplaceView"),
  library: () => import("./components/ArtifactLibraryView"),
  files: () => import("./components/ProjectFilesView"),
  schedules: () => import("./components/SchedulesView"),
  memory: () => import("./components/MemoryView"),
};

export const backgroundPreloadOrder: readonly PreloadableAppView[] = [
  "deep-analysis",
  "knowledge",
  "files",
  "library",
  "schedules",
  "memory",
  "marketplace",
];

interface NavigatorWithConnection extends Navigator {
  connection?: {
    saveData?: boolean;
    effectiveType?: string;
  };
}

export function shouldBackgroundPreloadAppViews() {
  if (typeof navigator === "undefined") return false;
  const connection = (navigator as NavigatorWithConnection).connection;
  if (connection?.saveData) return false;
  return !["slow-2g", "2g"].includes(connection?.effectiveType?.toLowerCase() ?? "");
}

export async function preloadAppView(view: string) {
  const loader = viewLoaders[view as PreloadableAppView];
  if (!loader) return;
  await loader().catch(() => undefined);
}

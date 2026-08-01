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

export function preloadAppView(view: string) {
  const loader = viewLoaders[view as PreloadableAppView];
  if (loader) void loader().catch(() => undefined);
}

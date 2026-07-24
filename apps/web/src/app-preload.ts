import {
  getAdminAuditTraffic,
  getAdminUsageStatistics,
  getDeepAnalysisMission,
  getKnowledgeDocument,
  getKnowledgeGraph,
  getMemorySettings,
  getOrganizationInstructions,
  getPersonalInstructions,
  listAdminAuditEvents,
  listAdminConversations,
  listAdminUsers,
  listArtifacts,
  listDeepAnalysisMissions,
  listExtensionInstallations,
  listExtensions,
  listKnowledgeDocuments,
  listKnowledgeSpaces,
  listKnowledgeTags,
  listMcpCatalog,
  listMcpInstallations,
  listMemories,
  listProjectFiles,
  listProjectFolders,
  listProjectLearningProposals,
  listProjectMemories,
  listProjects,
  listRuntimePrompts,
  listScheduledRuns,
  listScheduledTasks,
  listSkillCatalog,
  listTrashedExtensions,
  prefetchApiData,
} from "./api";

export const loadAdminView = () => import("./components/AdminView");
export const loadArtifactHtmlPreview = () => import("./components/ArtifactHtmlPreview");
export const loadArtifactLibraryView = () => import("./components/ArtifactLibraryView");
export const loadHelpCenterView = () => import("./components/HelpCenterView");
export const loadMarketplaceView = () => import("./components/MarketplaceView");
export const loadMemoryView = () => import("./components/MemoryView");
export const loadProjectFilesView = () => import("./components/ProjectFilesView");
export const loadProjectSettings = () => import("./components/ProjectSettings");
export const loadSchedulesView = () => import("./components/SchedulesView");
export const loadDeepAnalysisView = () => import("./workspace-frontends/deep-analysis");
export const loadKnowledgeView = () => import("./workspace-frontends/knowledge");

export interface AppPreloadContext {
  projectId: string | null;
  isAdmin: boolean;
}

export async function preloadAppViews({ projectId, isAdmin }: AppPreloadContext) {
  const moduleLoads = [
    loadArtifactHtmlPreview(),
    loadArtifactLibraryView(),
    loadHelpCenterView(),
    loadMarketplaceView(),
    loadMemoryView(),
    loadProjectFilesView(),
    loadProjectSettings(),
    loadSchedulesView(),
    loadDeepAnalysisView(),
    loadKnowledgeView(),
    ...(isAdmin ? [loadAdminView()] : []),
  ];

  await Promise.allSettled([
    ...moduleLoads,
    prefetchApiData(async () => {
      const missionsRequest = projectId ? listDeepAnalysisMissions(projectId) : Promise.resolve([]);
      const spacesRequest = listKnowledgeSpaces();
      const schedulesRequest = projectId ? listScheduledTasks(projectId) : Promise.resolve([]);

      const initialRequests: Promise<unknown>[] = [
        listExtensions(),
        listTrashedExtensions(),
        listExtensionInstallations(),
        listSkillCatalog({ sort: "popular", offset: 0, limit: 60 }),
        listMcpCatalog(),
        listMcpInstallations(),
        listMemories(undefined, "active"),
        getMemorySettings(),
        listProjects(),
        listArtifacts(projectId ?? undefined),
        missionsRequest,
        spacesRequest,
        schedulesRequest,
      ];

      if (projectId) {
        initialRequests.push(
          listProjectFiles(projectId),
          listProjectFolders(projectId),
          listProjectMemories(projectId),
          listProjectLearningProposals(projectId),
        );
      }

      if (isAdmin) {
        initialRequests.push(
          listAdminUsers({ query: "", limit: 100 }),
          getAdminUsageStatistics(30),
          listAdminConversations({ query: "", feedbackOnly: false, limit: 120 }),
          listAdminAuditEvents({ action: "", limit: 120 }),
          getAdminAuditTraffic(60),
          listAdminAuditEvents({
            action: "organization_instructions_changed",
            targetType: "organization_instructions",
            limit: 50,
          }),
          getOrganizationInstructions(),
          listRuntimePrompts(),
          getPersonalInstructions(),
        );
      }

      await Promise.allSettled(initialRequests);

      const [missionsResult, spacesResult, schedulesResult] = await Promise.allSettled([
        missionsRequest,
        spacesRequest,
        schedulesRequest,
      ]);
      const detailRequests: Promise<unknown>[] = [];

      if (missionsResult.status === "fulfilled" && missionsResult.value[0]) {
        const storedMissionId = projectId
          ? window.localStorage.getItem(`lumina:deep-analysis:selected:${projectId}`)
          : null;
        const selectedMission = missionsResult.value.find((mission) => mission.id === storedMissionId)
          ?? missionsResult.value[0];
        detailRequests.push(getDeepAnalysisMission(selectedMission.id));
      }
      if (spacesResult.status === "fulfilled" && spacesResult.value[0]) {
        const spaceId = spacesResult.value[0].id;
        const documentsRequest = listKnowledgeDocuments({ spaceId });
        detailRequests.push(
          listKnowledgeTags(spaceId),
          getKnowledgeGraph(spaceId),
          documentsRequest.then((documents) => (
            documents[0] ? getKnowledgeDocument(documents[0].id) : undefined
          )),
        );
      }
      if (schedulesResult.status === "fulfilled" && schedulesResult.value[0]) {
        detailRequests.push(listScheduledRuns(schedulesResult.value[0].id));
      }

      await Promise.allSettled(detailRequests);
    }),
  ]);
}

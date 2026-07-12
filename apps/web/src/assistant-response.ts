const internalArtifactMetadataLine =
  /^[ \t]*(?:[-*+]\s*)?(?:\*\*|__)?Artifact(?: ID)?(?:(?:\*\*|__)?[ \t]*:|[ \t]*:(?:\*\*|__))[ \t]*`?[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`?[ \t]*\r?\n?/gim;

export function sanitizeAssistantResponse(text: string, hasArtifacts = false) {
  const withoutInternalArtifactMetadata = text.replace(internalArtifactMetadataLine, "");
  if (!hasArtifacts) return withoutInternalArtifactMetadata;
  return withoutInternalArtifactMetadata.replace(/^[ \t]*보고서 열기[ \t]*\r?\n?/gm, "");
}

const internalArtifactMetadataLine =
  /^[ \t]*(?:[-*+]\s*)?(?:\*\*|__)?Artifact(?: ID)?(?:(?:\*\*|__)?[ \t]*:|[ \t]*:(?:\*\*|__))[ \t]*`?[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`?[ \t]*\r?\n?/gim;
const providerCitationToken = /\uE200cite((?:\uE202[A-Za-z0-9][A-Za-z0-9._:-]{0,159})+)\uE201/giu;
const providerCitationSource = /\uE202([A-Za-z0-9][A-Za-z0-9._:-]{0,159})/giu;
const privateUseCharacters = /[\uE200-\uF8FF]/gu;

export function sanitizeAssistantResponse(
  text: string,
  hasArtifacts = false,
  sourceIds: readonly string[] = [],
) {
  const knownSourceIds = new Set(sourceIds);
  const withoutProviderCitationTokens = text.replace(providerCitationToken, (_token, body: string) => {
    const markers: string[] = [];
    for (const match of body.matchAll(providerCitationSource)) {
      const sourceId = match[1];
      if (knownSourceIds.has(sourceId)) markers.push(`[source:${sourceId}]`);
    }
    return markers.join("");
  }).replace(privateUseCharacters, "");
  const withoutInternalArtifactMetadata = withoutProviderCitationTokens.replace(internalArtifactMetadataLine, "");
  if (!hasArtifacts) return withoutInternalArtifactMetadata;
  return withoutInternalArtifactMetadata.replace(/^[ \t]*보고서 열기[ \t]*\r?\n?/gm, "");
}

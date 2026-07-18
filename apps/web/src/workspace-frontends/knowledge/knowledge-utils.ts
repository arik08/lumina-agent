import type { KnowledgeEntity, KnowledgeSource, KnowledgeStatement } from "../../api-types";

export function formatDate(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function formatBytes(value: number) {
  if (value < 1_024) return `${value} B`;
  if (value < 1_048_576) return `${(value / 1_024).toFixed(1)} KB`;
  return `${(value / 1_048_576).toFixed(1)} MB`;
}

export function statementObject(statement: KnowledgeStatement, entityById: Map<string, KnowledgeEntity>) {
  if (statement.objectEntityId) return entityById.get(statement.objectEntityId)?.canonicalName ?? "알 수 없는 Entity";
  if (typeof statement.objectValue === "string") return statement.objectValue;
  if (statement.objectValue == null) return "-";
  return JSON.stringify(statement.objectValue);
}

export function statementSentence(statement: KnowledgeStatement, entityById: Map<string, KnowledgeEntity>) {
  const subject = entityById.get(statement.subjectEntityId)?.canonicalName ?? "알 수 없는 Entity";
  return `${subject} ${statement.predicateKey.replaceAll("_", " ")} ${statementObject(statement, entityById)}`;
}

export function sourceForEvidence(sources: KnowledgeSource[], evidenceId: string) {
  return sources.find((source) => source.evidenceSegments.some((evidence) => evidence.id === evidenceId)) ?? null;
}

export function evidenceById(sources: KnowledgeSource[]) {
  return new Map(sources.flatMap((source) => source.evidenceSegments.map((evidence) => [evidence.id, { evidence, source }] as const)));
}

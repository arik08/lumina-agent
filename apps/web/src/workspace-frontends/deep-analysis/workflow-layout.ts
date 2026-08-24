import type { DeepAnalysisWorkflowRevision } from "../../api-types";

export function normalizeWorkflowSequenceEdges(workflow: DeepAnalysisWorkflowRevision) {
  const nodeByKey = new Map(workflow.nodes.map((node) => [node.nodeKey, node]));
  const sequencePairs = new Set<string>();
  return {
    ...workflow,
    edges: workflow.edges.flatMap((edge) => {
      if (edge.edgeType === "loop_back") return [edge];
      const source = nodeByKey.get(edge.sourceNodeKey);
      const target = nodeByKey.get(edge.targetNodeKey);
      if (!source || !target) return [edge];
      const pairKey = `${edge.sourceNodeKey}\u0000${edge.targetNodeKey}`;
      if (sequencePairs.has(pairKey)) return [];
      sequencePairs.add(pairKey);
      return [edge];
    }),
  };
}

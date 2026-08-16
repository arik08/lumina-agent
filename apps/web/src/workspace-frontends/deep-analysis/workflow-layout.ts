import type {
  DeepAnalysisWorkflowNode,
  DeepAnalysisWorkflowRevision,
} from "../../api-types";

export function workflowSequenceEdgeEndpoints(
  source: DeepAnalysisWorkflowNode,
  target: DeepAnalysisWorkflowNode,
) {
  const sourceComesFirst = source.sequence !== target.sequence
    ? source.sequence < target.sequence
    : source.positionY !== target.positionY
      ? source.positionY < target.positionY
      : source.nodeKey.localeCompare(target.nodeKey) < 0;
  return sourceComesFirst
    ? { sourceNodeKey: source.nodeKey, targetNodeKey: target.nodeKey }
    : { sourceNodeKey: target.nodeKey, targetNodeKey: source.nodeKey };
}

export function orientWorkflowSequenceEdges(workflow: DeepAnalysisWorkflowRevision) {
  const nodeByKey = new Map(workflow.nodes.map((node) => [node.nodeKey, node]));
  const sequencePairs = new Set<string>();
  return {
    ...workflow,
    edges: workflow.edges.flatMap((edge) => {
      if (edge.edgeType === "loop_back") return [edge];
      const source = nodeByKey.get(edge.sourceNodeKey);
      const target = nodeByKey.get(edge.targetNodeKey);
      if (!source || !target) return [edge];
      const endpoints = workflowSequenceEdgeEndpoints(source, target);
      const pairKey = `${endpoints.sourceNodeKey}\u0000${endpoints.targetNodeKey}`;
      if (sequencePairs.has(pairKey)) return [];
      sequencePairs.add(pairKey);
      return [{ ...edge, ...endpoints }];
    }),
  };
}

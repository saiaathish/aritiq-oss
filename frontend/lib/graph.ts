import type { Result } from "./types";

export interface GraphNode {
  id: string;
  result: Result;
  index: number;
  deps: string[];
}

export interface GraphEdge {
  source: GraphNode;
  target: GraphNode;
}

export interface GraphModel {
  nodes: GraphNode[];
  byId: Map<string, GraphNode>;
  edges: GraphEdge[];
  missingDependencyRefs: Array<{ targetId: string; missingId: string }>;
}

export interface GraphNeighborhood {
  node: GraphNode;
  upstream: GraphNode[];
  downstream: GraphNode[];
  causedBy: GraphNode | null;
  missingUpstream: string[];
}

export function graphNodeId(result: Result, index: number): string {
  return result.claim.node_id || `claim-${index + 1}`;
}

export function buildGraphModel(results: Result[]): GraphModel {
  const nodes = results.map((result, index) => ({
    id: graphNodeId(result, index),
    result,
    index,
    deps: result.claim.depends_on ?? [],
  }));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const edges: GraphEdge[] = [];
  const missingDependencyRefs: Array<{ targetId: string; missingId: string }> = [];

  for (const target of nodes) {
    for (const dep of target.deps) {
      const source = byId.get(dep);
      if (source) {
        edges.push({ source, target });
      } else {
        missingDependencyRefs.push({ targetId: target.id, missingId: dep });
      }
    }
  }

  return { nodes, byId, edges, missingDependencyRefs };
}

export function getGraphNeighborhood(model: GraphModel, nodeId: string): GraphNeighborhood | null {
  const node = model.byId.get(nodeId);
  if (!node) return null;

  const upstream: GraphNode[] = [];
  const missingUpstream: string[] = [];
  for (const dep of node.deps) {
    const source = model.byId.get(dep);
    if (source) upstream.push(source);
    else missingUpstream.push(dep);
  }

  const downstream = model.edges
    .filter((edge) => edge.source.id === node.id)
    .map((edge) => edge.target);

  const causedBy = node.result.caused_by ? model.byId.get(node.result.caused_by) ?? null : null;

  return { node, upstream, downstream, causedBy, missingUpstream };
}

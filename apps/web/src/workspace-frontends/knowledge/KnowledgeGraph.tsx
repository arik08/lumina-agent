import { BookOpenText, CircleDot, GitBranch, LoaderCircle } from "lucide-react";
import { useMemo } from "react";
import type { KnowledgeEntity, KnowledgeNeighborhood, KnowledgeStatement } from "../../api-types";

interface KnowledgeGraphProps {
  neighborhood: KnowledgeNeighborhood | null;
  entities: KnowledgeEntity[];
  statements: KnowledgeStatement[];
  selectedEntityId: string | null;
  onSelectEntity: (entityId: string) => void;
  onOpenWiki: (entityId: string) => void;
}

export function KnowledgeGraph({ neighborhood, entities, statements, selectedEntityId, onSelectEntity, onOpenWiki }: KnowledgeGraphProps) {
  const nodes = neighborhood?.nodes ?? [];
  const root = entities.find((entity) => entity.id === selectedEntityId) ?? entities[0] ?? null;
  const positions = useMemo(() => {
    const result = new Map<string, { x: number; y: number }>();
    for (const [index, node] of nodes.entries()) {
      if (node.id === neighborhood?.rootEntityId) {
        result.set(node.id, { x: 370, y: 220 });
        continue;
      }
      const others = Math.max(1, nodes.length - 1);
      const adjustedIndex = nodes.slice(0, index).filter((item) => item.id !== neighborhood?.rootEntityId).length;
      const angle = (Math.PI * 2 * adjustedIndex) / others - Math.PI / 2;
      result.set(node.id, { x: 370 + Math.cos(angle) * 245, y: 220 + Math.sin(angle) * 150 });
    }
    return result;
  }, [neighborhood?.rootEntityId, nodes]);
  const approvedCount = statements.filter((statement) => statement.status === "approved").length;

  if (!entities.length) return <div className="knowledge-empty"><GitBranch size={25} /><h3>Entity를 먼저 등록해 주세요.</h3><p>승인된 Entity 관계만 Knowledge Graph에 표시됩니다.</p></div>;

  return (
    <div className="knowledge-graph-page">
      <aside className="knowledge-master-list knowledge-graph-entities">
        <header><div><strong>Entity</strong><small>{entities.length}개 · 승인 edge {approvedCount}개</small></div></header>
        {entities.map((entity) => <button className={root?.id === entity.id ? "is-active" : ""} type="button" key={entity.id} onClick={() => onSelectEntity(entity.id)}><CircleDot size={14} /><span><strong>{entity.canonicalName}</strong><small>{entity.entityType}</small></span></button>)}
      </aside>
      <section className="knowledge-graph-stage">
        <header><div><strong>{root?.canonicalName}</strong><small>2 hop neighborhood · 승인 Statement만 표시</small></div>{root && <button type="button" onClick={() => onOpenWiki(root.id)}><BookOpenText size={13} /> Wiki 열기</button>}</header>
        {!neighborhood || neighborhood.rootEntityId !== root?.id ? <div className="knowledge-loading"><LoaderCircle className="is-running" size={17} /> 관계를 불러오는 중</div> : nodes.length <= 1 ? <div className="knowledge-empty"><CircleDot size={23} /><h3>승인된 연결 관계가 없습니다.</h3><p>검토함에서 근거가 있는 Statement를 승인하면 그래프에 반영됩니다.</p></div> : <div className="knowledge-graph-scroll"><div className="knowledge-graph-canvas">
          <svg aria-hidden="true">{neighborhood.edges.map((edge) => {
            const source = positions.get(edge.subjectEntityId);
            const target = edge.objectEntityId ? positions.get(edge.objectEntityId) : null;
            if (!source || !target) return null;
            const x = (source.x + target.x) / 2;
            const y = (source.y + target.y) / 2;
            return <g key={edge.id}><line x1={source.x} y1={source.y} x2={target.x} y2={target.y} /><rect x={x - 44} y={y - 10} width="88" height="20" rx="10" /><text x={x} y={y + 3}>{edge.predicateKey}</text></g>;
          })}</svg>
          {nodes.map((node) => { const position = positions.get(node.id); return position ? <button className={node.id === neighborhood.rootEntityId ? "is-root" : ""} style={{ left: position.x, top: position.y }} type="button" key={node.id} onClick={() => onSelectEntity(node.id)}><CircleDot size={13} /><strong>{node.canonicalName}</strong><small>{node.entityType} · {node.depth ?? 0} hop</small></button> : null; })}
          {neighborhood.truncated && <span className="knowledge-truncated">안전한 표시 한도에 맞춰 일부 관계만 보여줍니다.</span>}
        </div></div>}
      </section>
    </div>
  );
}

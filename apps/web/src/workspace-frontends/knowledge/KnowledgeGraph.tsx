import { GitBranch, RotateCcw, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type ForceLink,
  type ForceManyBody,
  type ForceX,
  type ForceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { KnowledgeGraphResponse } from "../../api-types";

interface KnowledgeGraphProps { graph: KnowledgeGraphResponse; layoutKey: string; onSelectDocument: (documentId: string) => void; }

interface GraphNode extends SimulationNodeDatum {
  id: string;
  name: string;
  radius: number;
  degree: number;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  id: string;
  weight: number;
  tagNames: string[];
}

interface ForceSettings {
  centerStrength: number;
  repulsion: number;
  linkStrength: number;
  linkDistance: number;
}

interface Viewport { x: number; y: number; scale: number; }

interface GraphLayout {
  graphSignature: string;
  nodePositions: Map<string, { x: number; y: number }>;
  viewport: Viewport;
  width: number;
  height: number;
}

interface DragState {
  node: GraphNode;
  captureTarget: Element;
  pointerId: number;
  startX: number;
  startY: number;
  moved: boolean;
}

interface PanState {
  captureTarget: Element;
  pointerId: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
}

const defaultForceSettings: ForceSettings = {
  centerStrength: 0.018,
  repulsion: 140,
  linkStrength: 0.18,
  linkDistance: 88,
};

const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));
const lerp = (start: number, end: number, progress: number) => start + (end - start) * progress;

const edgeHitRadius = 10;
const graphLabelFontSize = 14;
const graphLabelGap = 7;
const hoverTransitionDuration = 160;
const graphLayouts = new Map<string, GraphLayout>();

function distanceToSegment(point: { x: number; y: number }, start: { x: number; y: number }, end: { x: number; y: number }) {
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  const lengthSquared = deltaX ** 2 + deltaY ** 2;
  if (lengthSquared === 0) return Math.hypot(point.x - start.x, point.y - start.y);
  const progress = clamp(((point.x - start.x) * deltaX + (point.y - start.y) * deltaY) / lengthSquared, 0, 1);
  return Math.hypot(point.x - (start.x + progress * deltaX), point.y - (start.y + progress * deltaY));
}

function endpointId(endpoint: GraphNode | string | number) {
  return typeof endpoint === "object" ? endpoint.id : String(endpoint);
}

function ForceControl({ label, value, minimum, maximum, step, onChange }: {
  label: string;
  value: number;
  minimum: number;
  maximum: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return <label className="knowledge-graph-force-control">
    <span>{label}<output>{value.toFixed(step < 1 ? 2 : 0)}</output></span>
    <input type="range" min={minimum} max={maximum} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} />
  </label>;
}

export function KnowledgeGraph({ graph, layoutKey, onSelectDocument }: KnowledgeGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const nodeLayerRef = useRef<HTMLDivElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const simulationRef = useRef<Simulation<GraphNode, GraphLink> | null>(null);
  const forceRefs = useRef<{
    link: ForceLink<GraphNode, GraphLink>;
    charge: ForceManyBody<GraphNode>;
    x: ForceX<GraphNode>;
    y: ForceY<GraphNode>;
  } | null>(null);
  const drawRef = useRef<() => void>(() => undefined);
  const onSelectDocumentRef = useRef(onSelectDocument);
  const [forceSettings, setForceSettings] = useState(defaultForceSettings);
  const [settingsOpen, setSettingsOpen] = useState(false);
  onSelectDocumentRef.current = onSelectDocument;

  useEffect(() => {
    const simulation = simulationRef.current;
    const forces = forceRefs.current;
    if (!simulation || !forces) return;
    forces.x.strength(forceSettings.centerStrength);
    forces.y.strength(forceSettings.centerStrength);
    forces.charge.strength(-forceSettings.repulsion);
    forces.link.strength(forceSettings.linkStrength).distance(forceSettings.linkDistance);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    simulation.alpha(0.55).alphaTarget(0);
    if (reducedMotion) {
      simulation.stop().tick(90);
      drawRef.current();
    } else {
      simulation.restart();
    }
  }, [forceSettings]);

  useEffect(() => {
    const canvasElement = canvasRef.current;
    const nodeLayerElement = nodeLayerRef.current;
    if (!canvasElement || !nodeLayerElement || !graph.nodes.length) return undefined;
    const contextValue = canvasElement.getContext("2d");
    if (!contextValue) return undefined;
    const canvas: HTMLCanvasElement = canvasElement;
    const nodeLayer: HTMLDivElement = nodeLayerElement;
    const context: CanvasRenderingContext2D = contextValue;
    const tooltip = tooltipRef.current;
    const graphSignature = [
      ...graph.nodes.map((node) => `node:${node.id}`),
      ...graph.edges.map((edge) => `edge:${edge.id}:${edge.sourceDocumentId}:${edge.targetDocumentId}`),
    ].sort().join("|");
    const savedLayout = graphLayouts.get(layoutKey);

    const orderedNodes = [...graph.nodes].sort((left, right) => left.id.localeCompare(right.id));
    const degrees = new Map(orderedNodes.map((node) => [node.id, 0]));
    graph.edges.forEach((edge) => {
      degrees.set(edge.sourceDocumentId, (degrees.get(edge.sourceDocumentId) ?? 0) + 1);
      degrees.set(edge.targetDocumentId, (degrees.get(edge.targetDocumentId) ?? 0) + 1);
    });
    const nodes: GraphNode[] = orderedNodes.map((node) => {
      const position = savedLayout?.nodePositions.get(node.id);
      const degree = degrees.get(node.id) ?? 0;
      return {
        id: node.id,
        name: node.title,
        degree,
        radius: 6 + Math.min(8, Math.sqrt(degree) * 2.2),
        ...(position ? { x: position.x, y: position.y } : {}),
      };
    });
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const tagNamesById = new Map(graph.nodes.flatMap((node) => node.tags.map((tag) => [tag.id, tag.name] as const)));
    const links: GraphLink[] = graph.edges
      .filter((edge) => nodeById.has(edge.sourceDocumentId) && nodeById.has(edge.targetDocumentId))
      .map((edge) => ({
        id: edge.id,
        source: edge.sourceDocumentId,
        target: edge.targetDocumentId,
        weight: edge.weight,
        tagNames: edge.sharedTagIds.flatMap((tagId) => {
          const name = tagNamesById.get(tagId);
          return name ? [name] : [];
        }),
      }));
    const adjacentByNode = new Map<string, Set<string>>(nodes.map((node) => [node.id, new Set()]));
    links.forEach((link) => {
      adjacentByNode.get(endpointId(link.source))?.add(endpointId(link.target));
      adjacentByNode.get(endpointId(link.target))?.add(endpointId(link.source));
    });
    const nodeButtons = new Map<string, HTMLButtonElement>();
    nodes.forEach((node) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "knowledge-graph-node-hit-target";
      button.setAttribute("aria-label", `${node.name} 문서 열기`);
      button.dataset.nodeId = node.id;
      nodeButtons.set(node.id, button);
    });
    nodeLayer.replaceChildren(...nodeButtons.values());

    let width = 0;
    let height = 0;
    let pixelRatio = 1;
    let frame: number | null = null;
    let hoverFrame: number | null = null;
    let hoverAnimationTimestamp: number | null = null;
    let zoomFrame: number | null = null;
    let hasRenderedFrame = false;
    let hoveredNode: GraphNode | null = null;
    let hoveredLink: GraphLink | null = null;
    const nodeHoverLevels = new Map<string, number>();
    let dragState: DragState | null = null;
    let panState: PanState | null = null;
    let colors = readColors();
    const viewport: Viewport = savedLayout ? { ...savedLayout.viewport } : { x: 0, y: 0, scale: 1 };
    let targetScale = viewport.scale;
    let zoomPoint = { x: 0, y: 0 };
    let zoomWorld = { x: 0, y: 0 };

    function readColors() {
      const styles = getComputedStyle(canvas);
      const token = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback;
      return {
        ink: token("--ink", "#20242c"),
        muted: token("--muted", "#69717d"),
        line: token("--line-strong", "#d4d8de"),
        cobalt: token("--cobalt", "#3f66c9"),
        cobaltHover: token("--cobalt-hover", "#3158b8"),
        edgeHighlight: token("--success", "#2f9765"),
        font: token("--font-ui", '"Segoe UI", sans-serif'),
      };
    }

    const requestDraw = () => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        draw();
        hasRenderedFrame = true;
      });
    };
    function draw() {
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.save();
      context.translate(viewport.x, viewport.y);
      context.scale(viewport.scale, viewport.scale);

      let focusLevel = 0;
      nodeHoverLevels.forEach((level) => { focusLevel = Math.max(focusLevel, level); });
      context.lineCap = "round";
      links.forEach((link) => {
        const source = typeof link.source === "object" ? link.source : nodeById.get(String(link.source));
        const target = typeof link.target === "object" ? link.target : nodeById.get(String(link.target));
        if (!source || !target || source.x === undefined || source.y === undefined || target.x === undefined || target.y === undefined) return;
        const activeLevel = Math.max(
          nodeHoverLevels.get(source.id) ?? 0,
          nodeHoverLevels.get(target.id) ?? 0,
        );
        const baseLineWidth = 1.15 + Math.min(0.35, link.weight * 0.08);
        context.beginPath();
        context.moveTo(source.x, source.y);
        context.lineTo(target.x, target.y);
        context.strokeStyle = colors.line;
        context.globalAlpha = lerp(0.68, 0.16, focusLevel);
        context.lineWidth = lerp(baseLineWidth, 1.65, activeLevel) / viewport.scale;
        context.stroke();
        if (activeLevel > 0.001) {
          context.strokeStyle = colors.edgeHighlight;
          context.globalAlpha = 0.95 * activeLevel;
          context.stroke();
        }
      });

      nodes.forEach((node) => {
        if (node.x === undefined || node.y === undefined) return;
        const ownLevel = nodeHoverLevels.get(node.id) ?? 0;
        let relatedLevel = ownLevel;
        adjacentByNode.get(node.id)?.forEach((adjacentId) => {
          relatedLevel = Math.max(relatedLevel, nodeHoverLevels.get(adjacentId) ?? 0);
        });
        const nodeAlpha = 1 - 0.84 * Math.max(0, focusLevel - relatedLevel);
        context.globalAlpha = nodeAlpha;
        context.beginPath();
        context.arc(node.x, node.y, node.radius * (1 + 0.2 * ownLevel), 0, Math.PI * 2);
        context.fillStyle = colors.cobalt;
        context.fill();
        if (ownLevel > 0.001) {
          context.globalAlpha = nodeAlpha * ownLevel;
          context.fillStyle = colors.cobaltHover;
          context.fill();
        }

        const showLabel = relatedLevel > 0.01 || viewport.scale >= 0.82 || node.degree >= 5;
        if (!showLabel) return;
        context.globalAlpha = clamp(0.84 - 0.74 * Math.max(0, focusLevel - relatedLevel) + 0.16 * ownLevel, 0.1, 1);
        context.fillStyle = colors.ink;
        context.font = `${graphLabelFontSize / viewport.scale}px ${colors.font}`;
        context.textBaseline = "middle";
        const label = node.name.length > 38 ? `${node.name.slice(0, 37)}…` : node.name;
        context.fillText(label, node.x + node.radius + graphLabelGap / viewport.scale, node.y);
      });

      context.restore();
      context.globalAlpha = 1;
      nodes.forEach((node) => {
        const button = nodeButtons.get(node.id);
        if (!button || node.x === undefined || node.y === undefined) return;
        const hitRadius = node.radius * viewport.scale + 6;
        const ownLevel = nodeHoverLevels.get(node.id) ?? 0;
        let relatedLevel = ownLevel;
        adjacentByNode.get(node.id)?.forEach((adjacentId) => {
          relatedLevel = Math.max(relatedLevel, nodeHoverLevels.get(adjacentId) ?? 0);
        });
        const showLabel = relatedLevel > 0.01 || viewport.scale >= 0.82 || node.degree >= 5;
        const label = node.name.length > 38 ? `${node.name.slice(0, 37)}…` : node.name;
        context.font = `${graphLabelFontSize / viewport.scale}px ${colors.font}`;
        const labelWidth = showLabel ? context.measureText(label).width * viewport.scale : 0;
        const hitWidth = showLabel ? hitRadius + node.radius * viewport.scale + 8 + labelWidth : hitRadius * 2;
        button.style.width = `${hitWidth}px`;
        button.style.height = `${hitRadius * 2}px`;
        button.style.transform = `translate(${viewport.x + node.x * viewport.scale - hitRadius}px, ${viewport.y + node.y * viewport.scale - hitRadius}px)`;
      });
    }
    drawRef.current = draw;

    const linkForce = forceLink<GraphNode, GraphLink>(links)
      .id((node) => node.id)
      .distance(forceSettings.linkDistance)
      .strength(forceSettings.linkStrength);
    const chargeForce = forceManyBody<GraphNode>().strength(-forceSettings.repulsion).distanceMin(18).distanceMax(900);
    const xForce = forceX<GraphNode>(0).strength(forceSettings.centerStrength);
    const yForce = forceY<GraphNode>(0).strength(forceSettings.centerStrength);
    const simulation = forceSimulation<GraphNode>(nodes)
      .force("link", linkForce)
      .force("charge", chargeForce)
      .force("center-x", xForce)
      .force("center-y", yForce)
      .force("collide", forceCollide<GraphNode>().radius((node) => node.radius + 7).strength(0.75).iterations(2))
      .alphaDecay(0.026)
      .velocityDecay(0.36)
      .on("tick", requestDraw)
      .on("end", () => {
        canvas.dataset.forceState = "settled";
        requestDraw();
      });
    simulationRef.current = simulation;
    forceRefs.current = { link: linkForce, charge: chargeForce, x: xForce, y: yForce };
    canvas.dataset.forceState = "running";

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const restoresCompleteLayout = savedLayout?.graphSignature === graphSignature
      && nodes.every((node) => savedLayout.nodePositions.has(node.id));
    canvas.dataset.layoutRestored = restoresCompleteLayout ? "true" : "false";
    if (restoresCompleteLayout) {
      simulation.alpha(0).stop();
      canvas.dataset.forceState = "settled";
    } else if (reducedMotion) {
      simulation.stop().tick(180);
      canvas.dataset.forceState = "settled";
    }

    const animateHover = (timestamp: number) => {
      const delta = hoverAnimationTimestamp === null ? 16 : clamp(timestamp - hoverAnimationTimestamp, 0, hoverTransitionDuration);
      hoverAnimationTimestamp = timestamp;
      const blend = 1 - Math.exp((-5 * delta) / hoverTransitionDuration);
      let unsettled = false;
      nodes.forEach((node) => {
        const target = node === hoveredNode ? 1 : 0;
        const current = nodeHoverLevels.get(node.id) ?? 0;
        let next = current + (target - current) * blend;
        if (Math.abs(target - next) < 0.01) next = target;
        else unsettled = true;
        if (next > 0) nodeHoverLevels.set(node.id, next);
        else nodeHoverLevels.delete(node.id);
      });
      requestDraw();
      if (unsettled) hoverFrame = requestAnimationFrame(animateHover);
      else {
        hoverFrame = null;
        hoverAnimationTimestamp = null;
      }
    };

    function requestHoverTransition() {
      if (reducedMotion) {
        nodeHoverLevels.clear();
        if (hoveredNode) nodeHoverLevels.set(hoveredNode.id, 1);
        requestDraw();
        return;
      }
      if (hoverFrame === null) {
        hoverAnimationTimestamp = null;
        hoverFrame = requestAnimationFrame(animateHover);
      }
    }

    function setHoveredNode(node: GraphNode | null) {
      if (node === hoveredNode) return;
      hoveredNode = node;
      requestHoverTransition();
    }

    function canvasPoint(event: PointerEvent | WheelEvent) {
      const bounds = canvas.getBoundingClientRect();
      return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    }

    function worldPoint(point: { x: number; y: number }) {
      return { x: (point.x - viewport.x) / viewport.scale, y: (point.y - viewport.y) / viewport.scale };
    }

    function findNode(point: { x: number; y: number }) {
      const world = worldPoint(point);
      for (let index = nodes.length - 1; index >= 0; index -= 1) {
        const node = nodes[index];
        if (node.x === undefined || node.y === undefined) continue;
        const hitRadius = node.radius + 6 / viewport.scale;
        if ((world.x - node.x) ** 2 + (world.y - node.y) ** 2 <= hitRadius ** 2) return node;
      }
      return null;
    }

    function findLink(point: { x: number; y: number }) {
      for (let index = links.length - 1; index >= 0; index -= 1) {
        const link = links[index];
        const source = typeof link.source === "object" ? link.source : nodeById.get(String(link.source));
        const target = typeof link.target === "object" ? link.target : nodeById.get(String(link.target));
        if (!source || !target || source.x === undefined || source.y === undefined || target.x === undefined || target.y === undefined) continue;
        const start = { x: viewport.x + source.x * viewport.scale, y: viewport.y + source.y * viewport.scale };
        const end = { x: viewport.x + target.x * viewport.scale, y: viewport.y + target.y * viewport.scale };
        if (distanceToSegment(point, start, end) <= edgeHitRadius) return link;
      }
      return null;
    }

    function hideTooltip() {
      if (tooltip) tooltip.hidden = true;
    }

    function showLinkTooltip(link: GraphLink, point: { x: number; y: number }) {
      if (!tooltip || !link.tagNames.length) {
        hideTooltip();
        return;
      }
      tooltip.textContent = link.tagNames.map((name) => `#${name}`).join("\n");
      tooltip.hidden = false;
      const left = clamp(point.x + 12, 8, Math.max(8, width - tooltip.offsetWidth - 8));
      const top = clamp(point.y + 12, 8, Math.max(8, height - tooltip.offsetHeight - 8));
      tooltip.style.transform = `translate(${left}px, ${top}px)`;
    }

    function heatSimulation(alpha = 0.28) {
      canvas.dataset.forceState = "running";
      simulation.alphaTarget(alpha);
      if (reducedMotion) {
        simulation.stop().alpha(alpha).tick(8);
        requestDraw();
      } else {
        simulation.restart();
      }
    }

    function releaseNode(node: GraphNode) {
      node.fx = null;
      node.fy = null;
      simulation.alphaTarget(0);
      if (reducedMotion) {
        simulation.stop().alpha(0.18).tick(70);
        canvas.dataset.forceState = "settled";
        requestDraw();
      }
    }

    const onPointerDown = (event: PointerEvent, forcedNode: GraphNode | null = null, captureTarget: Element = canvas) => {
      if (event.button !== 0) return;
      if (zoomFrame !== null) {
        cancelAnimationFrame(zoomFrame);
        zoomFrame = null;
        targetScale = viewport.scale;
      }
      hideTooltip();
      hoveredLink = null;
      const point = canvasPoint(event);
      const node = forcedNode ?? findNode(point);
      captureTarget.setPointerCapture(event.pointerId);
      if (node) {
        node.fx = node.x;
        node.fy = node.y;
        dragState = { node, captureTarget, pointerId: event.pointerId, startX: point.x, startY: point.y, moved: false };
        setHoveredNode(node);
        heatSimulation();
      } else {
        setHoveredNode(null);
        panState = { captureTarget, pointerId: event.pointerId, startX: point.x, startY: point.y, originX: viewport.x, originY: viewport.y };
      }
      requestDraw();
    };

    const onPointerMove = (event: PointerEvent) => {
      const point = canvasPoint(event);
      if (dragState?.pointerId === event.pointerId) {
        const world = worldPoint(point);
        dragState.node.fx = world.x;
        dragState.node.fy = world.y;
        dragState.moved ||= Math.hypot(point.x - dragState.startX, point.y - dragState.startY) > 4;
        if (reducedMotion) simulation.tick(2);
        requestDraw();
        return;
      }
      if (panState?.pointerId === event.pointerId) {
        viewport.x = panState.originX + point.x - panState.startX;
        viewport.y = panState.originY + point.y - panState.startY;
        requestDraw();
        return;
      }
      const nextHoveredNode = findNode(point);
      const nextHoveredLink = nextHoveredNode ? null : findLink(point);
      if (nextHoveredNode !== hoveredNode || nextHoveredLink !== hoveredLink) {
        setHoveredNode(nextHoveredNode);
        hoveredLink = nextHoveredLink;
        canvas.style.cursor = hoveredNode ? "grab" : "move";
        if (hoveredLink) showLinkTooltip(hoveredLink, point);
        else hideTooltip();
        requestDraw();
      } else if (hoveredLink) {
        showLinkTooltip(hoveredLink, point);
      }
    };

    const finishPointer = (event: PointerEvent, openDocument: boolean) => {
      const captureTarget = dragState?.captureTarget ?? panState?.captureTarget ?? canvas;
      let documentToOpen: GraphNode | null = null;
      if (dragState?.pointerId === event.pointerId) {
        const completedDrag = dragState;
        releaseNode(completedDrag.node);
        dragState = null;
        if (openDocument && !completedDrag.moved) documentToOpen = completedDrag.node;
      }
      if (panState?.pointerId === event.pointerId) panState = null;
      const nextHoveredNode = findNode(canvasPoint(event));
      setHoveredNode(nextHoveredNode);
      hoveredLink = nextHoveredNode ? null : findLink(canvasPoint(event));
      canvas.style.cursor = hoveredNode ? "grab" : "move";
      if (hoveredLink) showLinkTooltip(hoveredLink, canvasPoint(event));
      else hideTooltip();
      requestDraw();
      if (captureTarget.hasPointerCapture(event.pointerId)) captureTarget.releasePointerCapture(event.pointerId);
      if (documentToOpen) onSelectDocumentRef.current(documentToOpen.id);
    };

    const animateZoom = () => {
      const scaleRatio = targetScale / viewport.scale;
      const settled = Math.abs(Math.log(scaleRatio)) < 0.001;
      const nextScale = settled ? targetScale : viewport.scale * Math.exp(Math.log(scaleRatio) * 0.24);
      viewport.scale = nextScale;
      viewport.x = zoomPoint.x - zoomWorld.x * nextScale;
      viewport.y = zoomPoint.y - zoomWorld.y * nextScale;
      canvas.dataset.zoomScale = nextScale.toFixed(4);
      requestDraw();
      if (settled) {
        zoomFrame = null;
        return;
      }
      zoomFrame = requestAnimationFrame(animateZoom);
    };

    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      hideTooltip();
      hoveredLink = null;
      const point = canvasPoint(event);
      const deltaMultiplier = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? height : 1;
      const normalizedDelta = clamp(event.deltaY * deltaMultiplier, -120, 120);
      zoomPoint = point;
      zoomWorld = worldPoint(point);
      targetScale = clamp(targetScale * Math.exp(-normalizedDelta * 0.0015), 0.28, 3.5);
      if (reducedMotion) {
        viewport.scale = targetScale;
        viewport.x = point.x - zoomWorld.x * targetScale;
        viewport.y = point.y - zoomWorld.y * targetScale;
        canvas.dataset.zoomScale = targetScale.toFixed(4);
        requestDraw();
      } else if (zoomFrame === null) {
        zoomFrame = requestAnimationFrame(animateZoom);
      }
    };

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      const nextWidth = Math.max(1, Math.round(bounds.width));
      const nextHeight = Math.max(1, Math.round(bounds.height));
      const previousWidth = width;
      const previousHeight = height;
      width = nextWidth;
      height = nextHeight;
      pixelRatio = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
      if (previousWidth === 0 || previousHeight === 0) {
        if (savedLayout) {
          viewport.x += (width - savedLayout.width) / 2;
          viewport.y += (height - savedLayout.height) / 2;
        } else {
          viewport.x = width / 2;
          viewport.y = height / 2;
        }
      } else {
        viewport.x += (width - previousWidth) / 2;
        viewport.y += (height - previousHeight) / 2;
      }
      colors = readColors();
      requestDraw();
    };

    const onPointerUp = (event: PointerEvent) => finishPointer(event, true);
    const onPointerCancel = (event: PointerEvent) => finishPointer(event, false);
    const onPointerLeave = () => {
      if (dragState || panState || (!hoveredNode && !hoveredLink)) return;
      setHoveredNode(null);
      hoveredLink = null;
      hideTooltip();
      canvas.style.cursor = "move";
      requestDraw();
    };
    const nodeButtonCleanups: Array<() => void> = [];
    nodeButtons.forEach((button, nodeId) => {
      const node = nodeById.get(nodeId);
      if (!node) return;
      const onNodePointerDown = (event: PointerEvent) => onPointerDown(event, node, button);
      const onNodePointerEnter = () => {
        setHoveredNode(node);
        hoveredLink = null;
        hideTooltip();
        requestDraw();
      };
      const onNodePointerLeave = () => {
        if (dragState?.node === node) return;
        setHoveredNode(null);
      };
      const onNodeKeyboardClick = (event: MouseEvent) => {
        if (event.detail === 0) onSelectDocumentRef.current(node.id);
      };
      button.addEventListener("pointerdown", onNodePointerDown);
      button.addEventListener("pointermove", onPointerMove);
      button.addEventListener("pointerup", onPointerUp);
      button.addEventListener("pointercancel", onPointerCancel);
      button.addEventListener("pointerenter", onNodePointerEnter);
      button.addEventListener("pointerleave", onNodePointerLeave);
      button.addEventListener("click", onNodeKeyboardClick);
      nodeButtonCleanups.push(() => {
        button.removeEventListener("pointerdown", onNodePointerDown);
        button.removeEventListener("pointermove", onPointerMove);
        button.removeEventListener("pointerup", onPointerUp);
        button.removeEventListener("pointercancel", onPointerCancel);
        button.removeEventListener("pointerenter", onNodePointerEnter);
        button.removeEventListener("pointerleave", onNodePointerLeave);
        button.removeEventListener("click", onNodeKeyboardClick);
      });
    });
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointercancel", onPointerCancel);
    canvas.addEventListener("pointerleave", onPointerLeave);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    nodeLayer.addEventListener("wheel", onWheel, { passive: false });
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    const shell = canvas.closest(".app-shell");
    const themeObserver = new MutationObserver(() => {
      colors = readColors();
      requestDraw();
    });
    if (shell) themeObserver.observe(shell, { attributes: true, attributeFilter: ["class"] });
    resize();
    requestDraw();

    return () => {
      if (hasRenderedFrame) {
        graphLayouts.set(layoutKey, {
          graphSignature,
          nodePositions: new Map(nodes.flatMap((node) => node.x !== undefined && node.y !== undefined ? [[node.id, { x: node.x, y: node.y }] as const] : [])),
          viewport: { ...viewport },
          width,
          height,
        });
      }
      simulation.stop();
      simulationRef.current = null;
      forceRefs.current = null;
      resizeObserver.disconnect();
      themeObserver.disconnect();
      nodeButtonCleanups.forEach((cleanup) => cleanup());
      nodeLayer.replaceChildren();
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerCancel);
      canvas.removeEventListener("pointerleave", onPointerLeave);
      canvas.removeEventListener("wheel", onWheel);
      nodeLayer.removeEventListener("wheel", onWheel);
      if (frame !== null) cancelAnimationFrame(frame);
      if (hoverFrame !== null) cancelAnimationFrame(hoverFrame);
      if (zoomFrame !== null) cancelAnimationFrame(zoomFrame);
    };
  }, [graph, layoutKey]);

  const updateForce = (key: keyof ForceSettings, value: number) => setForceSettings((current) => ({ ...current, [key]: value }));

  if (!graph.nodes.length) return <div className="knowledge-empty-graph"><GitBranch size={28} /><p>연결할 문서가 아직 없습니다.</p></div>;
  return <div className="knowledge-graph-canvas">
    <canvas ref={canvasRef} data-force-engine="d3" role="img" aria-label="공통 태그로 연결된 문서 그래프" />
    <div ref={nodeLayerRef} className="knowledge-graph-node-layer" aria-label="지식 문서 노드" />
    <div ref={tooltipRef} className="knowledge-graph-edge-tooltip" role="tooltip" hidden />
    <button className="knowledge-graph-force-trigger" type="button" aria-label="그래프 장력 설정" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((open) => !open)}><SlidersHorizontal size={15} /></button>
    {settingsOpen && <section className="knowledge-graph-force-panel" aria-label="그래프 장력 설정">
      <header><strong>장력</strong><span><button type="button" aria-label="장력 기본값 복원" onClick={() => setForceSettings(defaultForceSettings)}><RotateCcw size={13} /></button><button type="button" aria-label="장력 설정 닫기" onClick={() => setSettingsOpen(false)}><X size={14} /></button></span></header>
      <ForceControl label="중심 장력" value={forceSettings.centerStrength} minimum={0.002} maximum={0.08} step={0.002} onChange={(value) => updateForce("centerStrength", value)} />
      <ForceControl label="반발력" value={forceSettings.repulsion} minimum={20} maximum={500} step={5} onChange={(value) => updateForce("repulsion", value)} />
      <ForceControl label="링크 장력" value={forceSettings.linkStrength} minimum={0.02} maximum={1} step={0.02} onChange={(value) => updateForce("linkStrength", value)} />
      <ForceControl label="링크 거리" value={forceSettings.linkDistance} minimum={30} maximum={220} step={2} onChange={(value) => updateForce("linkDistance", value)} />
    </section>}
  </div>;
}

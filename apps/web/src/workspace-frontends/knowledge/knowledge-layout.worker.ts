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

interface LayoutNode extends SimulationNodeDatum {
  id: string;
  radius: number;
}

interface LayoutLink extends SimulationLinkDatum<LayoutNode> {
  source: string | LayoutNode;
  target: string | LayoutNode;
}

interface ForceSettings {
  centerStrength: number;
  repulsion: number;
  linkStrength: number;
  linkDistance: number;
}

type WorkerRequest =
  | { type: "init"; nodes: LayoutNode[]; links: Array<{ source: string; target: string }>; settings: ForceSettings; reducedMotion: boolean; settled?: boolean }
  | { type: "settings"; settings: ForceSettings }
  | { type: "heat"; alpha: number }
  | { type: "pin"; nodeId: string; x: number; y: number }
  | { type: "release"; nodeId: string }
  | { type: "stop" };

let nodes: LayoutNode[] = [];
let nodesById = new Map<string, LayoutNode>();
let simulation: Simulation<LayoutNode, LayoutLink> | null = null;
let forces: {
  link: ForceLink<LayoutNode, LayoutLink>;
  charge: ForceManyBody<LayoutNode>;
  x: ForceX<LayoutNode>;
  y: ForceY<LayoutNode>;
} | null = null;
let reducedMotion = false;
let lastPublishedAt = 0;

function publish(state: "running" | "settled", force = false) {
  const now = performance.now();
  if (!force && state === "running" && now - lastPublishedAt < 32) return;
  lastPublishedAt = now;
  const positions = new Float32Array(nodes.length * 2);
  nodes.forEach((node, index) => {
    positions[index * 2] = node.x ?? 0;
    positions[index * 2 + 1] = node.y ?? 0;
  });
  self.postMessage({ type: "positions", state, positions: positions.buffer }, [positions.buffer]);
}

function applySettings(settings: ForceSettings) {
  if (!simulation || !forces) return;
  forces.x.strength(settings.centerStrength);
  forces.y.strength(settings.centerStrength);
  forces.charge.strength(-settings.repulsion);
  forces.link.strength(settings.linkStrength).distance(settings.linkDistance);
  simulation.alpha(0.55).alphaTarget(0);
  if (reducedMotion) {
    simulation.stop().tick(90);
    publish("settled", true);
  } else {
    simulation.restart();
  }
}

function initialize(request: Extract<WorkerRequest, { type: "init" }>) {
  simulation?.stop();
  nodes = request.nodes.map((node) => ({ ...node }));
  nodesById = new Map(nodes.map((node) => [node.id, node]));
  reducedMotion = request.reducedMotion;
  const links: LayoutLink[] = request.links.map((link) => ({ ...link }));
  const link = forceLink<LayoutNode, LayoutLink>(links)
    .id((node) => node.id)
    .distance(request.settings.linkDistance)
    .strength(request.settings.linkStrength);
  const charge = forceManyBody<LayoutNode>()
    .strength(-request.settings.repulsion)
    .distanceMin(18)
    .distanceMax(900);
  const x = forceX<LayoutNode>(0).strength(request.settings.centerStrength);
  const y = forceY<LayoutNode>(0).strength(request.settings.centerStrength);
  forces = { link, charge, x, y };
  simulation = forceSimulation<LayoutNode>(nodes)
    .force("link", link)
    .force("charge", charge)
    .force("center-x", x)
    .force("center-y", y)
    .force("collide", forceCollide<LayoutNode>().radius((node) => node.radius + 7).strength(0.75).iterations(2))
    .alphaDecay(0.026)
    .velocityDecay(0.36)
    .on("tick", () => publish("running"))
    .on("end", () => publish("settled", true));
  if (request.settled) {
    simulation.alpha(0).stop();
    publish("settled", true);
  } else if (reducedMotion) {
    simulation.stop().tick(180);
    publish("settled", true);
  } else {
    publish("running", true);
  }
}

self.addEventListener("message", (event: MessageEvent<WorkerRequest>) => {
  const request = event.data;
  if (request.type === "init") {
    initialize(request);
    return;
  }
  if (request.type === "stop") {
    simulation?.stop();
    simulation = null;
    forces = null;
    nodes = [];
    nodesById.clear();
    return;
  }
  if (!simulation) return;
  if (request.type === "settings") {
    applySettings(request.settings);
    return;
  }
  if (request.type === "heat") {
    const alpha = Math.max(simulation.alpha(), request.alpha);
    simulation.alpha(alpha).alphaTarget(request.alpha);
    if (reducedMotion) {
      simulation.stop().tick(8);
      publish("settled", true);
    } else {
      simulation.restart();
    }
    return;
  }
  const node = nodesById.get(request.nodeId);
  if (!node) return;
  if (request.type === "pin") {
    node.x = request.x;
    node.y = request.y;
    node.fx = request.x;
    node.fy = request.y;
    simulation.alpha(Math.max(simulation.alpha(), 0.28)).alphaTarget(0.28);
    if (reducedMotion) {
      simulation.stop().tick(2);
      publish("running", true);
    } else {
      simulation.restart();
    }
    return;
  }
  node.fx = null;
  node.fy = null;
  simulation.alphaTarget(0);
  if (reducedMotion) {
    simulation.stop().alpha(0.18).tick(70);
    publish("settled", true);
  } else {
    simulation.restart();
  }
});

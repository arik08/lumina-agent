from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy.orm import Session

from ..models import utc_now
from .models import (
    DeepAnalysisMission,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowRevision,
)


MAX_WORKFLOW_NODES = 14
MAX_REPLANS = 4
MAX_ADDED_NODES_PER_DECISION = 4

_DECISION_PATTERN = re.compile(
    r"<!--\s*LUMINA_WORKFLOW_DECISION\s*(\{.*?\})\s*-->",
    re.IGNORECASE | re.DOTALL,
)
_ALLOWED_ACTIONS = {"continue", "expand", "shrink", "replace", "finish"}
_ALLOWED_NODE_TYPES = {
    "data_check",
    "research",
    "analysis",
    "validation",
    "synthesis",
}


@dataclass(frozen=True, slots=True)
class PlannedNode:
    key: str
    node_type: str
    title: str
    purpose: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InitialWorkflowPlan:
    kind: str
    reason: str
    nodes: tuple[PlannedNode, ...]


def initial_workflow_plan(title: str, objective: str) -> InitialWorkflowPlan:
    question = f"{title} {objective}".lower()
    if any(
        token in question
        for token in (
            "원가",
            "비용",
            "매출",
            "수익",
            "변동",
            "증감",
            "기여도",
            "kpi",
            "csv",
            "xlsx",
            "정량",
        )
    ):
        return InitialWorkflowPlan(
            kind="quantitative",
            reason="질문에서 정량 변동·기여도 분석 신호를 확인해 분해와 원인 검증을 병렬화한 초기안을 구성했습니다.",
            nodes=(
                PlannedNode(
                    "N001",
                    "scope",
                    "질문·측정기준 설계",
                    "질문을 측정 가능한 지표, 비교 기준, 기간과 완료 조건으로 바꾸고 이후 Workflow가 적절한지 평가합니다.",
                ),
                PlannedNode(
                    "N010",
                    "data_check",
                    "자료·품질 진단",
                    "필요한 수치 자료의 범위, 단위, 누락, 중복과 정합성을 확인합니다.",
                    ("N001",),
                ),
                PlannedNode(
                    "N020",
                    "analysis",
                    "변동·기여도 분해",
                    "기준 대비 증감을 재현 가능한 계산으로 분해하고 항목별 기여도를 산출합니다.",
                    ("N010",),
                ),
                PlannedNode(
                    "N025",
                    "analysis",
                    "업무 원인 가설 분석",
                    "수치 변동을 설명할 가격·물량·믹스·효율·외부요인 가설을 근거와 연결합니다.",
                    ("N010",),
                ),
                PlannedNode(
                    "N030",
                    "validation",
                    "교차검증·대안설명 점검",
                    "정량 분해와 업무 가설을 대조하고 반대 근거와 대안 설명을 검증합니다.",
                    ("N020", "N025"),
                ),
                PlannedNode(
                    "N035",
                    "synthesis",
                    "핵심 원인 합성",
                    "확실한 원인, 조건부 원인과 미확인 항목을 중요도순으로 합성합니다.",
                    ("N030",),
                ),
                PlannedNode(
                    "N040",
                    "report",
                    "최종 보고서",
                    "결론, 정량 근거, 한계, 권고 조치와 후속 확인 항목을 보고서로 정리합니다.",
                    ("N035",),
                ),
            ),
        )
    if any(
        token in question
        for token in ("비교", "벤치마크", "시장", "경쟁", "동향", "조사", "사례", "리서치")
    ) and not any(
        token in question
        for token in ("전략", "투자", "도입", "선택", "의사결정", "정책", "리스크", "사업성")
    ):
        return InitialWorkflowPlan(
            kind="comparative_research",
            reason="비교·조사형 질문으로 판단해 자료 수집과 비교 기준 점검을 분기하고, 비교 분석과 반대 관점을 다시 합류시키는 초기안을 구성했습니다.",
            nodes=(
                PlannedNode("N001", "scope", "조사 질문·비교축 설계", "대상, 기간, 비교 기준과 판단 조건을 확정하고 Workflow 적합성을 평가합니다."),
                PlannedNode("N010", "research", "근거·사례 수집", "Project 자료와 사용 가능한 출처에서 비교 가능한 근거와 사례를 수집합니다.", ("N001",)),
                PlannedNode("N015", "validation", "비교 기준·출처 점검", "비교축의 공정성, 출처 신뢰도와 시점 차이를 독립적으로 점검합니다.", ("N001",)),
                PlannedNode("N020", "analysis", "비교 대상별 분석", "수집 자료와 검증된 비교축을 함께 사용해 대상별 차이와 맥락을 분석합니다.", ("N010", "N015")),
                PlannedNode("N025", "analysis", "반대 관점·예외 분석", "주요 해석을 뒤집을 수 있는 반례, 누락 관점과 적용 예외를 별도로 분석합니다.", ("N010", "N015")),
                PlannedNode("N030", "synthesis", "비교 결과 교차 합성", "주 분석과 반대 관점을 교차검증하여 공통점, 차이, 시사점과 불확실성을 합성합니다.", ("N020", "N025")),
                PlannedNode("N040", "report", "최종 보고서", "비교 결과, 근거, 반대 관점, 한계와 적용 시사점을 보고서로 정리합니다.", ("N030",)),
            ),
        )
    if any(
        token in question
        for token in ("전략", "투자", "도입", "선택", "의사결정", "정책", "리스크", "사업성")
    ):
        return InitialWorkflowPlan(
            kind="decision",
            reason="의사결정형 질문으로 판단해 선택지, 평가 기준, 위험과 실행조건을 분리한 초기안을 구성했습니다.",
            nodes=(
                PlannedNode("N001", "scope", "의사결정 문제 정의", "결정해야 할 사항, 제약, 이해관계자와 성공 기준을 확정하고 Workflow 적합성을 평가합니다."),
                PlannedNode("N010", "research", "현황·선택지 파악", "현재 상태와 가능한 선택지를 근거와 함께 정리합니다.", ("N001",)),
                PlannedNode("N020", "analysis", "대안 가치 분석", "대안별 기대효과, 비용과 실행 가능성을 동일한 기준으로 분석합니다.", ("N010",)),
                PlannedNode("N025", "analysis", "위험·민감도 분석", "핵심 위험, 실패 조건과 결론을 바꾸는 민감 요인을 분석합니다.", ("N010",)),
                PlannedNode("N030", "validation", "대안 교차검증", "가정과 반대 근거를 검토하고 대안 간 트레이드오프를 확인합니다.", ("N020", "N025")),
                PlannedNode("N035", "synthesis", "권고안·실행조건 합성", "권고안과 선택 조건, 선행 조치와 중단 기준을 합성합니다.", ("N030",)),
                PlannedNode("N040", "report", "최종 보고서", "의사결정안, 근거, 위험, 실행 로드맵과 후속 확인 항목을 정리합니다.", ("N035",)),
            ),
        )
    return InitialWorkflowPlan(
        kind="open_analysis",
        reason="비정형 질문으로 판단해 핵심 가설과 대안 가설을 분리 탐색한 뒤 검증에서 합류하는 최소 Workflow를 구성했습니다.",
        nodes=(
            PlannedNode("N001", "scope", "질문·범위 설계", "질문을 검증 가능한 하위 질문으로 나누고 필요한 Workflow를 평가합니다."),
            PlannedNode("N010", "data_check", "근거·자료 진단", "사용 가능한 자료와 부족한 근거를 구분합니다.", ("N001",)),
            PlannedNode("N020", "analysis", "핵심 가설 분석", "확인된 근거로 가장 유력한 가설과 설명을 분석합니다.", ("N010",)),
            PlannedNode("N025", "analysis", "대안 가설·반례 분석", "핵심 설명과 경쟁하는 대안 가설, 반례와 누락 변수를 독립적으로 분석합니다.", ("N010",)),
            PlannedNode("N030", "synthesis", "교차검증·합성", "핵심 가설과 대안 가설을 함께 검증하여 결론, 불확실성과 한계를 합성합니다.", ("N020", "N025")),
            PlannedNode("N040", "report", "최종 보고서", "결론, 근거, 대안 설명, 한계와 후속 조치를 보고서로 정리합니다.", ("N030",)),
        ),
    )


def plan_edges(plan: InitialWorkflowPlan) -> list[tuple[str, str]]:
    return [
        (dependency, node.key)
        for node in plan.nodes
        for dependency in node.depends_on
    ]


def planned_positions(plan: InitialWorkflowPlan) -> dict[str, tuple[int, int, int]]:
    level: dict[str, int] = {}
    for node in plan.nodes:
        level[node.key] = (
            max((level.get(dependency, 0) for dependency in node.depends_on), default=-1)
            + 1
        )
    groups: dict[int, list[PlannedNode]] = {}
    for node in plan.nodes:
        groups.setdefault(level[node.key], []).append(node)
    max_rows = max((len(group) for group in groups.values()), default=1)
    positions: dict[str, tuple[int, int, int]] = {}
    sequence = 0
    for column in sorted(groups):
        group = groups[column]
        height = (len(group) - 1) * 130
        top = 180 + ((max_rows - 1) * 130 - height) // 2
        for row, node in enumerate(group):
            positions[node.key] = (80 + column * 220, top + row * 130, sequence)
            sequence += 1
    return positions


def graph_digest(
    nodes: Iterable[DeepAnalysisWorkflowNode | PlannedNode],
    edges: Iterable[DeepAnalysisWorkflowEdge | tuple[str, str]],
) -> str:
    node_payload = []
    for node in nodes:
        key = node.node_key if isinstance(node, DeepAnalysisWorkflowNode) else node.key
        node_payload.append(
            {
                "key": key,
                "type": node.node_type,
                "title": node.title,
                "purpose": node.purpose,
            }
        )
    edge_payload = []
    for edge in edges:
        if isinstance(edge, DeepAnalysisWorkflowEdge):
            edge_payload.append((edge.source_node_key, edge.target_node_key))
        else:
            edge_payload.append(edge)
    canonical = json.dumps(
        {"nodes": sorted(node_payload, key=lambda item: item["key"]), "edges": sorted(edge_payload)},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _snapshot(
    nodes: Iterable[DeepAnalysisWorkflowNode],
    edges: Iterable[DeepAnalysisWorkflowEdge],
) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "nodeKey": node.node_key,
                "nodeType": node.node_type,
                "title": node.title,
                "purpose": node.purpose,
                "status": node.status,
                "sequence": node.sequence,
            }
            for node in sorted(nodes, key=lambda item: item.sequence)
        ],
        "edges": [
            {"source": edge.source_node_key, "target": edge.target_node_key}
            for edge in sorted(
                edges, key=lambda item: (item.source_node_key, item.target_node_key)
            )
        ],
    }


def initial_change_log(plan: InitialWorkflowPlan) -> list[dict[str, Any]]:
    snapshot = {
        "nodes": [
            {
                "nodeKey": node.key,
                "nodeType": node.node_type,
                "title": node.title,
                "purpose": node.purpose,
                "status": "ready" if index == 0 else "planned",
                "sequence": index,
            }
            for index, node in enumerate(plan.nodes)
        ],
        "edges": [
            {"source": source, "target": target}
            for source, target in plan_edges(plan)
        ],
    }
    return [
        {
            "revision": 1,
            "action": "initial",
            "reason": plan.reason,
            "graphChanged": True,
            "createdAt": utc_now().isoformat(),
            "before": None,
            "after": snapshot,
        }
    ]


def _topological_order(
    nodes: list[DeepAnalysisWorkflowNode], edges: list[DeepAnalysisWorkflowEdge]
) -> tuple[list[DeepAnalysisWorkflowNode], dict[str, int]]:
    by_key = {node.node_key: node for node in nodes}
    incoming = {key: 0 for key in by_key}
    outgoing: dict[str, list[str]] = {key: [] for key in by_key}
    for edge in edges:
        if edge.source_node_key not in by_key or edge.target_node_key not in by_key:
            continue
        incoming[edge.target_node_key] += 1
        outgoing[edge.source_node_key].append(edge.target_node_key)
    ready = sorted(
        (key for key, count in incoming.items() if count == 0),
        key=lambda key: (by_key[key].sequence, key),
    )
    ordered: list[DeepAnalysisWorkflowNode] = []
    level = {key: 0 for key in by_key}
    while ready:
        key = ready.pop(0)
        ordered.append(by_key[key])
        for target in sorted(outgoing[key]):
            level[target] = max(level[target], level[key] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
                ready.sort(key=lambda item: (by_key[item].sequence, item))
    if len(ordered) != len(nodes):
        raise ValueError("Workflow 변경으로 순환 의존성이 생겼습니다.")
    return ordered, level


def layout_workflow(
    nodes: list[DeepAnalysisWorkflowNode], edges: list[DeepAnalysisWorkflowEdge]
) -> None:
    ordered, level = _topological_order(nodes, edges)
    groups: dict[int, list[DeepAnalysisWorkflowNode]] = {}
    for sequence, node in enumerate(ordered):
        node.sequence = sequence
        groups.setdefault(level[node.node_key], []).append(node)
    max_rows = max((len(group) for group in groups.values()), default=1)
    for column, group in groups.items():
        height = (len(group) - 1) * 130
        top = 180 + ((max_rows - 1) * 130 - height) // 2
        for row, node in enumerate(group):
            node.position_x = 80 + column * 220
            node.position_y = top + row * 130


def adaptive_decision_instruction(
    node: DeepAnalysisWorkflowNode,
    nodes: list[DeepAnalysisWorkflowNode],
    revision: DeepAnalysisWorkflowRevision,
) -> str:
    if node.node_type == "report":
        return ""
    pending = [
        f"{item.node_key}:{item.title}"
        for item in nodes
        if item.status in {"planned", "ready"}
    ]
    replans = sum(
        1
        for item in revision.change_log_json
        if isinstance(item, dict) and item.get("graphChanged") and item.get("action") != "initial"
    )
    return f"""

Workflow 적응 판단:
- 현재 결과를 바탕으로 남은 Workflow가 충분한지 반드시 평가하십시오.
- 남은 Node: {', '.join(pending) if pending else '없음'}
- 이미 적용된 그래프 재계획: {replans}/{MAX_REPLANS}회
- 근거가 부족하거나 별도 전문 분석이 필요하면 expand, 불필요한 예정 Node가 있으면 shrink, 예정 단계를 다른 분석으로 바꿔야 하면 replace, 바로 최종 합성이 가능하면 finish를 선택하십시오.
- 단순히 예정대로 진행해도 충분하면 continue를 선택하십시오.
- 서로 독립적으로 검증해야 하는 가설·지역·제품·관점은 한 줄로 연결하지 말고 같은 선행 Node에서 분기하십시오.
- 분기 결과를 함께 판단해야 하면 별도 검증·합성 Node를 추가하고 그 Node의 dependsOn에 모든 분기 ref를 지정해 다시 합류시키십시오.
- add의 ref는 이번 판단 안에서만 쓰는 짧은 식별자입니다. dependsOn은 current 또는 앞서 선언한 ref만 사용할 수 있으며, 생략하면 current에서 분기합니다.
- 추가 Node는 최대 {MAX_ADDED_NODES_PER_DECISION}개이며 보고서 Node를 직접 추가하지 마십시오.
- Markdown 본문 맨 끝에 아래 형식의 HTML 주석을 정확히 하나 추가하십시오. 이 주석은 문서 저장 전에 분리됩니다.
<!-- LUMINA_WORKFLOW_DECISION
{{"action":"continue|expand|shrink|replace|finish","reason":"판단 근거","confidence":0.0,"add":[{{"ref":"causeA","title":"원인 A 분석","purpose":"독립적으로 검증할 내용","nodeType":"analysis","dependsOn":["current"]}},{{"ref":"causeB","title":"원인 B 분석","purpose":"독립적으로 검증할 내용","nodeType":"analysis","dependsOn":["current"]}},{{"ref":"merge","title":"원인 교차검증","purpose":"두 분석 결과를 함께 검증","nodeType":"validation","dependsOn":["causeA","causeB"]}}],"remove":["N020"]}}
-->
"""


def extract_workflow_decision(markdown: str) -> tuple[str, dict[str, Any]]:
    match = _DECISION_PATTERN.search(markdown)
    clean = _DECISION_PATTERN.sub("", markdown).rstrip()
    if match is None:
        return clean, {
            "action": "continue",
            "reason": "구조화된 Workflow 변경 요청이 없어 기존 계획을 유지했습니다.",
            "confidence": None,
            "add": [],
            "remove": [],
        }
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError:
        return clean, {
            "action": "continue",
            "reason": "Workflow 변경 제어값을 해석할 수 없어 안전하게 기존 계획을 유지했습니다.",
            "confidence": None,
            "add": [],
            "remove": [],
        }
    action = str(raw.get("action") or "continue").lower()
    if action not in _ALLOWED_ACTIONS:
        action = "continue"
    reason = str(raw.get("reason") or "판단 근거가 제공되지 않았습니다.").strip()[:1000]
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence"))))
    except (TypeError, ValueError):
        confidence = None
    additions = []
    seen_refs: set[str] = set()
    for item in raw.get("add", []) if isinstance(raw.get("add"), list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:240]
        purpose = str(item.get("purpose") or "").strip()[:2000]
        node_type = str(item.get("nodeType") or "analysis").strip().lower()
        if title and purpose:
            raw_ref = str(item.get("ref") or f"A{len(additions) + 1}")
            ref = re.sub(r"[^A-Za-z0-9_-]", "", raw_ref)[:32]
            if not ref or ref in seen_refs or ref.lower() == "current":
                ref = f"A{len(additions) + 1}"
            raw_dependencies = (
                item.get("dependsOn") if isinstance(item.get("dependsOn"), list) else []
            )
            dependencies = []
            for dependency in raw_dependencies:
                candidate = str(dependency)[:32]
                if candidate == "current" or candidate in seen_refs:
                    if candidate not in dependencies:
                        dependencies.append(candidate)
            if not dependencies:
                dependencies = ["current"]
            additions.append(
                {
                    "ref": ref,
                    "title": title,
                    "purpose": purpose,
                    "nodeType": node_type if node_type in _ALLOWED_NODE_TYPES else "analysis",
                    "dependsOn": dependencies,
                }
            )
            seen_refs.add(ref)
        if len(additions) >= MAX_ADDED_NODES_PER_DECISION:
            break
    removals = [
        str(item)[:32]
        for item in raw.get("remove", []) if isinstance(item, str)
    ][:8] if isinstance(raw.get("remove"), list) else []
    return clean, {
        "action": action,
        "reason": reason,
        "confidence": confidence,
        "add": additions,
        "remove": removals,
    }


def _next_node_key(nodes: Iterable[DeepAnalysisWorkflowNode]) -> str:
    numbers = []
    for node in nodes:
        match = re.fullmatch(r"N(\d+)", node.node_key)
        if match:
            numbers.append(int(match.group(1)))
    return f"N{(max(numbers, default=40) + 10):03d}"


def _add_edge(
    db: Session,
    revision: DeepAnalysisWorkflowRevision,
    edges: list[DeepAnalysisWorkflowEdge],
    source: str,
    target: str,
) -> None:
    if source == target or any(
        edge.source_node_key == source and edge.target_node_key == target
        for edge in edges
    ):
        return
    edge = DeepAnalysisWorkflowEdge(
        workflow_revision_id=revision.id,
        source_node_key=source,
        target_node_key=target,
        edge_type="adaptive",
    )
    db.add(edge)
    edges.append(edge)


def _remove_pending_nodes(
    db: Session,
    revision: DeepAnalysisWorkflowRevision,
    nodes: list[DeepAnalysisWorkflowNode],
    edges: list[DeepAnalysisWorkflowEdge],
    requested: set[str],
) -> list[str]:
    removable = {
        node.node_key
        for node in nodes
        if node.node_key in requested
        and node.status in {"planned", "ready"}
        and node.node_type != "report"
    }
    if not removable:
        return []
    predecessors = {
        edge.source_node_key
        for edge in edges
        if edge.target_node_key in removable and edge.source_node_key not in removable
    }
    successors = {
        edge.target_node_key
        for edge in edges
        if edge.source_node_key in removable and edge.target_node_key not in removable
    }
    for edge in list(edges):
        if edge.source_node_key in removable or edge.target_node_key in removable:
            edges.remove(edge)
            db.delete(edge)
    for node in list(nodes):
        if node.node_key in removable:
            nodes.remove(node)
            db.delete(node)
    for source in predecessors:
        for target in successors:
            _add_edge(db, revision, edges, source, target)
    return sorted(removable)


def apply_workflow_decision(
    db: Session,
    *,
    mission: DeepAnalysisMission,
    revision: DeepAnalysisWorkflowRevision,
    current_node: DeepAnalysisWorkflowNode,
    decision: dict[str, Any],
) -> bool:
    nodes = list(
        db.query(DeepAnalysisWorkflowNode)
        .filter(DeepAnalysisWorkflowNode.workflow_revision_id == revision.id)
        .order_by(DeepAnalysisWorkflowNode.sequence)
    )
    edges = list(
        db.query(DeepAnalysisWorkflowEdge)
        .filter(DeepAnalysisWorkflowEdge.workflow_revision_id == revision.id)
    )
    before = _snapshot(nodes, edges)
    action = str(decision.get("action") or "continue")
    graph_change_count = sum(
        1
        for item in revision.change_log_json
        if isinstance(item, dict) and item.get("graphChanged") and item.get("action") != "initial"
    )
    if graph_change_count >= MAX_REPLANS and action != "continue":
        action = "continue"
        decision = {
            **decision,
            "action": "continue",
            "reason": f"재계획 상한 {MAX_REPLANS}회에 도달해 현재 Workflow를 유지했습니다. 원 판단: {decision.get('reason', '')}",
        }

    removed: list[str] = []
    additions = list(decision.get("add") or [])
    if action == "finish":
        removed = _remove_pending_nodes(
            db,
            revision,
            nodes,
            edges,
            {
                node.node_key
                for node in nodes
                if node.status in {"planned", "ready"} and node.node_type != "report"
            },
        )
        additions = []
    elif action in {"shrink", "replace"}:
        removed = _remove_pending_nodes(
            db,
            revision,
            nodes,
            edges,
            set(decision.get("remove") or []),
        )

    added: list[str] = []
    if (
        action in {"expand", "replace"}
        and additions
        and len(nodes) < MAX_WORKFLOW_NODES
    ):
        room = max(0, MAX_WORKFLOW_NODES - len(nodes))
        additions = additions[:room]
        successors = [
            edge.target_node_key
            for edge in list(edges)
            if edge.source_node_key == current_node.node_key
        ]
        for edge in list(edges):
            if edge.source_node_key == current_node.node_key:
                edges.remove(edge)
                db.delete(edge)
        created: list[
            tuple[DeepAnalysisWorkflowNode, dict[str, Any], str]
        ] = []
        used_refs: set[str] = set()
        for index, item in enumerate(additions):
            key = _next_node_key(nodes)
            raw_ref = str(item.get("ref") or f"A{index + 1}")
            ref = re.sub(r"[^A-Za-z0-9_-]", "", raw_ref)[:32]
            if not ref or ref in used_refs or ref.lower() == "current":
                ref = f"A{index + 1}"
            used_refs.add(ref)
            node = DeepAnalysisWorkflowNode(
                workflow_revision_id=revision.id,
                node_key=key,
                node_type=item["nodeType"],
                title=item["title"],
                purpose=item["purpose"],
                status="planned",
                sequence=len(nodes),
                position_x=0,
                position_y=0,
                config_json={
                    "origin": "runtime_replan",
                    "createdByNodeKey": current_node.node_key,
                    "reason": decision.get("reason"),
                    "adaptiveRef": ref,
                    "dependsOn": list(item.get("dependsOn") or ["current"]),
                },
            )
            db.add(node)
            db.flush()
            nodes.append(node)
            added.append(key)
            created.append((node, item, ref))

        available_refs: dict[str, str] = {}
        for node, item, ref in created:
            dependencies = item.get("dependsOn")
            if not isinstance(dependencies, list):
                dependencies = ["current"]
            sources: list[str] = []
            for dependency in dependencies:
                candidate = str(dependency)[:32]
                source = (
                    current_node.node_key
                    if candidate in {"current", current_node.node_key}
                    else available_refs.get(candidate)
                )
                if source and source not in sources:
                    sources.append(source)
            if not sources:
                sources = [current_node.node_key]
            for source in sources:
                _add_edge(db, revision, edges, source, node.node_key)
            available_refs[ref] = node.node_key

        added_set = set(added)
        branch_sources = {
            edge.source_node_key
            for edge in edges
            if edge.source_node_key in added_set and edge.target_node_key in added_set
        }
        terminal_nodes = [key for key in added if key not in branch_sources]
        for successor in successors:
            for terminal in terminal_nodes:
                _add_edge(db, revision, edges, terminal, successor)

    graph_changed = bool(removed or added)
    if action == "finish":
        reports = [node for node in nodes if node.node_type == "report"]
        if reports:
            report = reports[-1]
            if not any(
                edge.target_node_key == report.node_key
                and edge.source_node_key == current_node.node_key
                for edge in edges
            ):
                _add_edge(db, revision, edges, current_node.node_key, report.node_key)
                graph_changed = True

    db.flush()
    if graph_changed:
        layout_workflow(nodes, edges)
        revision.revision_number += 1
        revision.reason = str(decision.get("reason") or "실행 중 Workflow 조정")
        revision.source = "runtime_replan"
        revision.graph_digest = graph_digest(nodes, edges)
    current_node.config_json = {
        **current_node.config_json,
        "workflowDecision": {**decision, "action": action},
    }
    after = _snapshot(nodes, edges)
    revision.change_log_json = [
        *revision.change_log_json,
        {
            "revision": revision.revision_number,
            "action": action,
            "reason": decision.get("reason"),
            "confidence": decision.get("confidence"),
            "requestedByNodeKey": current_node.node_key,
            "addedNodeKeys": added,
            "removedNodeKeys": removed,
            "graphChanged": graph_changed,
            "createdAt": utc_now().isoformat(),
            "before": before,
            "after": after,
        },
    ]
    mission.completion_contract_json = {
        **mission.completion_contract_json,
        "lastWorkflowDecision": {
            "action": action,
            "reason": decision.get("reason"),
            "graphChanged": graph_changed,
        },
    }
    db.flush()
    return graph_changed


def next_runnable_node(
    nodes: list[DeepAnalysisWorkflowNode], edges: list[DeepAnalysisWorkflowEdge]
) -> DeepAnalysisWorkflowNode | None:
    status = {node.node_key: node.status for node in nodes}
    predecessors: dict[str, set[str]] = {node.node_key: set() for node in nodes}
    for edge in edges:
        if edge.target_node_key in predecessors:
            predecessors[edge.target_node_key].add(edge.source_node_key)
    for node in sorted(nodes, key=lambda item: item.sequence):
        if node.status not in {"planned", "ready"}:
            continue
        if all(status.get(key) == "completed" for key in predecessors[node.node_key]):
            return node
    return None


def descendant_node_keys(
    node_key: str, edges: Iterable[DeepAnalysisWorkflowEdge]
) -> set[str]:
    outgoing: dict[str, set[str]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source_node_key, set()).add(edge.target_node_key)
    found = {node_key}
    queue = [node_key]
    while queue:
        current = queue.pop(0)
        for target in outgoing.get(current, set()):
            if target not in found:
                found.add(target)
                queue.append(target)
    return found

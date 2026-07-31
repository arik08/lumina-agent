from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..agent_frontends import DEFAULT_AGENT_FRONTEND
from ..api.errors import ApiProblem
from ..api.schemas import (
    ExecutionSelection,
    MessageReferenceInput,
    RunCreate,
    RunMessageInput,
)
from ..config import Settings
from ..models import (
    Artifact,
    ArtifactVersion,
    Conversation,
    ProjectFile,
    ProjectFileVersion,
    Run,
    ToolExecution,
    User,
    utc_now,
)
from ..project_files.service import (
    create_project_file,
    create_project_file_version,
    logical_path_key,
)
from ..runs.service import create_run
from ..runs.state import CANCELLED, COMPLETED, TERMINAL_STATUSES
from ..storage import ManagedStorage, StorageError
from .models import (
    DeepAnalysisMission,
    DeepAnalysisMissionFileLink,
    DeepAnalysisWorkflowEdge,
    DeepAnalysisWorkflowNode,
    DeepAnalysisWorkflowRevision,
)
from .events import emit_event
from .context_manifest import (
    current_file_version,
    link_file,
    persist_context_manifest,
)
from .planning import dependency_edges, runnable_nodes


_LOOP_DECISION_PATTERN = re.compile(
    r"<!--\s*LUMINA_LOOP_DECISION\s*(\{.*?\})\s*-->",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class TerminalSyncResult:
    next_run_ids: tuple[str, ...] = ()
    changed: bool = False


def pending_terminal_run_ids(db: Session) -> tuple[str, ...]:
    pending = list(
        db.scalars(
            select(DeepAnalysisWorkflowNode.run_id)
            .join(
                Run,
                Run.id == DeepAnalysisWorkflowNode.run_id,
            )
            .where(
                DeepAnalysisWorkflowNode.status == "running",
                DeepAnalysisWorkflowNode.run_id.is_not(None),
                Run.status.in_(TERMINAL_STATUSES),
            )
        )
    )
    repairable = list(
        db.scalars(
            select(DeepAnalysisWorkflowNode.run_id)
            .join(Run, Run.id == DeepAnalysisWorkflowNode.run_id)
            .join(ToolExecution, ToolExecution.run_id == Run.id)
            .where(
                DeepAnalysisWorkflowNode.status == "completed",
                DeepAnalysisWorkflowNode.run_id.is_not(None),
                Run.status == COMPLETED,
                ToolExecution.tool_name.in_({"create_report", "write_file"}),
                ToolExecution.status == "completed",
                ToolExecution.artifact_id.is_not(None),
            )
            .distinct()
        )
    )
    return tuple(
        dict.fromkeys(
            run_id for run_id in (*pending, *repairable) if run_id is not None
        )
    )


def record_recovered_run_ids(db: Session, run_ids: tuple[str, ...]) -> None:
    if not run_ids:
        return
    rows = db.execute(
        select(
            DeepAnalysisWorkflowNode, DeepAnalysisWorkflowRevision, DeepAnalysisMission
        )
        .join(
            DeepAnalysisWorkflowRevision,
            DeepAnalysisWorkflowRevision.id
            == DeepAnalysisWorkflowNode.workflow_revision_id,
        )
        .join(
            DeepAnalysisMission,
            DeepAnalysisMission.id == DeepAnalysisWorkflowRevision.mission_id,
        )
        .where(DeepAnalysisWorkflowNode.run_id.in_(run_ids))
    ).all()
    for node, revision, mission in rows:
        emit_event(
            db,
            mission,
            "node_queued",
            {
                "nodeId": node.id,
                "nodeKey": node.node_key,
                "runId": node.run_id,
                "status": "queued",
                "recovered": True,
                "workflowRevisionId": revision.id,
            },
        )


def _run_context(
    db: Session, run_id: str
) -> (
    tuple[
        DeepAnalysisWorkflowNode,
        DeepAnalysisWorkflowRevision,
        DeepAnalysisMission,
    ]
    | None
):
    return (
        db.execute(
            select(
                DeepAnalysisWorkflowNode,
                DeepAnalysisWorkflowRevision,
                DeepAnalysisMission,
            )
            .join(
                DeepAnalysisWorkflowRevision,
                DeepAnalysisWorkflowRevision.id
                == DeepAnalysisWorkflowNode.workflow_revision_id,
            )
            .join(
                DeepAnalysisMission,
                DeepAnalysisMission.id == DeepAnalysisWorkflowRevision.mission_id,
            )
            .where(DeepAnalysisWorkflowNode.run_id == run_id)
        )
        .tuples()
        .one_or_none()
    )


def record_node_started(db: Session, run: Run) -> None:
    deep_analysis = run.snapshot_json.get("deep_analysis")
    if not isinstance(deep_analysis, dict) or deep_analysis.get("nodeStartedEvent"):
        return
    context = _run_context(db, run.id)
    if context is None:
        return
    node, revision, mission = context
    emit_event(
        db,
        mission,
        "node_started",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run.id,
            "status": run.status,
            "workflowRevisionId": revision.id,
            "attempt": len(node.run_history_json) + 1,
        },
    )
    run.snapshot_json = {
        **run.snapshot_json,
        "deep_analysis": {**deep_analysis, "nodeStartedEvent": True},
    }


def record_output_progress(
    db: Session,
    run: Run,
    *,
    output_characters: int | None = None,
) -> bool:
    """Persist bounded progress markers without copying model text into Mission events."""
    deep_analysis = run.snapshot_json.get("deep_analysis")
    if not isinstance(deep_analysis, dict):
        return False
    if output_characters is None:
        output_characters = len(run.assistant_draft or "")
    if output_characters <= 0:
        return False
    bucket = ((output_characters - 1) // 2000) + 1
    previous_bucket = int(deep_analysis.get("outputEventBucket") or 0)
    run.snapshot_json = {
        **run.snapshot_json,
        "deep_analysis": {
            **deep_analysis,
            "outputCharacters": output_characters,
            "outputEventBucket": max(previous_bucket, bucket),
        },
    }
    if previous_bucket >= bucket:
        return False
    context = _run_context(db, run.id)
    if context is None:
        return False
    node, _revision, mission = context
    emit_event(
        db,
        mission,
        "node_output_delta",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run.id,
            "outputCharacters": output_characters,
            "progressBucket": bucket,
        },
    )
    return True


_UNSAFE_PATH = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MARKDOWN_MARKERS = re.compile(r"(?m)^#{1,6}\s+|\*\*|__|`+|^[-*+]\s+")
_OUTPUT_TIMEZONE = ZoneInfo("Asia/Seoul")


def _path_segment(value: str, *, fallback: str, limit: int = 90) -> str:
    clean = _UNSAFE_PATH.sub("_", value).strip().strip(".")
    clean = re.sub(r"\s+", " ", clean)
    return (clean or fallback)[:limit].rstrip()


def _mission_output_timestamp(mission: DeepAnalysisMission) -> str:
    return mission.created_at.astimezone(_OUTPUT_TIMEZONE).strftime("%y%m%d_%H%M%S")


def _configured_output_format(mission: DeepAnalysisMission) -> str:
    value = str(
        (mission.execution_settings_json or {}).get("outputFormat") or "markdown"
    ).strip()
    return value or "markdown"


def _is_html_output_format(value: str) -> bool:
    return "html" in value.casefold()


def _output_path(mission: DeepAnalysisMission, node: DeepAnalysisWorkflowNode) -> str:
    mission_name = _path_segment(mission.title, fallback="심층분석")
    node_name = _path_segment(node.title, fallback=node.node_key)
    created_at = _mission_output_timestamp(mission)
    suffix = (
        ".html"
        if (
            node.node_type == "report"
            and _is_html_output_format(_configured_output_format(mission))
        )
        else ".md"
    )
    return f"심층분석/{mission_name}_{created_at}/{node.node_key}_{node_name}{suffix}"


def _output_path_for_content(
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    content: str,
) -> str:
    path = _output_path(mission, node)
    normalized = content.lstrip().casefold()
    required_markup = ("<!doctype html", "<html", "<head", "<body")
    is_complete_html = all(marker in normalized for marker in required_markup)
    if node.node_type == "report" and is_complete_html:
        return str(PurePosixPath(path).with_suffix(".html"))
    return str(PurePosixPath(path).with_suffix(".md"))


def _partial_output_path(
    mission: DeepAnalysisMission, node: DeepAnalysisWorkflowNode
) -> str:
    path = _output_path(mission, node)
    suffix = PurePosixPath(path).suffix
    return path.removesuffix(suffix) + f"_partial{suffix}"


def output_directory(mission: DeepAnalysisMission) -> str:
    mission_name = _path_segment(mission.title, fallback="심층분석")
    created_at = _mission_output_timestamp(mission)
    return f"심층분석/{mission_name}_{created_at}"


def _run_manifest(
    db: Session,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
) -> list[dict[str, Any]]:
    manifest = [dict(item) for item in mission.source_manifest_json]
    known_ids = {
        str(item.get("projectFileId")) for item in manifest if item.get("projectFileId")
    }
    workflow_nodes = list(
        db.scalars(
            select(DeepAnalysisWorkflowNode).where(
                DeepAnalysisWorkflowNode.workflow_revision_id
                == node.workflow_revision_id
            )
        )
    )
    edges = list(
        db.scalars(
            select(DeepAnalysisWorkflowEdge).where(
                DeepAnalysisWorkflowEdge.workflow_revision_id
                == node.workflow_revision_id
            )
        )
    )
    incoming: dict[str, set[str]] = {}
    for edge in dependency_edges(edges):
        incoming.setdefault(edge.target_node_key, set()).add(edge.source_node_key)
    direct_predecessor_keys = incoming.get(node.node_key, set())
    ancestor_keys: set[str] = set()
    queue = list(direct_predecessor_keys)
    while queue:
        key = queue.pop(0)
        if key in ancestor_keys:
            continue
        ancestor_keys.add(key)
        queue.extend(incoming.get(key, set()))
    dependency_metadata: dict[str, dict[str, Any]] = {}
    for candidate in sorted(workflow_nodes, key=lambda item: item.sequence):
        if candidate.node_key not in ancestor_keys:
            continue
        if candidate.output_project_file_id:
            dependency_metadata[candidate.output_project_file_id] = {
                "dependencyNodeKey": candidate.node_key,
                "dependencyNodeTitle": candidate.title,
                "dependencyKind": (
                    "direct_predecessor"
                    if candidate.node_key in direct_predecessor_keys
                    else "ancestor"
                ),
                "dependencyOutputRole": "representative",
                "dependencySequence": candidate.sequence,
            }
        for item in candidate.generated_files_json:
            if isinstance(item, dict) and item.get("projectFileId"):
                project_file_id = str(item["projectFileId"])
                if project_file_id in dependency_metadata:
                    continue
                dependency_metadata[project_file_id] = {
                    "dependencyNodeKey": candidate.node_key,
                    "dependencyNodeTitle": candidate.title,
                    "dependencyKind": (
                        "direct_predecessor"
                        if candidate.node_key in direct_predecessor_keys
                        else "ancestor"
                    ),
                    "dependencyOutputRole": "supporting",
                    "dependencySequence": candidate.sequence,
                }
    if not dependency_metadata:
        return manifest
    generated = list(
        db.execute(
            select(ProjectFile, ProjectFileVersion)
            .join(
                ProjectFileVersion,
                (ProjectFileVersion.project_file_id == ProjectFile.id)
                & (
                    ProjectFileVersion.version_number
                    == ProjectFile.current_version_number
                ),
            )
            .where(
                ProjectFile.project_id == mission.project_id,
                ProjectFile.deleted_at.is_(None),
                ProjectFile.id.in_(dependency_metadata),
            )
        ).tuples()
    )
    generated.sort(
        key=lambda row: (
            dependency_metadata[row[0].id]["dependencyKind"] != "direct_predecessor",
            dependency_metadata[row[0].id]["dependencySequence"],
            dependency_metadata[row[0].id]["dependencyOutputRole"] != "representative",
            row[0].logical_path,
        )
    )
    for project_file, version in generated:
        if project_file.id in known_ids:
            continue
        metadata = dependency_metadata[project_file.id]
        manifest.append(
            {
                "projectFileId": project_file.id,
                "logicalPath": project_file.logical_path,
                "version": version.version_number,
                "versionId": version.id,
                "contentHash": version.content_hash,
                "mimeType": version.mime_type,
                "sizeBytes": version.size_bytes,
                "generated": True,
                "dependencyNodeKey": metadata["dependencyNodeKey"],
                "dependencyNodeTitle": metadata["dependencyNodeTitle"],
                "dependencyKind": metadata["dependencyKind"],
                "dependencyOutputRole": metadata["dependencyOutputRole"],
            }
        )
    return manifest


def _manifest_prompt(manifest: list[dict[str, Any]]) -> str:
    if not manifest:
        return "- 시작 시점에 등록된 Project 파일이 없습니다. 자료 부재를 결과에 명시하십시오."
    groups = (
        ("Mission 입력 자료", lambda item: not item.get("generated")),
        (
            "직접 선행 Node 산출물",
            lambda item: item.get("dependencyKind") == "direct_predecessor",
        ),
        (
            "이전 공통 조상 산출물",
            lambda item: item.get("dependencyKind") == "ancestor",
        ),
    )
    lines: list[str] = []
    rendered = 0
    for title, predicate in groups:
        items = [item for item in manifest if predicate(item)]
        if not items:
            continue
        lines.append(f"[{title}]")
        for item in items:
            if rendered >= 200:
                break
            node_key = item.get("dependencyNodeKey")
            output_role = item.get("dependencyOutputRole")
            origin = (
                f" · {node_key} · {'대표 출력' if output_role == 'representative' else '보조 산출물'}"
                if node_key
                else ""
            )
            lines.append(f"- {item['logicalPath']}{origin}")
            rendered += 1
        if rendered >= 200:
            break
    if len(manifest) > 200:
        lines.append(f"- 외 {len(manifest) - 200}개 파일이 있습니다.")
    return "\n".join(lines)


def _summary(markdown: str, limit: int = 420) -> str:
    text = _MARKDOWN_MARKERS.sub("", markdown)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _cost_microusd(usage: dict[str, Any]) -> int:
    value = usage.get("cost_usd")
    if value is None:
        breakdown = usage.get("estimated_cost_breakdown_usd")
        if isinstance(breakdown, dict):
            value = breakdown.get("total")
    try:
        return max(0, int(round(float(value or 0) * 1_000_000)))
    except (TypeError, ValueError):
        return 0


def _stage_instruction(node: DeepAnalysisWorkflowNode) -> str:
    instructions = {
        "scope": (
            "분석 질문을 검증 가능한 형태로 구체화하고, 포함·제외 범위, 핵심 정의, "
            "성공 기준과 필요한 가정을 명시하십시오."
        ),
        "data_check": (
            "Project 파일 목록과 관련 자료를 실제로 확인하십시오. 사용 가능한 근거, 기간·단위·누락·중복·정합성 "
            "문제를 구분하고, 자료가 부족하면 가능한 분석과 불가능한 분석을 명확히 나누십시오."
        ),
        "research": (
            "질문에 필요한 근거와 사례를 실제 자료에서 수집하고, 출처·시점·적용 범위와 빠진 근거를 구분하십시오. "
            "근거가 부족하면 확인된 사실과 추정 영역을 명확히 나누십시오."
        ),
        "analysis": (
            "확인된 자료와 앞 단계 정의를 사용해 핵심 원인과 기여도를 분석하십시오. 숫자 계산이 필요하면 "
            "직접 암산하지 말고 Python 등 실행 도구로 재현 가능한 계산을 수행하고 계산식·입력·결과를 남기십시오."
        ),
        "validation": (
            "앞 단계 결과를 독립적으로 교차검증하고, 반대 근거·대안 설명·자료 품질 문제가 결론을 바꾸는지 점검하십시오. "
            "통과한 주장과 추가 확인이 필요한 주장을 구분하십시오."
        ),
        "synthesis": (
            "앞 단계의 가설과 결과를 서로 교차 검증하고, 반대 근거와 대안 설명을 점검하십시오. "
            "확실한 결론, 조건부 결론, 미확인 항목을 분리하십시오."
        ),
        "report": (
            "의사결정자가 바로 사용할 수 있는 최종 보고서를 작성하십시오. 요약, 핵심 결론, 근거, "
            "정량 결과, 한계, 권고 조치와 후속 확인 항목을 포함하십시오."
        ),
    }
    return instructions.get(node.node_type, node.purpose)


_AnalysisDepth = Literal["auto", "brief", "standard", "deep"]
_AnswerLength = Literal["auto", "brief", "standard", "detailed"]
_OutputMode = Literal["auto", "chat", "file"]


def _node_output_mode(
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
) -> _OutputMode:
    if node.node_type != "report":
        return "chat"
    settings = mission.execution_settings_json or {}
    return cast(_OutputMode, str(settings.get("outputMode") or "auto"))


def _run_profile(
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
) -> tuple[_AnalysisDepth, _AnswerLength, int | None]:
    settings = mission.execution_settings_json or {}
    analysis_depth = cast(_AnalysisDepth, str(settings.get("analysisDepth") or "auto"))
    answer_length = cast(_AnswerLength, str(settings.get("answerLength") or "auto"))
    output_mode = cast(_OutputMode, str(settings.get("outputMode") or "auto"))
    configured_target = settings.get("targetOutputTokens")
    target_output_tokens = (
        int(configured_target)
        if isinstance(configured_target, int)
        and not isinstance(configured_target, bool)
        and configured_target > 0
        else None
    )
    if node.node_type == "report":
        return (
            analysis_depth,
            answer_length,
            target_output_tokens if output_mode != "chat" else None,
        )
    handoff_length: _AnswerLength = (
        "brief" if node.node_type in {"scope", "data_check"} else "standard"
    )
    return (analysis_depth, handoff_length, None)


def _output_instruction(
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
) -> str:
    if node.node_type == "report":
        output_format = _configured_output_format(mission)
        normalized = output_format.casefold()
        if _is_html_output_format(output_format):
            format_instruction = (
                "최종 산출물은 독립 실행 가능한 HTML 문서로 작성하십시오. <!doctype html>로 시작하고 "
                "html, head, body를 포함하며 Markdown code fence로 감싸지 마십시오."
            )
            if normalized not in {"html", "html (.html)", ".html"}:
                format_instruction += (
                    f" 사용자가 입력한 구체적 형태는 '{output_format}'입니다."
                )
        elif normalized in {"markdown", "markdown (.md)", "md", ".md"}:
            format_instruction = "최종 산출물은 Markdown 문서로 작성하십시오."
        else:
            format_instruction = (
                f"사용자가 지정한 최종 산출물 형태는 '{output_format}'입니다. 이 형태의 구성과 표현을 "
                "최종 보고서에 반영하십시오. 직접 입력한 형태의 원문은 Markdown 파일로 저장됩니다."
            )
        return (
            "이 Node는 최종 산출물입니다. 선행 결과를 단순히 이어 붙이지 말고 중복을 제거해 "
            "하나의 일관된 최종 보고서로 작성하십시오. 의사결정에 필요한 결론, 근거, 반대 근거, "
            f"한계와 후속 조치를 충분히 설명하십시오. {format_instruction}"
        )
    return (
        "형식 경계(최우선): Mission 설명의 HTML 보고서 요청은 report 유형의 최종 Node에만 적용됩니다. "
        "현재 Node는 report가 아니므로 완전한 Markdown만 작성하고 <!doctype html>, <html>, <head>, "
        "<body>, <style>, <script>를 포함하지 마십시오. "
        "이 Node의 출력은 사용자가 직접 읽는 중간보고서이자 다음 Node를 위한 압축 인계물입니다. "
        "파일을 작성했다거나 항목을 반영했다는 완료 안내만 쓰지 마십시오. 서론, Executive Summary, "
        "맺음말과 일반 배경 설명으로 분량을 늘리지 말고, 이 단계에서 새로 확인하거나 판단한 사실, "
        "근거·출처, 계산 결과, 반대 근거·불확실성, 다음 Node가 반드시 알아야 할 내용을 본문으로 남기십시오. "
        "선행 산출물의 내용을 반복 요약하지 말고 필요한 경우 해당 파일이나 섹션을 가리키십시오. "
        "본문 끝에는 `## 다음 Node 인계`를 두고 `결론`, `근거`, `불확실성`, `참조` 항목을 간결하게 작성하십시오."
    )


def _run_prompt_prefix(
    mission: DeepAnalysisMission,
    manifest: list[dict[str, Any]],
) -> str:
    settings = mission.execution_settings_json or {}
    research_period = settings.get("researchPeriod")
    if not isinstance(research_period, dict):
        research_period = {}
    start_date = research_period.get("startDate") or "제한 없음"
    end_date = research_period.get("endDate") or "제한 없음"
    source_policy = settings.get("webSourcePolicy")
    if not isinstance(source_policy, dict):
        source_policy = {}
    source_mode = str(source_policy.get("mode") or "all")
    source_domains = (
        ", ".join(str(value) for value in source_policy.get("domains", []) if value)
        or "없음"
    )
    excluded_domains = (
        ", ".join(
            str(value) for value in source_policy.get("excludedDomains", []) if value
        )
        or "없음"
    )
    guidance_lines = [
        f"{index}. {item.get('instruction')}"
        for index, item in enumerate(settings.get("guidanceHistory", []), start=1)
        if isinstance(item, dict) and item.get("instruction")
    ]
    guidance = "\n".join(guidance_lines[-50:]) or "- 추가 지침 없음"
    return f"""당신은 Lumina Workflow에서 하나의 작업 세션을 실행하고 있습니다.

Mission: {mission.title}
Mission 설명: {mission.objective or mission.title}

선행 세션 출력과 Project 파일:
{_manifest_prompt(manifest)}

연구 범위와 출처 정책:
- 연구 기간: {start_date} ~ {end_date}
- 웹 출처 모드: {source_mode}
- 우선 또는 허용 도메인: {source_domains}
- 제외 도메인: {excluded_domains}
- restrict 모드에서는 허용 도메인 밖의 웹 출처를 사용하지 마십시오. prioritize 모드에서는 지정 도메인을 우선하되 필요한 보완 출처를 사용할 수 있습니다.

실행 중 추가 지침(이 Node 시작 전에 제출된 항목):
{guidance}
"""


def _merge_instruction(manifest: list[dict[str, Any]]) -> str:
    predecessor_keys = tuple(
        dict.fromkeys(
            str(item["dependencyNodeKey"])
            for item in manifest
            if item.get("dependencyKind") == "direct_predecessor"
            and item.get("dependencyNodeKey")
        )
    )
    if len(predecessor_keys) < 2:
        return ""
    return (
        "합류 규칙:\n"
        f"- 직접 선행 Node {', '.join(predecessor_keys)}의 대표 출력을 각각 확인하십시오.\n"
        "- 같은 파일·출처·주장을 반복해 붙이지 말고 파일 version과 출처를 기준으로 중복을 제거하십시오.\n"
        "- 서로 충돌하는 결론은 임의로 하나를 버리지 말고 각 근거와 적용 조건을 나란히 보존한 뒤 판단하십시오.\n"
        "- 공통 조상 산출물은 배경으로 한 번만 사용하고 직접 선행 Node가 새로 만든 판단을 중심으로 합성하십시오."
    )


def _loop_settings(node: DeepAnalysisWorkflowNode) -> dict[str, Any] | None:
    value = (node.config_json or {}).get("loopBack")
    if not isinstance(value, dict):
        return None
    target = value.get("targetNodeKey")
    condition = value.get("condition")
    max_iterations = value.get("maxIterations")
    if (
        not isinstance(target, str)
        or not isinstance(condition, str)
        or not condition.strip()
        or not isinstance(max_iterations, int)
        or isinstance(max_iterations, bool)
        or not 2 <= max_iterations <= 3
    ):
        return None
    return {
        "targetNodeKey": target,
        "condition": condition.strip(),
        "maxIterations": max_iterations,
    }


def _loop_instruction(node: DeepAnalysisWorkflowNode) -> str:
    settings = _loop_settings(node)
    if settings is None:
        return ""
    completed_iterations = sum(
        isinstance(item, dict)
        and item.get("loopBackTargetNodeKey") == settings["targetNodeKey"]
        for item in node.run_history_json
    )
    iteration = completed_iterations + 1
    return f"""

반복 판단:
- 이 Node는 {settings["targetNodeKey"]}부터 다시 실행할 수 있는 검증 Node입니다.
- 현재 반복은 {iteration}/{settings["maxIterations"]}회차입니다.
- 반복 조건: {settings["condition"]}
- 확인 가능한 근거로 조건이 충족되고 현재 반복이 마지막이 아닐 때만 repeat를 true로 판단하십시오.
- 본문 맨 끝에 아래 HTML 주석을 정확히 하나 추가하십시오. 이 주석은 저장 전에 제거됩니다.
<!-- LUMINA_LOOP_DECISION {{"repeat":true|false,"reason":"판단 근거"}} -->
"""


def _extract_loop_decision(markdown: str) -> tuple[str, dict[str, Any] | None]:
    match = _LOOP_DECISION_PATTERN.search(markdown)
    clean = _LOOP_DECISION_PATTERN.sub("", markdown).rstrip()
    if match is None:
        return clean, None
    try:
        payload = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return clean, None
    if not isinstance(payload, dict) or not isinstance(payload.get("repeat"), bool):
        return clean, None
    return clean, {
        "repeat": payload["repeat"],
        "reason": str(payload.get("reason") or "").strip()[:1000],
    }


def _run_prompt(
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    manifest: list[dict[str, Any]],
) -> str:
    stable_prefix = _run_prompt_prefix(mission, manifest)
    merge_instruction = _merge_instruction(manifest)
    loop_instruction = _loop_instruction(node)
    return f"""{stable_prefix}
--- Node 전용 지시 ---

작업 세션: {node.node_key} · {node.title}

작업 프롬프트:
{node.purpose or node.title}

단계별 지시:
{_stage_instruction(node)}

{merge_instruction}

{loop_instruction}

출력 계약:
{_output_instruction(mission, node)}

실행 규칙:
- 필요한 경우 위 Project 파일과 선행 세션 출력을 실제로 확인·사용하십시오.
- 확인하지 않은 사실이나 수치를 만들어내지 마십시오.
- 보고서가 아닌 Node는 다음 Node가 그대로 인계받을 수 있는 Markdown 문서만 한국어로 작성하십시오.
- 채팅 인사말이나 작업 예고 없이 완성된 본문부터 출력하십시오.
"""


def _ensure_node_conversation(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
) -> Conversation:
    if node.conversation_id:
        existing = db.get(Conversation, node.conversation_id)
        if existing is not None:
            return existing
    conversation = Conversation(
        organization_id=mission.organization_id,
        project_id=mission.project_id,
        owner_user_id=user.id,
        title=f"{mission.title} · {node.node_key} {node.title}",
        surface="deep_analysis",
        agent_id=DEFAULT_AGENT_FRONTEND.agent_id,
        agent_version=DEFAULT_AGENT_FRONTEND.agent_version,
        revision=1,
    )
    db.add(conversation)
    db.flush()
    node.conversation_id = conversation.id
    return conversation


def _reserved_budget_microusd(
    db: Session,
    nodes: list[DeepAnalysisWorkflowNode],
) -> int:
    run_ids = [
        node.run_id for node in nodes if node.status == "running" and node.run_id
    ]
    if not run_ids:
        return 0
    total = 0
    for run in db.scalars(select(Run).where(Run.id.in_(run_ids))):
        deep_analysis = run.snapshot_json.get("deep_analysis")
        reservation = (
            deep_analysis.get("budget_reservation_microusd")
            if isinstance(deep_analysis, dict)
            else None
        )
        if isinstance(reservation, int) and not isinstance(reservation, bool):
            total += max(0, reservation)
            continue
        limits = run.snapshot_json.get("limits")
        max_cost_usd = limits.get("maxCostUsd") if isinstance(limits, dict) else None
        if isinstance(max_cost_usd, (int, float)) and not isinstance(
            max_cost_usd, bool
        ):
            total += max(0, round(float(max_cost_usd) * 1_000_000))
    return total


def _available_budget_microusd(
    db: Session,
    mission: DeepAnalysisMission,
    nodes: list[DeepAnalysisWorkflowNode],
) -> int | None:
    if mission.budget_microusd is None:
        return None
    return max(
        0,
        mission.budget_microusd
        - mission.spent_microusd
        - _reserved_budget_microusd(db, nodes),
    )


def create_node_run(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    settings: Settings,
    budget_limit_microusd: int | None = None,
) -> tuple[Run, bool]:
    if node.run_id:
        existing = db.get(Run, node.run_id)
        if existing is not None:
            return existing, False
    if mission.budget_microusd is not None and budget_limit_microusd is None:
        workflow_nodes = list(
            db.scalars(
                select(DeepAnalysisWorkflowNode).where(
                    DeepAnalysisWorkflowNode.workflow_revision_id
                    == node.workflow_revision_id
                )
            )
        )
        budget_limit_microusd = _available_budget_microusd(db, mission, workflow_nodes)
    if budget_limit_microusd is not None and budget_limit_microusd <= 0:
        raise ApiProblem(
            409, "mission_budget_exhausted", "Mission 예산이 소진되었습니다."
        )

    conversation = _ensure_node_conversation(
        db,
        user=user,
        mission=mission,
        node=node,
    )
    manifest = _run_manifest(db, mission, node)
    analysis_depth, answer_length, target_output_tokens = _run_profile(mission, node)
    attempt = len(node.run_history_json) + 1
    prompt = _run_prompt(
        mission,
        node,
        manifest,
    )
    stable_prefix_text = _run_prompt_prefix(mission, manifest)
    execution_settings = mission.execution_settings_json or {}
    objective_offset = prompt.find(mission.objective) if mission.objective else -1
    prompt_references = []
    for item in execution_settings.get("promptReferences", []):
        if not isinstance(item, dict):
            continue
        reference = {
            key: item.get(key)
            for key in (
                "kind",
                "reference_id",
                "version_or_digest",
                "display_snapshot",
                "token_start",
                "token_end",
            )
        }
        token_start = reference.get("token_start")
        token_end = reference.get("token_end")
        if (
            objective_offset >= 0
            and isinstance(token_start, int)
            and isinstance(token_end, int)
        ):
            reference["token_start"] = token_start + objective_offset
            reference["token_end"] = token_end + objective_offset
        prompt_references.append(MessageReferenceInput.model_validate(reference))
    output_mode = _node_output_mode(mission, node)
    frozen_execution = execution_settings.get("execution")
    selected_execution = (
        ExecutionSelection.model_validate(frozen_execution)
        if isinstance(frozen_execution, dict)
        else None
    )
    run, _message, created = create_run(
        db,
        user=user,
        conversation_id=conversation.id,
        payload=RunCreate(
            message=RunMessageInput(
                text=prompt,
                prompt_references=prompt_references,
                output_mode=output_mode,
                analysis_depth=analysis_depth,
                answer_length=answer_length,
                target_output_tokens=target_output_tokens,
            ),
            execution=selected_execution,
        ),
        idempotency_key=(
            f"deep-analysis:{mission.id}:{node.node_key}:attempt:{attempt}"
        ),
        image_backend_model=settings.codex_image_model,
        settings=settings,
    )
    run.snapshot_json = {
        **run.snapshot_json,
        "clarification_mode": "autonomous",
        "memory_learning_mode": "off",
        "deep_analysis": {
            "mission_id": mission.id,
            "node_id": node.id,
            "node_key": node.node_key,
            "node_type": node.node_type,
            "output_format": (
                _configured_output_format(mission)
                if node.node_type == "report"
                else "markdown"
            ),
            "attempt": attempt,
            "output_directory": output_directory(mission),
            "research_period": execution_settings.get(
                "researchPeriod", {"startDate": None, "endDate": None}
            ),
            "web_source_policy": execution_settings.get(
                "webSourcePolicy",
                {"mode": "all", "domains": [], "excludedDomains": []},
            ),
            "guidance_history": execution_settings.get("guidanceHistory", []),
        },
        "project_file_manifest": manifest,
    }
    if budget_limit_microusd is not None:
        budget_limit_usd = budget_limit_microusd / 1_000_000
        limits = dict(run.snapshot_json.get("limits", {}))
        configured_limit = float(limits.get("maxCostUsd") or 0)
        effective_limit_usd = (
            min(configured_limit, budget_limit_usd)
            if configured_limit > 0
            else budget_limit_usd
        )
        limits["maxCostUsd"] = effective_limit_usd
        deep_analysis = dict(run.snapshot_json.get("deep_analysis", {}))
        deep_analysis["budget_reservation_microusd"] = round(
            effective_limit_usd * 1_000_000
        )
        run.snapshot_json = {
            **run.snapshot_json,
            "limits": limits,
            "deep_analysis": deep_analysis,
        }
    node.run_id = run.id
    node.status = "running"
    node.started_at = node.started_at or utc_now()
    node.error_message = None
    db.flush()
    context_manifest = persist_context_manifest(
        db,
        mission=mission,
        node=node,
        run=run,
        files=manifest,
        tool_profile="deep-analysis-core-v1",
        stable_prefix_text=stable_prefix_text,
        dynamic_context_characters=len(prompt),
    )
    if created:
        emit_event(
            db,
            mission,
            "node_queued",
            {
                "nodeId": node.id,
                "nodeKey": node.node_key,
                "runId": run.id,
                "status": run.status,
                "attempt": attempt,
                "workflowRevisionId": node.workflow_revision_id,
                "contextManifestId": context_manifest.id,
                "prefixHash": context_manifest.prefix_hash,
            },
        )
    return run, created


def create_runnable_node_runs(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    nodes: list[DeepAnalysisWorkflowNode],
    edges: list[DeepAnalysisWorkflowEdge],
    settings: Settings,
) -> tuple[Run, ...]:
    fanout_limit = max(
        1,
        min(settings.user_concurrency_limit, settings.server_concurrency_limit),
    )
    active_count = sum(
        node.status == "running" and node.run_id is not None for node in nodes
    )
    slots = max(0, fanout_limit - active_count)
    if slots == 0:
        return ()
    candidates = [
        node for node in nodes if node.status == "running" and node.run_id is None
    ]
    candidates.extend(runnable_nodes(nodes, edges))
    selected = candidates[:slots]
    if not selected:
        return ()
    budget_limits: list[int | None] = [None] * len(selected)
    available_budget = _available_budget_microusd(db, mission, nodes)
    if available_budget is not None:
        if available_budget <= 0:
            return ()
        share, remainder = divmod(available_budget, len(selected))
        budget_limits = [
            share + (1 if index < remainder else 0) for index in range(len(selected))
        ]
    created_runs: list[Run] = []
    for node, budget_limit in zip(selected, budget_limits, strict=True):
        run, created = create_node_run(
            db,
            user=user,
            mission=mission,
            node=node,
            settings=settings,
            budget_limit_microusd=budget_limit,
        )
        if created:
            created_runs.append(run)
    return tuple(created_runs)


def archive_current_attempt(db: Session, node: DeepAnalysisWorkflowNode) -> None:
    if not node.run_id:
        return
    run = db.get(Run, node.run_id)
    item = {
        "attempt": len(node.run_history_json) + 1,
        "runId": node.run_id,
        "status": run.status if run is not None else node.status,
        "costMicrousd": _cost_microusd(run.usage_json) if run is not None else 0,
        "errorMessage": (
            run.error_message
            if run is not None and run.error_message
            else node.error_message
        ),
        "startedAt": (
            run.started_at.isoformat()
            if run is not None and run.started_at is not None
            else node.started_at.isoformat()
            if node.started_at is not None
            else None
        ),
        "finishedAt": (
            run.finished_at.isoformat()
            if run is not None and run.finished_at is not None
            else node.finished_at.isoformat()
            if node.finished_at is not None
            else None
        ),
    }
    node.run_history_json = [*node.run_history_json, item]


def _generated_files(db: Session, run_id: str) -> list[dict[str, Any]]:
    tools = db.scalars(
        select(ToolExecution)
        .where(
            ToolExecution.run_id == run_id,
            ToolExecution.tool_name == "run_python_calculation",
            ToolExecution.status == "completed",
        )
        .order_by(ToolExecution.created_at, ToolExecution.id)
    )
    files: list[dict[str, Any]] = []
    for tool in tools:
        result = tool.result_json or {}
        for item in result.get("files", []):
            if isinstance(item, dict) and item.get("projectFileId"):
                files.append(dict(item))
    return files


def _completed_artifact_output(
    db: Session,
    run_id: str,
    *,
    storage: ManagedStorage,
) -> str | None:
    rows = db.execute(
        select(Artifact, ArtifactVersion)
        .join(ToolExecution, ToolExecution.artifact_id == Artifact.id)
        .join(
            ArtifactVersion,
            (ArtifactVersion.artifact_id == Artifact.id)
            & (ArtifactVersion.version_number == Artifact.current_version_number),
        )
        .where(
            ToolExecution.run_id == run_id,
            ToolExecution.tool_name.in_({"create_report", "write_file"}),
            ToolExecution.status == "completed",
            Artifact.source_run_id == run_id,
            Artifact.deleted_at.is_(None),
        )
        .order_by(ToolExecution.created_at.desc(), ToolExecution.id.desc())
    ).tuples()
    for _artifact, version in rows:
        try:
            content = (
                storage.read_bytes(
                    version.storage_key,
                    expected_sha256=version.content_hash,
                )
                .decode("utf-8")
                .strip()
            )
        except (StorageError, UnicodeDecodeError):
            continue
        if content:
            return content
    return None


def _mission_spent(db: Session, workflow_revision_id: str) -> int:
    total = 0
    for item in db.scalars(
        select(DeepAnalysisWorkflowNode).where(
            DeepAnalysisWorkflowNode.workflow_revision_id == workflow_revision_id
        )
    ):
        total += item.actual_cost_microusd
        total += sum(
            int(history.get("costMicrousd") or 0)
            for history in item.run_history_json
            if isinstance(history, dict)
        )
    return total


def _save_output(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    run: Run,
    markdown: str,
    storage: ManagedStorage,
    settings: Settings,
) -> None:
    if node.output_project_file_id:
        version_row = current_file_version(db, node.output_project_file_id)
        if version_row is not None:
            project_file, version = version_row
            expected_path = _output_path_for_content(mission, node, markdown)
            if (
                PurePosixPath(project_file.logical_path).suffix
                == PurePosixPath(expected_path).suffix
            ):
                content = markdown.encode("utf-8")
                if version.content_hash != hashlib.sha256(content).hexdigest():
                    project_file, version = create_project_file_version(
                        db,
                        user=user,
                        project_id=mission.project_id,
                        file_id=project_file.id,
                        base_version=project_file.current_version_number,
                        original_filename=PurePosixPath(project_file.logical_path).name,
                        content=content,
                        change_reason=(
                            f"심층분석 {mission.id} {node.node_key} 산출물 복구"
                        ),
                        source_run_id=run.id,
                        max_upload_bytes=settings.max_upload_bytes,
                        storage=storage,
                    )
                node.output_logical_path = project_file.logical_path
                link_file(
                    db,
                    mission=mission,
                    project_file_id=project_file.id,
                    version_id=version.id,
                    node=node,
                    run=run,
                    purpose="node_output",
                    validation_status="completed",
                    metadata={"logicalPath": project_file.logical_path},
                )
                return
        node.output_project_file_id = None
        node.output_logical_path = None
    logical_path = _output_path_for_content(mission, node, markdown)
    existing = db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == mission.project_id,
            ProjectFile.active_path_key == logical_path_key(logical_path),
            ProjectFile.deleted_at.is_(None),
        )
    )
    if existing is not None:
        node.output_project_file_id = existing.id
        node.output_logical_path = existing.logical_path
        version_row = current_file_version(db, existing.id)
        if version_row is not None:
            _file, version = version_row
            link_file(
                db,
                mission=mission,
                project_file_id=existing.id,
                version_id=version.id,
                node=node,
                run=run,
                purpose="node_output",
                validation_status="completed",
                metadata={"logicalPath": existing.logical_path},
            )
        return
    project_file, version = create_project_file(
        db,
        user=user,
        project_id=mission.project_id,
        logical_path=logical_path,
        original_filename=PurePosixPath(logical_path).name,
        content=markdown.encode("utf-8"),
        change_reason=f"심층분석 {mission.id} {node.node_key} 출력",
        max_upload_bytes=settings.max_upload_bytes,
        storage=storage,
    )
    node.output_project_file_id = project_file.id
    node.output_logical_path = project_file.logical_path
    link_file(
        db,
        mission=mission,
        project_file_id=project_file.id,
        version_id=version.id,
        node=node,
        run=run,
        purpose="node_output",
        validation_status="completed",
        metadata={"logicalPath": project_file.logical_path},
    )


def _save_partial_output(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    run: Run,
    markdown: str,
    storage: ManagedStorage,
    settings: Settings,
) -> tuple[str, str] | None:
    content = markdown.strip()
    if not content:
        return None
    logical_path = _partial_output_path(mission, node)
    existing = db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == mission.project_id,
            ProjectFile.active_path_key == logical_path_key(logical_path),
            ProjectFile.deleted_at.is_(None),
        )
    )
    if existing is not None:
        version_row = current_file_version(db, existing.id)
        if version_row is None:
            return None
        project_file, version = version_row
    else:
        project_file, version = create_project_file(
            db,
            user=user,
            project_id=mission.project_id,
            logical_path=logical_path,
            original_filename=PurePosixPath(logical_path).name,
            content=content.encode("utf-8"),
            change_reason=f"심층분석 {mission.id} {node.node_key} 중단 출력 보존",
            max_upload_bytes=settings.max_upload_bytes,
            storage=storage,
        )
    link_file(
        db,
        mission=mission,
        project_file_id=project_file.id,
        version_id=version.id,
        node=node,
        run=run,
        purpose="partial_output",
        validation_status="interrupted",
        metadata={
            "logicalPath": project_file.logical_path,
            "terminalRunStatus": run.status,
        },
    )
    return project_file.id, project_file.logical_path


def preserve_partial_output(
    db: Session,
    *,
    user: User,
    mission: DeepAnalysisMission,
    node: DeepAnalysisWorkflowNode,
    run: Run,
    storage: ManagedStorage,
    settings: Settings,
) -> tuple[str, str] | None:
    saved = _save_partial_output(
        db,
        user=user,
        mission=mission,
        node=node,
        run=run,
        markdown=run.assistant_draft,
        storage=storage,
        settings=settings,
    )
    if saved is None:
        return None
    project_file_id, logical_path = saved
    emit_event(
        db,
        mission,
        "mission_file_created",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "projectFileId": project_file_id,
            "logicalPath": logical_path,
            "purpose": "partial_output",
            "validationStatus": "interrupted",
        },
    )
    return saved


def sync_terminal_run(
    db: Session,
    *,
    run_id: str,
    storage: ManagedStorage,
    artifact_storage: ManagedStorage,
    settings: Settings,
) -> TerminalSyncResult:
    row = db.execute(
        select(
            DeepAnalysisWorkflowNode, DeepAnalysisWorkflowRevision, DeepAnalysisMission
        )
        .join(
            DeepAnalysisWorkflowRevision,
            DeepAnalysisWorkflowRevision.id
            == DeepAnalysisWorkflowNode.workflow_revision_id,
        )
        .join(
            DeepAnalysisMission,
            DeepAnalysisMission.id == DeepAnalysisWorkflowRevision.mission_id,
        )
        .where(DeepAnalysisWorkflowNode.run_id == run_id)
    ).one_or_none()
    if row is None:
        return TerminalSyncResult()
    node, workflow_revision, mission = row
    run = db.get(Run, run_id)
    if run is None or run.status not in TERMINAL_STATUSES:
        return TerminalSyncResult()
    artifact_output = (
        _completed_artifact_output(db, run_id, storage=artifact_storage)
        if run.status == COMPLETED
        else None
    )
    if node.status == "completed":
        if not artifact_output or artifact_output == node.output_markdown:
            return TerminalSyncResult()
        user = db.get(User, mission.created_by_user_id)
        if user is None:
            return TerminalSyncResult()
        _save_output(
            db,
            user=user,
            mission=mission,
            node=node,
            run=run,
            markdown=artifact_output,
            storage=storage,
            settings=settings,
        )
        node.output_markdown = artifact_output
        node.output_summary = _summary(artifact_output)
        node.error_message = None
        mission.revision += 1
        emit_event(
            db,
            mission,
            "mission_file_created",
            {
                "nodeId": node.id,
                "nodeKey": node.node_key,
                "projectFileId": node.output_project_file_id,
                "logicalPath": node.output_logical_path,
                "purpose": "node_output_repair",
                "missionRevision": mission.revision,
            },
        )
        return TerminalSyncResult(changed=True)
    if node.status in {"failed", "cancelled"}:
        return TerminalSyncResult()

    node.actual_cost_microusd = _cost_microusd(run.usage_json)
    node.generated_files_json = _generated_files(db, run_id)
    node.finished_at = run.finished_at or utc_now()
    user = db.get(User, mission.created_by_user_id)
    if user is None:
        node.status = "failed"
        node.error_message = "실행 사용자를 찾을 수 없습니다."
        mission.status = "failed"
        mission.revision += 1
        return TerminalSyncResult(changed=True)

    if run.status == COMPLETED:
        clean_assistant, loop_decision = _extract_loop_decision(
            run.assistant_draft.strip()
        )
        markdown, artifact_loop_decision = _extract_loop_decision(
            artifact_output or clean_assistant
        )
        loop_decision = artifact_loop_decision or loop_decision
        if not markdown:
            node.status = "failed"
            node.error_message = "모델이 비어 있는 출력을 반환했습니다."
            mission.status = "failed"
            mission.revision += 1
            return TerminalSyncResult(changed=True)
        _save_output(
            db,
            user=user,
            mission=mission,
            node=node,
            run=run,
            markdown=markdown,
            storage=storage,
            settings=settings,
        )
        node.output_markdown = markdown
        node.output_summary = _summary(markdown)
        node.status = "completed"
        node.error_message = None
        db.flush()
        for generated_file in node.generated_files_json:
            if not isinstance(generated_file, dict) or not generated_file.get(
                "projectFileId"
            ):
                continue
            version_row = current_file_version(db, str(generated_file["projectFileId"]))
            if version_row is None:
                continue
            project_file, version = version_row
            link_file(
                db,
                mission=mission,
                project_file_id=project_file.id,
                version_id=version.id,
                node=node,
                run=run,
                purpose="calculation_output",
                validation_status="tool_completed",
                metadata={
                    "logicalPath": project_file.logical_path,
                    "kind": generated_file.get("kind"),
                },
            )
        emit_event(
            db,
            mission,
            "node_completed",
            {
                "nodeId": node.id,
                "nodeKey": node.node_key,
                "runId": run.id,
                "status": node.status,
                "outputProjectFileId": node.output_project_file_id,
                "outputLogicalPath": node.output_logical_path,
                "actualCostMicrousd": node.actual_cost_microusd,
            },
        )
        if node.output_project_file_id:
            emit_event(
                db,
                mission,
                "mission_file_created",
                {
                    "nodeId": node.id,
                    "nodeKey": node.node_key,
                    "projectFileId": node.output_project_file_id,
                    "logicalPath": node.output_logical_path,
                },
            )
        mission.spent_microusd = _mission_spent(db, workflow_revision.id)
        emit_event(
            db,
            mission,
            "mission_cost_updated",
            {
                "spentMicrousd": mission.spent_microusd,
                "budgetMicrousd": mission.budget_microusd,
                "nodeId": node.id,
                "nodeKey": node.node_key,
            },
        )

        nodes = list(
            db.scalars(
                select(DeepAnalysisWorkflowNode)
                .where(
                    DeepAnalysisWorkflowNode.workflow_revision_id
                    == workflow_revision.id
                )
                .order_by(DeepAnalysisWorkflowNode.sequence)
            )
        )
        edges = list(
            db.scalars(
                select(DeepAnalysisWorkflowEdge).where(
                    DeepAnalysisWorkflowEdge.workflow_revision_id
                    == workflow_revision.id
                )
            )
        )
        if (
            mission.budget_microusd is not None
            and mission.spent_microusd >= mission.budget_microusd
        ):
            mission.status = "blocked"
            mission.revision += 1
            emit_event(
                db,
                mission,
                "mission_budget_warning",
                {
                    "status": mission.status,
                    "spentMicrousd": mission.spent_microusd,
                    "budgetMicrousd": mission.budget_microusd,
                    "missionRevision": mission.revision,
                },
            )
            return TerminalSyncResult(changed=True)

        loop_edge = next(
            (
                edge
                for edge in edges
                if edge.edge_type == "loop_back"
                and edge.source_node_key == node.node_key
            ),
            None,
        )
        loop_settings = _loop_settings(node)
        if loop_edge is not None and loop_settings is not None:
            completed_iterations = sum(
                isinstance(item, dict)
                and item.get("loopBackTargetNodeKey") == loop_edge.target_node_key
                for item in node.run_history_json
            )
            current_iteration = completed_iterations + 1
            repeat = bool(loop_decision and loop_decision["repeat"])
            repeat = repeat and current_iteration < loop_settings["maxIterations"]
            loop_reason = (
                loop_decision["reason"]
                if loop_decision is not None
                else "구조화된 반복 판단이 없어 다음 단계로 진행합니다."
            )
            emit_event(
                db,
                mission,
                "workflow_loop_evaluated",
                {
                    "sourceNodeKey": node.node_key,
                    "targetNodeKey": loop_edge.target_node_key,
                    "iteration": current_iteration,
                    "maxIterations": loop_settings["maxIterations"],
                    "repeat": repeat,
                    "reason": loop_reason,
                },
            )
            if repeat:
                forward_edges = dependency_edges(edges)
                descendants = {loop_edge.target_node_key}
                queue = [loop_edge.target_node_key]
                while queue:
                    source_key = queue.pop()
                    for edge in forward_edges:
                        if (
                            edge.source_node_key == source_key
                            and edge.target_node_key not in descendants
                        ):
                            descendants.add(edge.target_node_key)
                            queue.append(edge.target_node_key)
                ancestors = {node.node_key}
                queue = [node.node_key]
                while queue:
                    target_key = queue.pop()
                    for edge in forward_edges:
                        if (
                            edge.target_node_key == target_key
                            and edge.source_node_key not in ancestors
                        ):
                            ancestors.add(edge.source_node_key)
                            queue.append(edge.source_node_key)
                loop_node_keys = descendants & ancestors
                loop_node_ids = {
                    item.id for item in nodes if item.node_key in loop_node_keys
                }
                if loop_node_ids:
                    db.execute(
                        update(DeepAnalysisMissionFileLink)
                        .where(
                            DeepAnalysisMissionFileLink.producing_node_id.in_(
                                loop_node_ids
                            )
                        )
                        .values(stale_status="review_required")
                        .execution_options(synchronize_session=False)
                    )
                for loop_node in nodes:
                    if loop_node.node_key not in loop_node_keys:
                        continue
                    archive_current_attempt(db, loop_node)
                    if loop_node.id == node.id and loop_node.run_history_json:
                        history = list(loop_node.run_history_json)
                        history[-1] = {
                            **history[-1],
                            "loopBackTargetNodeKey": loop_edge.target_node_key,
                            "loopIteration": current_iteration,
                            "loopReason": loop_reason,
                        }
                        loop_node.run_history_json = history
                    loop_node.status = "planned"
                    loop_node.run_id = None
                    loop_node.output_project_file_id = None
                    loop_node.output_logical_path = None
                    loop_node.output_summary = ""
                    loop_node.output_markdown = ""
                    loop_node.generated_files_json = []
                    loop_node.error_message = None
                    loop_node.actual_cost_microusd = 0
                    loop_node.started_at = None
                    loop_node.finished_at = None
                db.flush()
                next_runs = create_runnable_node_runs(
                    db,
                    user=user,
                    mission=mission,
                    nodes=nodes,
                    edges=edges,
                    settings=settings,
                )
                mission.revision += 1
                emit_event(
                    db,
                    mission,
                    "workflow_loop_restarted",
                    {
                        "sourceNodeKey": node.node_key,
                        "targetNodeKey": loop_edge.target_node_key,
                        "iteration": current_iteration + 1,
                        "maxIterations": loop_settings["maxIterations"],
                        "nodeKeys": sorted(loop_node_keys),
                        "missionRevision": mission.revision,
                    },
                )
                return TerminalSyncResult(
                    next_run_ids=tuple(item.id for item in next_runs),
                    changed=True,
                )

        next_runs = create_runnable_node_runs(
            db,
            user=user,
            mission=mission,
            nodes=nodes,
            edges=edges,
            settings=settings,
        )
        if next_runs:
            mission.revision += 1
            return TerminalSyncResult(
                next_run_ids=tuple(item.id for item in next_runs),
                changed=True,
            )

        running = [item for item in nodes if item.status == "running"]
        if running:
            mission.revision += 1
            return TerminalSyncResult(changed=True)

        unresolved = [item for item in nodes if item.status in {"planned", "ready"}]
        if unresolved:
            mission.status = "blocked"
            mission.revision += 1
            emit_event(
                db,
                mission,
                "mission_status_changed",
                {
                    "status": mission.status,
                    "missionRevision": mission.revision,
                    "blockedNodeKeys": [item.node_key for item in unresolved],
                },
            )
            return TerminalSyncResult(changed=True)

        mission.status = "completed"
        mission.completion_outcome = "satisfied"
        mission.revision += 1
        emit_event(
            db,
            mission,
            "mission_completed",
            {
                "status": mission.status,
                "missionRevision": mission.revision,
                "finalOutputFileId": node.output_project_file_id,
            },
        )
        return TerminalSyncResult(changed=True)

    preserve_partial_output(
        db,
        user=user,
        mission=mission,
        node=node,
        run=run,
        storage=storage,
        settings=settings,
    )
    node.status = "cancelled" if run.status == CANCELLED else "failed"
    node.error_message = (
        None
        if run.status == CANCELLED
        else (run.error_message or "Node 실행에 실패했습니다.")
    )
    mission.status = "cancelled" if run.status == CANCELLED else "failed"
    mission.spent_microusd = _mission_spent(db, workflow_revision.id)
    mission.revision += 1
    emit_event(
        db,
        mission,
        "node_failed" if node.status == "failed" else "node_cancelled",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run.id,
            "status": node.status,
            "missionStatus": mission.status,
            "missionRevision": mission.revision,
            "actualCostMicrousd": node.actual_cost_microusd,
        },
    )
    return TerminalSyncResult(changed=True)


def fail_terminal_sync(db: Session, *, run_id: str, message: str) -> bool:
    row = db.execute(
        select(DeepAnalysisWorkflowNode, DeepAnalysisMission)
        .join(
            DeepAnalysisWorkflowRevision,
            DeepAnalysisWorkflowRevision.id
            == DeepAnalysisWorkflowNode.workflow_revision_id,
        )
        .join(
            DeepAnalysisMission,
            DeepAnalysisMission.id == DeepAnalysisWorkflowRevision.mission_id,
        )
        .where(DeepAnalysisWorkflowNode.run_id == run_id)
    ).one_or_none()
    if row is None:
        return False
    node, mission = row
    if node.status != "running":
        return False
    node.status = "failed"
    node.error_message = message
    node.finished_at = utc_now()
    mission.status = "failed"
    mission.revision += 1
    emit_event(
        db,
        mission,
        "node_failed",
        {
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "runId": run_id,
            "status": node.status,
            "missionStatus": mission.status,
            "missionRevision": mission.revision,
        },
    )
    return True

from __future__ import annotations

import ast
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SERVER_SOURCE = _REPOSITORY_ROOT / "apps" / "server" / "src" / "lumina"
_EXECUTION_STATE_MODULE = _SERVER_SOURCE / "runs" / "execution_state.py"


def _python_sources() -> list[Path]:
    return sorted(_SERVER_SOURCE.rglob("*.py"))


def test_execution_snapshot_keys_have_one_storage_boundary() -> None:
    offenders: list[str] = []
    for path in _python_sources():
        if path == _EXECUTION_STATE_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in {
                "model_turn_inflight",
                "tool_checkpoint",
            }:
                offenders.append(f"{path.relative_to(_REPOSITORY_ROOT)}:{node.lineno}")

    assert offenders == []


def test_run_status_assignments_stay_inside_transition_boundary() -> None:
    offenders: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                raw_targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                targets.extend(raw_targets)
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "status"
                    and isinstance(target.value, ast.Name)
                    and target.value.id.endswith("run")
                    and target.value.id != "scheduled_run"
                ):
                    offenders.append(
                        f"{path.relative_to(_REPOSITORY_ROOT)}:{target.lineno}"
                    )

    assert offenders == []


def test_tool_execution_records_always_have_an_idempotency_key() -> None:
    offenders: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ToolExecution"
            ):
                continue
            if not any(keyword.arg == "idempotency_key" for keyword in node.keywords):
                offenders.append(f"{path.relative_to(_REPOSITORY_ROOT)}:{node.lineno}")

    assert offenders == []

from lumina.agent.executor import _tool_event
from lumina.models import ToolExecution
from lumina.runs.service import tool_display_name, tool_response


def _tool(tool_name: str) -> ToolExecution:
    return ToolExecution(
        id="tool-id",
        run_id="run-id",
        tool_call_id="call-id",
        tool_name=tool_name,
        validated_input_json={},
        status="running",
    )


def test_tool_display_name_uses_user_facing_search_labels() -> None:
    assert tool_display_name("web_search") == "검색"
    assert tool_display_name("web_fetch") == "페이지 확인"


def test_tool_name_is_identical_in_live_events_and_run_snapshots() -> None:
    for tool_name in ("web_search", "web_fetch", "create_report", "mcp__server__fetch"):
        tool = _tool(tool_name)

        expected_label = tool_display_name(tool_name)
        assert _tool_event(tool)["label"] == expected_label
        assert tool_response(tool)["label"] == expected_label

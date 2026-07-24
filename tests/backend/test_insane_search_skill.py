from __future__ import annotations

import json
from pathlib import Path

from lumina.agent import executor as executor_module
from lumina.models import Run
from lumina.tools.web import WebToolError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPOSITORY_ROOT / "extensions" / "skills"


def _fallback_skill_run(*, allow_implicit_invocation: bool = True) -> Run:
    return Run(
        snapshot_json={
            "extensions": [
                {
                    "extension_id": "insane-search-id",
                    "slug": "insane-search",
                    "name": "insane-search",
                    "instructions": "# Insane Search\nUse the fallback retrieval chain.",
                    "digest": "digest",
                    "allow_implicit_invocation": allow_implicit_invocation,
                }
            ],
            "extension_application": "explicit_references",
            "prompt_references": [],
        }
    )


def _http_error(status_code: int) -> WebToolError:
    return WebToolError(
        "http_error",
        f"외부 서버 요청이 HTTP {status_code}로 실패했습니다.",
        stage="http",
        status_code=status_code,
    )


def test_blocked_web_fetch_recommends_insane_search_without_activating_it() -> None:
    run = _fallback_skill_run()

    recommendation = executor_module._blocked_web_fallback_skill_recommendation(
        run,
        tool_name="web_fetch",
        error=_http_error(403),
    )

    assert recommendation is not None
    assert recommendation["skillId"] == "insane-search-id"
    assert recommendation["slug"] == "insane-search"
    assert "결론에 중요" in recommendation["reason"]
    assert "merely one of several candidate sources" in recommendation["instruction"]
    assert "API cost" in recommendation["instruction"]
    assert "auto_selected_skill_ids" not in run.snapshot_json


def test_non_fallback_http_statuses_do_not_recommend_insane_search() -> None:
    for status_code in (401, 402, 404):
        run = _fallback_skill_run()

        recommendation = executor_module._blocked_web_fallback_skill_recommendation(
            run,
            tool_name="web_fetch",
            error=_http_error(status_code),
        )

        assert recommendation is None
        assert "auto_selected_skill_ids" not in run.snapshot_json


def test_blocked_web_fetch_respects_disabled_implicit_skill_activation() -> None:
    run = _fallback_skill_run(allow_implicit_invocation=False)

    recommendation = executor_module._blocked_web_fallback_skill_recommendation(
        run,
        tool_name="web_fetch",
        error=_http_error(403),
    )

    assert recommendation is None
    assert "auto_selected_skill_ids" not in run.snapshot_json


def test_insane_search_is_a_material_last_resort_not_a_generic_403_fallback() -> None:
    skill = (SKILL_ROOT / "insane-search" / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(skill.split())

    assert "blocked source that is material to the answer" in normalized
    assert "merely one of several candidate sources" in normalized
    assert "Never use it to bypass authentication, paywalls" in normalized
    assert "Weigh API cost, site terms, and legal risk" in normalized
    assert "are signals only, never sufficient grounds by themselves" in normalized


def test_insane_search_catalog_description_preserves_model_judgment() -> None:
    catalog = json.loads((SKILL_ROOT / "catalog.json").read_text(encoding="utf-8"))
    description = catalog["insane-search"]["description"]

    assert "여러 검색 후보 중 하나가 실패한 경우에는 사용하지 않고" in description
    assert "자동 선택하지 않으며" in description
    assert "API 비용, 사이트 약관과 법적 위험" in description
    assert "모델이 판단해야 합니다" in description

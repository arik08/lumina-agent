from pathlib import Path
from typing import get_args

from lumina import document_limits, image_formats, secret_policy
from lumina.agent import image_tool
from lumina.artifacts import render_validation
from lumina.artifacts import service as artifact_service
from lumina.artifacts.reporting import theme
from lumina.attachments import extraction, validation
from lumina.extensions import service as extension_service
from lumina.extensions import package_policy, repository_catalog
from lumina.mcp import policy as mcp_policy
from lumina.mcp import runtime as mcp_runtime
from lumina.mcp import service as mcp_service
from lumina.notifications import service as notification_service
from lumina.projects import memberships, schemas
from lumina.providers.codex import image_generation
from lumina.runs import state as run_state
from lumina.schedules import service as schedule_service
from lumina.tools import workspace


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_project_membership_values_come_from_schema_types() -> None:
    assert memberships.PROJECT_ROLES is schemas.PROJECT_ROLES
    assert memberships.MEMBERSHIP_STATUSES is schemas.MEMBERSHIP_STATUSES
    assert schemas.PROJECT_ROLES == frozenset(get_args(schemas.ProjectRole))
    assert schemas.MEMBERSHIP_STATUSES == frozenset(
        get_args(schemas.ProjectMembershipStatus)
    )


def test_mcp_security_policy_is_shared_by_validation_and_runtime() -> None:
    assert mcp_runtime.SECRET_NAME_PATTERN is mcp_policy.SECRET_NAME_PATTERN
    assert mcp_service.SECRET_NAME_PATTERN is mcp_policy.SECRET_NAME_PATTERN
    assert (
        mcp_runtime.APPROVABLE_PRIVATE_NETWORKS
        is mcp_policy.APPROVABLE_PRIVATE_NETWORKS
    )
    assert (
        mcp_service.APPROVABLE_PRIVATE_NETWORKS
        is mcp_policy.APPROVABLE_PRIVATE_NETWORKS
    )


def test_image_format_mapping_is_shared_by_tool_and_provider() -> None:
    assert image_tool.IMAGE_MIME_BY_FORMAT is image_formats.IMAGE_MIME_BY_FORMAT
    assert image_generation.IMAGE_MIME_BY_FORMAT is image_formats.IMAGE_MIME_BY_FORMAT
    assert image_tool.IMAGE_FORMAT_BY_MIME is image_formats.IMAGE_FORMAT_BY_MIME


def test_report_palette_values_only_live_in_theme_module() -> None:
    reporting_root = REPOSITORY_ROOT / "apps/server/src/lumina/artifacts/reporting"
    canonical_values = {
        theme.COBALT_HEX,
        theme.INK_HEX,
        theme.MUTED_HEX,
        theme.LIGHT_BLUE_HEX,
    }
    for path in reporting_root.glob("*.py"):
        if path.name == "theme.py":
            continue
        source = path.read_text(encoding="utf-8").upper()
        for value in canonical_values:
            assert value not in source, path


def test_terminal_and_secret_policies_are_shared() -> None:
    assert notification_service.TERMINAL_STATUSES is run_state.TERMINAL_STATUSES
    assert (
        extension_service.reject_secret_key_names
        is secret_policy.reject_secret_key_names
    )
    assert (
        schedule_service.reject_secret_key_names
        is secret_policy.reject_secret_key_names
    )


def test_document_safety_limits_are_shared_across_processing_stages() -> None:
    assert render_validation.MAX_DOCUMENT_PAGES is document_limits.MAX_DOCUMENT_PAGES
    assert artifact_service.MAX_DOCUMENT_PAGES is document_limits.MAX_DOCUMENT_PAGES
    assert extraction.MAX_DOCUMENT_PAGES is document_limits.MAX_DOCUMENT_PAGES
    assert validation.MAX_OPENXML_MEMBERS is document_limits.MAX_OPENXML_MEMBERS
    assert artifact_service.MAX_OPENXML_MEMBERS is document_limits.MAX_OPENXML_MEMBERS


def test_skill_text_file_policy_is_shared_by_catalog_and_workspace() -> None:
    assert repository_catalog.SKILL_TEXT_SUFFIXES is package_policy.SKILL_TEXT_SUFFIXES
    assert workspace.SKILL_TEXT_SUFFIXES is package_policy.SKILL_TEXT_SUFFIXES

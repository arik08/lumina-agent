from __future__ import annotations

from pathlib import Path

import pytest

from lumina.api.errors import ApiProblem
from lumina.extensions.agent_skill_spec import (
    AgentSkillSpecError,
    parse_agent_skill,
)
from lumina.extensions.package_content import decode_package_content
from lumina.extensions.repository_catalog import _skill_package
from lumina.extensions.service import normalize_package, standardize_skill_package


def test_agent_skill_frontmatter_accepts_standard_optional_fields() -> None:
    document = parse_agent_skill(
        "---\n"
        "name: company-calculator\n"
        "description: Calculate approved company scenarios. Use for forecast requests.\n"
        "license: Proprietary\n"
        "compatibility: Requires the company calculator MCP connection.\n"
        "metadata:\n"
        "  lumina-source: skill-mcp:company-calculator\n"
        'allowed-tools: "company_calculator__run"\n'
        "---\n\n"
        "# Company calculator\n",
        expected_name="company-calculator",
    )

    assert document.name == "company-calculator"
    assert document.metadata == {
        "lumina-source": "skill-mcp:company-calculator"
    }
    assert document.compatibility == (
        "Requires the company calculator MCP connection."
    )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("# Missing frontmatter", "YAML frontmatter"),
        (
            "---\nname: Wrong\ndescription: invalid name\n---\n",
            "lowercase",
        ),
        (
            "---\nname: other\ndescription: mismatch\n---\n",
            "match",
        ),
        (
            "---\nname: expected\n---\n",
            "requires description",
        ),
    ],
)
def test_agent_skill_frontmatter_rejects_invalid_documents(
    content: str,
    message: str,
) -> None:
    with pytest.raises(AgentSkillSpecError, match=message):
        parse_agent_skill(content, expected_name="expected")


def test_legacy_skill_is_migrated_and_no_nonstandard_five_mb_cap_is_applied() -> None:
    large_reference = "x" * 5_100_000
    package, document = standardize_skill_package(
        normalize_package(
            {
                "SKILL.md": "# Legacy workflow\n",
                "references/large.txt": large_reference,
            }
        ),
        expected_name="legacy-workflow",
        fallback_description=(
            "Run the legacy workflow. Use when the user requests this workflow."
        ),
    )

    assert document.name == "legacy-workflow"
    assert package["SKILL.md"].startswith("---\nname: legacy-workflow\n")
    assert package["references/large.txt"] == large_reference


@pytest.mark.parametrize(
    "content",
    [
        "api_key = os.environ.get('OPENAI_API_KEY')\n",
        "api_key = read_api_key(args.api_key_env)\n",
    ],
)
def test_package_secret_scan_allows_runtime_key_lookup(content: str) -> None:
    package = normalize_package(
        {
            "SKILL.md": "# Runtime key lookup\n",
            "scripts/example.py": content,
        }
    )

    assert package["scripts/example.py"] == content


@pytest.mark.parametrize(
    "content",
    [
        "api_key = actualsecretvalue\n",
        "password: 'actualsecretvalue'\n",
    ],
)
def test_package_secret_scan_rejects_literal_secret_assignments(content: str) -> None:
    with pytest.raises(ApiProblem) as error:
        normalize_package(
            {
                "SKILL.md": "# Unsafe secret\n",
                "references/example.txt": content,
            }
        )

    assert error.value.code == "secret_content_forbidden"


def test_standardize_rejects_a_frontmatter_name_that_differs_from_slug() -> None:
    with pytest.raises(ApiProblem) as error:
        standardize_skill_package(
            {
                "SKILL.md": (
                    "---\n"
                    "name: another-name\n"
                    "description: Use this for another workflow.\n"
                    "---\n"
                )
            },
            expected_name="expected-name",
            fallback_description="unused",
        )

    assert error.value.code == "invalid_agent_skill"


def test_repository_package_preserves_binary_assets(tmp_path: Path) -> None:
    root = tmp_path / "binary-skill"
    (root / "assets").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\n"
        "name: binary-skill\n"
        "description: Use this Skill when a binary template is required.\n"
        "---\n",
        encoding="utf-8",
    )
    expected = b"\x89PNG\r\n\x1a\n\x00\xff"
    (root / "assets" / "template.png").write_bytes(expected)

    package = _skill_package(root)
    decoded, encoding = decode_package_content(package["assets/template.png"])

    assert encoding == "base64"
    assert decoded == expected

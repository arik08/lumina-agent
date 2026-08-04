from pathlib import Path
import subprocess
import sys


SKILL_CREATOR = (
    Path(__file__).resolve().parents[2] / "extensions" / "skills" / "skill-creator"
)
QUICK_VALIDATE = SKILL_CREATOR / "scripts" / "quick_validate.py"
INIT_SKILL = SKILL_CREATOR / "scripts" / "init_skill.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        check=False,
        text=True,
    )


def test_lumina_skill_creation_uses_persistent_extensions_workspace() -> None:
    instructions = (SKILL_CREATOR / "SKILL.md").read_text(encoding="utf-8")

    assert "with the `create_skill` tool" in instructions
    assert "`extensions/skills/<skill-name>/`" in instructions
    assert "Never choose `.skills/` or `skills/`" in instructions
    assert "temporary directory" in instructions


def test_quick_validate_accepts_standard_optional_frontmatter(tmp_path: Path) -> None:
    skill_dir = tmp_path / "portable-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: portable-skill\n"
        "description: Process portable inputs. Use when validating a portable workflow.\n"
        "license: Apache-2.0\n"
        "compatibility: Requires Python 3.12 or newer.\n"
        'allowed-tools: "Read Bash(python:*)"\n'
        "metadata:\n"
        '  author: "example-org"\n'
        '  version: "1.0"\n'
        "---\n\n"
        "# Portable Skill\n",
        encoding="utf-8",
    )

    result = _run(str(QUICK_VALIDATE), str(skill_dir))

    assert result.returncode == 0, result.stdout + result.stderr


def test_quick_validate_requires_name_to_match_parent_directory(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "different-directory"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: portable-skill\n"
        "description: Process portable inputs. Use for portable workflows.\n"
        "---\n",
        encoding="utf-8",
    )

    result = _run(str(QUICK_VALIDATE), str(skill_dir))

    assert result.returncode == 1
    assert "must match parent directory" in result.stdout


def test_init_skill_keeps_client_metadata_opt_in(tmp_path: Path) -> None:
    result = _run(
        str(INIT_SKILL),
        "portable-skill",
        "--path",
        str(tmp_path),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    skill_dir = tmp_path / "portable-skill"
    assert (skill_dir / "SKILL.md").exists()
    assert not (skill_dir / "agents" / "openai.yaml").exists()


def test_init_skill_can_generate_optional_client_metadata(tmp_path: Path) -> None:
    result = _run(
        str(INIT_SKILL),
        "client-skill",
        "--path",
        str(tmp_path),
        "--openai-interface",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "client-skill" / "agents" / "openai.yaml").exists()

"""Tests for the registry instructions field and _build_list_registries_description.

# spec: openspec/changes/registry-instructions-field/specs/registry-instructions/spec.md
"""

import json
from pathlib import Path

from skills_mcp.config.loader import load_config
from skills_mcp.config.model import (
    CacheConfig,
    Config,
    GithubRegistry,
    HttpRegistry,
    NoAuth,
)
from skills_mcp.server import _build_list_registries_description


def _write_config(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "skills-mcp.jsonc"
    p.write_text(json.dumps(data))
    return p


def _github_reg(
    name: str = "my-reg",
    description: str | None = None,
    instructions: str | None = None,
) -> GithubRegistry:
    return GithubRegistry(
        name=name,
        owner="acme",
        repo="skills",
        skills_dir="skills",
        ref="main",
        auth=NoAuth(),
        cache_enabled=True,
        description=description,
        instructions=instructions,
    )


def _http_reg(
    name: str = "my-http",
    description: str | None = None,
    instructions: str | None = None,
) -> HttpRegistry:
    return HttpRegistry(
        name=name,
        url="https://example.com/SKILL.md",
        skill_name="my-skill",
        auth=NoAuth(),
        cache_enabled=True,
        description=description,
        instructions=instructions,
    )


def _cfg(*regs: GithubRegistry | HttpRegistry) -> Config:
    return Config(
        registries={r.name: r for r in regs},
        cache=CacheConfig(),
    )


# ---------------------------------------------------------------------------
# Scenario: GitHub registry with instructions parses correctly
# ---------------------------------------------------------------------------


def test_github_registry_with_instructions_parses_correctly(tmp_path: Path):
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "my-reg": {
                    "type": "github",
                    "owner": "acme",
                    "repo": "skills",
                    "skills_dir": "skills",
                    "ref": "main",
                    "instructions": "Call list_skills('my-reg') at the start of every session",
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["my-reg"]
    assert isinstance(reg, GithubRegistry)
    assert reg.instructions == "Call list_skills('my-reg') at the start of every session"


# ---------------------------------------------------------------------------
# Scenario: HTTP registry with instructions parses correctly
# ---------------------------------------------------------------------------


def test_http_registry_with_instructions_parses_correctly(tmp_path: Path):
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "my-http": {
                    "type": "http",
                    "url": "https://example.com/SKILL.md",
                    "skill_name": "my-skill",
                    "instructions": "Always list skills from my-http first",
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["my-http"]
    assert isinstance(reg, HttpRegistry)
    assert reg.instructions == "Always list skills from my-http first"


# ---------------------------------------------------------------------------
# Scenario: Registry without instructions defaults to None
# ---------------------------------------------------------------------------


def test_registry_without_instructions_defaults_to_none(tmp_path: Path):
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "r": {
                    "type": "github",
                    "owner": "o",
                    "repo": "r",
                    "skills_dir": "",
                    "ref": "main",
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["r"]
    assert isinstance(reg, GithubRegistry)
    assert reg.instructions is None


# ---------------------------------------------------------------------------
# Scenario: Empty string instructions treated as None
# ---------------------------------------------------------------------------


def test_empty_string_instructions_treated_as_none(tmp_path: Path):
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "r": {
                    "type": "github",
                    "owner": "o",
                    "repo": "r",
                    "skills_dir": "",
                    "ref": "main",
                    "instructions": "",
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["r"]
    assert isinstance(reg, GithubRegistry)
    assert reg.instructions is None


# ---------------------------------------------------------------------------
# Scenario: Description with no registries configured
# ---------------------------------------------------------------------------

_STATIC_INTRO = "List all configured skill registries."


def test_description_with_no_registries_configured():
    result = _build_list_registries_description(_cfg())
    assert _STATIC_INTRO in result
    assert "Configured registries:" not in result


# ---------------------------------------------------------------------------
# Scenario: Description with registry having description and instructions
# ---------------------------------------------------------------------------


def test_description_with_registry_having_description_and_instructions():
    reg = _github_reg(
        description="The acme skills registry",
        instructions="Call list_skills('my-reg') at session start",
    )
    result = _build_list_registries_description(_cfg(reg))
    assert "my-reg" in result
    assert "The acme skills registry" in result
    assert "Call list_skills('my-reg') at session start" in result


# ---------------------------------------------------------------------------
# Scenario: Description with registry having description only
# ---------------------------------------------------------------------------


def test_description_with_registry_having_description_only():
    reg = _github_reg(description="The acme skills registry", instructions=None)
    result = _build_list_registries_description(_cfg(reg))
    assert "my-reg" in result
    assert "The acme skills registry" in result
    # instructions is None — no instructions line should follow
    assert "list_skills" not in result


# ---------------------------------------------------------------------------
# Scenario: Description with registry having neither description nor instructions
# ---------------------------------------------------------------------------


def test_description_with_registry_having_neither_description_nor_instructions():
    reg = _github_reg(description=None, instructions=None)
    result = _build_list_registries_description(_cfg(reg))
    assert "my-reg" in result


# ---------------------------------------------------------------------------
# Scenario: Description with instructions only (no description)
# ---------------------------------------------------------------------------


def test_description_with_instructions_only_no_description():
    reg = _github_reg(
        description=None,
        instructions="Call list_skills('my-reg') at session start",
    )
    result = _build_list_registries_description(_cfg(reg))
    assert "my-reg" in result
    assert "Call list_skills('my-reg') at session start" in result


# ---------------------------------------------------------------------------
# Scenario: Multiple registries appear in config order
# ---------------------------------------------------------------------------


def test_multiple_registries_appear_in_config_order():
    reg_a = _github_reg(name="alpha", instructions="Alpha instructions")
    reg_b = _http_reg(name="beta", instructions="Beta instructions")
    result = _build_list_registries_description(_cfg(reg_a, reg_b))
    pos_alpha = result.index("alpha")
    pos_beta = result.index("beta")
    assert pos_alpha < pos_beta

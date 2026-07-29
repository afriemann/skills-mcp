"""Tests for config loader: error paths and valid loading."""

import json
from pathlib import Path

import pytest

from skills_mcp.config.loader import load_config
from skills_mcp.config.model import (
    BasicAuth,
    BearerAuth,
    GhCliAuth,
    GithubRegistry,
    GithubTokenAuth,
    HttpRegistry,
    NoAuth,
)


def _write_config(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "skills-mcp.jsonc"
    p.write_text(json.dumps(data))
    return p


def test_missing_config_exits(tmp_path: Path):
    with pytest.raises(SystemExit) as exc_info:
        load_config(tmp_path / "nonexistent.jsonc")
    assert exc_info.value.code == 1


def test_bad_json_exits(tmp_path: Path):
    p = tmp_path / "bad.jsonc"
    p.write_text("{not valid json")
    with pytest.raises(SystemExit) as exc_info:
        load_config(p)
    assert exc_info.value.code == 1


def test_unknown_registry_type_exits(tmp_path: Path):
    p = _write_config(tmp_path, {"registries": {"r": {"type": "ftp"}}})
    with pytest.raises(SystemExit) as exc_info:
        load_config(p)
    assert exc_info.value.code == 1


def test_valid_minimal_github_config(tmp_path: Path):
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "my-skills": {
                    "type": "github",
                    "owner": "acme",
                    "repo": "skills",
                    "skills_dir": "skills",
                    "ref": "main",
                }
            }
        },
    )
    cfg = load_config(p)
    assert "my-skills" in cfg.registries
    reg = cfg.registries["my-skills"]
    assert isinstance(reg, GithubRegistry)
    assert reg.owner == "acme"
    assert reg.ref == "main"
    assert not reg.ref_is_sha
    assert isinstance(reg.auth, NoAuth)


def test_github_sha_ref_is_sha_true(tmp_path: Path):
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "r": {
                    "type": "github",
                    "owner": "o",
                    "repo": "r",
                    "skills_dir": "",
                    "ref": "abc1234",
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["r"]
    assert isinstance(reg, GithubRegistry)
    assert reg.ref_is_sha  # 7-char hex → SHA


def test_github_branch_ref_is_sha_false(tmp_path: Path):
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
    assert not reg.ref_is_sha


def test_github_token_auth(tmp_path: Path):
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
                    "auth": {"type": "github_token", "env_var": "GH_TOKEN"},
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["r"]
    assert isinstance(reg, GithubRegistry)
    assert isinstance(reg.auth, GithubTokenAuth)
    assert reg.auth.env_var == "GH_TOKEN"


def test_github_gh_cli_auth(tmp_path: Path):
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
                    "auth": {"type": "gh_cli"},
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["r"]
    assert isinstance(reg, GithubRegistry)
    assert isinstance(reg.auth, GhCliAuth)


def test_valid_http_config(tmp_path: Path):
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "my-http": {
                    "type": "http",
                    "url": "https://example.com/SKILL.md",
                    "skill_name": "my-skill",
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["my-http"]
    assert isinstance(reg, HttpRegistry)
    assert reg.url == "https://example.com/SKILL.md"
    assert reg.skill_name == "my-skill"
    assert isinstance(reg.auth, NoAuth)


def test_http_bearer_auth(tmp_path: Path):
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "r": {
                    "type": "http",
                    "url": "https://x.com/SKILL.md",
                    "skill_name": "s",
                    "auth": {"type": "bearer", "env_var": "MY_TOKEN"},
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["r"]
    assert isinstance(reg, HttpRegistry)
    assert isinstance(reg.auth, BearerAuth)
    assert reg.auth.env_var == "MY_TOKEN"


def test_http_basic_auth(tmp_path: Path):
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "r": {
                    "type": "http",
                    "url": "https://x.com/SKILL.md",
                    "skill_name": "s",
                    "auth": {
                        "type": "basic",
                        "username_env_var": "USER",
                        "password_env_var": "PASS",
                    },
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["r"]
    assert isinstance(reg, HttpRegistry)
    assert isinstance(reg.auth, BasicAuth)
    assert reg.auth.username_env_var == "USER"


def test_missing_env_var_name_exits(tmp_path: Path):
    """Empty env_var string must exit(1)."""
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
                    "auth": {"type": "github_token", "env_var": ""},
                }
            }
        },
    )
    with pytest.raises(SystemExit) as exc_info:
        load_config(p)
    assert exc_info.value.code == 1


def test_jsonc_with_comments(tmp_path: Path):
    """A JSONC file with // comments and trailing commas must load successfully."""
    content = """\
{
  // global cache settings
  "registries": {
    "r": {
      "type": "http",  // inline comment
      "url": "https://example.com/SKILL.md",
      "skill_name": "demo",
    },
  },
}
"""
    p = tmp_path / "skills-mcp.jsonc"
    p.write_text(content)
    cfg = load_config(p)
    assert "r" in cfg.registries


def test_url_with_double_slash_in_config(tmp_path: Path):
    """URLs containing '//' must survive JSONC comment stripping."""
    p = _write_config(
        tmp_path,
        {
            "registries": {
                "r": {
                    "type": "http",
                    "url": "https://raw.githubusercontent.com/foo/bar/main/SKILL.md",
                    "skill_name": "bar",
                }
            }
        },
    )
    cfg = load_config(p)
    reg = cfg.registries["r"]
    assert isinstance(reg, HttpRegistry)
    assert "https://" in reg.url

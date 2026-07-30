# spec: openspec/changes/skill-listing-frontmatter-index/specs/frontmatter-parsing/spec.md
"""Unit tests for the SKILL.md frontmatter parser (parse_frontmatter)."""

import pytest

from skills_mcp.frontmatter import parse_frontmatter

# ---------------------------------------------------------------------------
# Scenario: Standard description + tags frontmatter is parsed correctly
# ---------------------------------------------------------------------------


def test_bare_scalar_and_block_list_parsed():
    """Description (bare scalar) and tags (block list) are parsed into the result dict."""
    content = (
        "---\n"
        "description: Use this skill for coding tasks\n"
        "tags:\n"
        "  - python\n"
        "  - async\n"
        "---\n"
        "# Skill content\n"
    )
    result = parse_frontmatter(content)
    assert result["description"] == "Use this skill for coding tasks"
    assert result["tags"] == ["python", "async"]


def test_single_quoted_scalar_parsed():
    """Single-quoted string values are stripped of their outer quotes."""
    content = "---\ndescription: 'A useful skill'\n---\n"
    result = parse_frontmatter(content)
    assert result["description"] == "A useful skill"


def test_double_quoted_scalar_parsed():
    """Double-quoted string values are stripped of their outer quotes."""
    content = '---\ndescription: "A useful skill"\n---\n'
    result = parse_frontmatter(content)
    assert result["description"] == "A useful skill"


# ---------------------------------------------------------------------------
# Scenario: No frontmatter fence returns empty dict
# ---------------------------------------------------------------------------


def test_no_fence_returns_empty_dict():
    """Content without --- delimiters returns an empty dict."""
    content = "# Just a regular SKILL.md\nNo frontmatter here."
    result = parse_frontmatter(content)
    assert result == {}


def test_empty_content_returns_empty_dict():
    """Empty string returns an empty dict."""
    result = parse_frontmatter("")
    assert result == {}


# ---------------------------------------------------------------------------
# Scenario: Partial / malformed input returns partial dict without raising
# ---------------------------------------------------------------------------


def test_partial_frontmatter_no_raise():
    """An unclosed frontmatter block returns whatever was parsed; never raises."""
    content = "---\nname: my-skill\ndescription: 'Incomplete\n"
    result = parse_frontmatter(content)
    assert isinstance(result, dict)
    assert result.get("name") == "my-skill"
    # Incomplete quoted string is silently skipped; no exception


def test_malformed_line_no_raise():
    """Arbitrary malformed YAML-ish content must never raise."""
    garbage = "---\n: no key\n  bad indent\nkey:\nvalue\n---\n"
    result = parse_frontmatter(garbage)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Scenario: Colon inside quoted value is preserved (not treated as separator)
# ---------------------------------------------------------------------------


def test_colon_inside_single_quoted_value_preserved():
    """A colon inside a single-quoted scalar value must not be treated as key: value."""
    content = "---\ndescription: 'Use when: logging is needed'\n---\n"
    result = parse_frontmatter(content)
    assert result["description"] == "Use when: logging is needed"


def test_colon_inside_double_quoted_value_preserved():
    """A colon inside a double-quoted scalar value must not be treated as key: value."""
    content = '---\ndescription: "Use when: logging is needed"\n---\n'
    result = parse_frontmatter(content)
    assert result["description"] == "Use when: logging is needed"


# ---------------------------------------------------------------------------
# Scenario: Hash inside quoted value is preserved (not treated as comment)
# ---------------------------------------------------------------------------


def test_hash_inside_single_quoted_not_stripped():
    """A # inside a single-quoted value is literal, not a comment marker."""
    content = "---\ndescription: 'foo #bar'\n---\n"
    result = parse_frontmatter(content)
    assert result["description"] == "foo #bar"


def test_hash_inline_bare_not_stripped():
    """An inline # in a bare scalar value is literal, not stripped (per spec D1)."""
    content = "---\nname: my-skill # intentional\n---\n"
    result = parse_frontmatter(content)
    assert result["name"] == "my-skill # intentional"


# ---------------------------------------------------------------------------
# Scenario: Full-line comments are skipped
# ---------------------------------------------------------------------------


def test_full_line_comment_skipped():
    """Lines whose first non-whitespace character is # are skipped entirely."""
    content = "---\n# This is a comment\nname: skill\n---\n"
    result = parse_frontmatter(content)
    assert result == {"name": "skill"}


# ---------------------------------------------------------------------------
# Scenario: '' single-quote escape is resolved
# ---------------------------------------------------------------------------


def test_single_quoted_apostrophe_escape():
    """'' inside a single-quoted string is the escape sequence for a literal apostrophe."""
    content = "---\ndescription: 'It''s great'\n---\n"
    result = parse_frontmatter(content)
    assert result["description"] == "It's great"


def test_double_apostrophe_escape_multiple():
    """Multiple '' escapes in one value are all resolved."""
    content = "---\ndescription: 'don''t stop, won''t'\n---\n"
    result = parse_frontmatter(content)
    assert result["description"] == "don't stop, won't"


# ---------------------------------------------------------------------------
# Scenario: Nested mappings are silently skipped
# ---------------------------------------------------------------------------


def test_nested_mapping_silently_skipped():
    """A nested mapping under a key must not appear in the result dict."""
    content = "---\nname: skill\nmetadata:\n  version: 1.0\n  author: alice\n---\n"
    result = parse_frontmatter(content)
    assert result.get("name") == "skill"
    assert "metadata" not in result
    assert "version" not in result


def test_nested_mapping_and_list_coexist():
    """A valid list key and a skipped nested mapping may coexist in the same frontmatter."""
    content = "---\ntags:\n  - python\nmetadata:\n  version: 1.0\nname: skill\n---\n"
    result = parse_frontmatter(content)
    assert result.get("tags") == ["python"]
    assert "metadata" not in result
    assert result.get("name") == "skill"


# ---------------------------------------------------------------------------
# Scenario: Arbitrary input never raises
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "---\n---\n",  # empty frontmatter
        "---\n  \n---\n",  # only whitespace
        "---\nkey: " + ("x" * 10_000) + "\n---\n",  # very long value
        "---\n\x00\x01\x02\n---\n",  # null bytes
        "---\n" + "a: b\n" * 500 + "---\n",  # many keys
        "not yaml at all",
        "",
    ],
)
def test_never_raises_on_arbitrary_input(content: str):
    """parse_frontmatter must never raise regardless of the input."""
    result = parse_frontmatter(content)
    assert isinstance(result, dict)

"""Tests for the JSONC comment stripper."""

from skills_mcp.config.loader import strip_jsonc


def test_plain_json_unchanged():
    result = strip_jsonc('{"key": "value"}')
    assert result.strip() == '{"key": "value"}'


def test_line_comment_removed():
    src = '{"key": "value"} // this is a comment\n'
    result = strip_jsonc(src)
    assert "//" not in result
    assert '"value"' in result


def test_block_comment_removed():
    src = '{"key": /* comment */ "value"}'
    result = strip_jsonc(src)
    assert "/*" not in result
    assert '"value"' in result


def test_url_in_string_preserved():
    """'//' inside a string literal must NOT be stripped."""
    src = '{"url": "https://github.com/foo/bar"}'
    result = strip_jsonc(src)
    import json

    data = json.loads(result)
    assert data["url"] == "https://github.com/foo/bar"


def test_comment_containing_url_stripped():
    """A '//' comment that itself mentions a URL is still stripped."""
    src = '{"key": "value"} // see https://example.com\n{"other": 1}'
    result = strip_jsonc(src)
    assert "example.com" not in result
    assert '"value"' in result


def test_trailing_comma_before_brace():
    src = '{"a": 1, "b": 2,}'
    import json

    result = strip_jsonc(src)
    data = json.loads(result)
    assert data == {"a": 1, "b": 2}


def test_trailing_comma_before_bracket():
    src = "[1, 2, 3,]"
    import json

    result = strip_jsonc(src)
    data = json.loads(result)
    assert data == [1, 2, 3]


def test_escaped_quote_inside_string():
    """A '\"' inside a string must not end the string early."""
    src = r'{"key": "va\"lue"}'
    import json

    result = strip_jsonc(src)
    data = json.loads(result)
    assert data["key"] == 'va"lue'


def test_block_comment_multiline():
    src = '{"a": /* this\n   is\n   multiline */ 42}'
    import json

    result = strip_jsonc(src)
    data = json.loads(result)
    assert data["a"] == 42


def test_comment_in_string_not_stripped():
    """A string value containing '//' must pass through intact."""
    src = '{"path": "//server/share"}'
    import json

    result = strip_jsonc(src)
    data = json.loads(result)
    assert data["path"] == "//server/share"

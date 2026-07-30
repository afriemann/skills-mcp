"""Minimal SKILL.md frontmatter parser.

Parses the YAML-like block between the first pair of ``---`` delimiters.

Supported grammar (top-level keys only):
  - Bare scalar values: ``key: value  # inline hash NOT stripped``
  - Single-quoted scalars: ``key: 'value'`` (``''`` is the escape for a literal ``'``)
  - Double-quoted scalars: ``key: "value"``
  - Block lists: a ``key:`` line followed by ``  - item`` lines
  - Full-line comments: lines whose first non-whitespace character is ``#``

Explicitly unsupported (silently skipped):
  - Nested mappings (``key:\\n  sub: val``)
  - Multi-line block scalars (``|``/``>``)
  - Inline ``#`` stripping from bare scalar values — inline hashes are preserved verbatim

Never raises.
"""

from __future__ import annotations


def parse_frontmatter(content: str) -> dict[str, object]:
    """Return a dict of top-level frontmatter keys parsed from *content*.

    Returns an empty dict when *content* has no frontmatter, is empty, or
    cannot be parsed.  Malformed input is silently skipped — this function
    never raises.
    """
    result: dict[str, object] = {}
    if not content:
        return result

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return result

    # State
    current_list_key: str | None = None  # key whose list is being built
    current_list: list[object] | None = None  # the actual list object being appended to
    in_skip_block: bool = False  # True while inside a nested mapping

    for line in lines[1:]:
        stripped = line.strip()

        # End of frontmatter
        if stripped == "---":
            break

        # Empty lines: keep state, continue
        if not stripped:
            continue

        # Full-line comments
        if stripped.startswith("#"):
            continue

        is_indented = len(line) > 0 and line[0] in (" ", "\t")

        if is_indented:
            if current_list_key is None:
                # Indented line before any key — skip
                continue
            if in_skip_block:
                # Inside a nested mapping block — skip
                continue
            if stripped.startswith("- "):
                # Block list item
                item = stripped[2:].strip()
                if current_list is not None:
                    current_list.append(item)
                else:
                    new_list: list[object] = [item]
                    result[current_list_key] = new_list
                    current_list = new_list
            else:
                # Indented non-list line → nested mapping detected
                in_skip_block = True
                result.pop(current_list_key, None)
                current_list = None
        else:
            # Top-level line — reset list/skip state
            current_list_key = None
            current_list = None
            in_skip_block = False

            if ":" not in stripped:
                continue

            key, _, raw_val = stripped.partition(":")
            key = key.strip()
            raw_val = raw_val.strip()

            if not key:
                continue

            if raw_val == "":
                # Could be block list or nested mapping — wait for first child line
                current_list_key = key
            elif raw_val.startswith("'"):
                # Single-quoted scalar
                if len(raw_val) >= 2 and raw_val.endswith("'"):
                    result[key] = raw_val[1:-1].replace("''", "'")
                # else malformed quote — skip
            elif raw_val.startswith('"'):
                # Double-quoted scalar
                if len(raw_val) >= 2 and raw_val.endswith('"'):
                    result[key] = raw_val[1:-1]
                # else malformed — skip
            else:
                # Bare scalar: inline # is NOT stripped (per design D1)
                result[key] = raw_val

    return result

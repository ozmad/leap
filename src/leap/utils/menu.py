"""Shared parsing for numbered-menu options in CLI dialog prompts.

Used by:
  * the server's auto-approve and ``select_option``/``custom_answer`` handlers
  * the monitor's right-click "permission options" menu

Single source of truth for the regex — Claude's provider exposes the same
pattern via ``menu_option_regex`` so callers that pass a provider get
identical behavior.
"""
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from leap.cli_providers.base import CLIProvider


# Match "<digit>. <label>" (normal Ink TUI) OR "<digit>  <label>" with 2+
# spaces (corruption: when overlapping pyte frames overwrite the cell that
# held the period, the visible separator is just the cells that nothing
# was redrawn into).  The leading "cursor/border garbage" group accepts
# ZERO OR MORE clusters of non-digit-non-space chars (each optionally
# separated by horizontal whitespace) so that:
#   * "❯s" (a stale "s" cell stuck next to the cursor) still parses
#   * "│ ❯ 1. Yes" (bordered Ink dialog: border + space + cursor + space
#     + digit) parses — without this the SELECTED row of a bordered
#     menu would silently drop out of the parsed options, while the
#     unselected rows (single border cluster only) still parsed, so
#     auto-approve could not find option 1's "Yes" and the dialog
#     would sit indefinitely
#   * "❯ ❯ 1. Yes" (double-cursor overdraw from re-rendered frames)
#     parses
# Single-space separators between digit and label are still rejected
# so phrases like "1 file changed" / "12 minutes remaining" in
# conversational text do NOT get parsed as menu options.  The
# letters-only "Yes" check in auto-approve is the safety net for the
# broader prefix: prose that does now parse as a menu option (e.g.
# inline "The plan is: 1. read file") yields a label whose letters
# don't reduce to "yes", so auto-approve still refuses to act on it.
#
# **Possessive quantifiers (`++`, `*+`) are required.**  The plain-`*`
# form would catastrophically backtrack on no-match lines that contain
# a mid-sentence period (e.g. "Claude has written up a plan. Would
# you like to proceed?") — the regex engine explores exponentially
# many ways to split the prefix into clusters before giving up.  The
# possessive form commits each cluster greedily and never backtracks
# into the prefix, so no-match lines fail in O(n) instead of hanging
# the auto-sender thread.  Verified safe on Python 3.11+ (Leap's
# minimum); earlier interpreters would silently re-introduce the
# blowup since they treat `++` as a syntax error and fall back to
# greedy — pyproject.toml's python = "^3.11" gate prevents that.
MENU_OPTION_RE: re.Pattern[str] = re.compile(
    r'\s*(?:[^\d\s]++\s*+)*+(\d+)(?:\.[^\w\n]+|[ \t]{2,})(.+)'
)


def extract_menu_options(
    prompt_output: str,
    provider: Optional['CLIProvider'] = None,
) -> list[tuple[int, str]]:
    """Extract numbered menu options from prompt output.

    The prompt may contain numbered content (e.g. plan steps) above the
    actual TUI options.  Both match the ``N. label`` pattern, so we
    return only the **last** contiguous 1..n sequence — the real menu.

    Args:
        prompt_output: Rendered prompt text.
        provider: CLI provider whose ``menu_option_regex`` overrides
            ``MENU_OPTION_RE`` if it returns a non-None pattern.  When
            ``provider`` is given and does not use numbered menus, the
            function returns ``[]`` immediately.
    """
    if provider and not provider.has_numbered_menus:
        return []

    pattern = (
        provider.menu_option_regex
        if provider and provider.menu_option_regex
        else MENU_OPTION_RE
    )

    all_matches: list[tuple[int, str]] = []
    for line in prompt_output.split('\n'):
        m = pattern.match(line)
        if m:
            all_matches.append((int(m.group(1)), m.group(2).strip()))

    if not all_matches:
        return []

    # Walk backwards to the last match numbered "1".
    last_one_idx = -1
    for i in range(len(all_matches) - 1, -1, -1):
        if all_matches[i][0] == 1:
            last_one_idx = i
            break

    if last_one_idx == -1:
        return all_matches  # no "1" found — return all as fallback

    # Take the contiguous ascending sequence from that point.
    result: list[tuple[int, str]] = []
    expected = 1
    for i in range(last_one_idx, len(all_matches)):
        num, label = all_matches[i]
        if num == expected:
            result.append((num, label))
            expected += 1
        else:
            break

    return result

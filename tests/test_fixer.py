"""Tests for the Fixer transformations."""

import pytest
import mwparserfromhell

from cwfix.fixer import (
    fix_simple_bold,
    fix_bold_italic,
    fix_bold_link,
    fix_all_identical,
    make_edit_summary,
    generate_diff,
    DEFAULT_EDIT_SUMMARY,
)


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def wikitext_simple():
    return "The event is called <b>25.1</b> and it's an AMRAP."


@pytest.fixture
def wikitext_bold_italic():
    return '! colspan="8" | {{center|<b>\'\'Elected unopposed\'\'</b>}}'


@pytest.fixture
def wikitext_bold_link():
    return "See <b>[[Main Page]]</b> for details."


@pytest.fixture
def wikitext_bold_link_italic():
    return "See <b>\'\'[[The Great Gatsby]]\'\'</b> for details."


@pytest.fixture
def wikitext_multiple_identical():
    return """| 15 || Sampagaon II || -
! colspan="8" | {{center|<b>''Elected unopposed''</b>}}
|-
| 60 || Afzalpur || -
! colspan="8" | {{center|<b>''Elected unopposed''</b>}}
|-
| 66 || Shahapur || -
! colspan="8" | {{center|<b>''Elected unopposed''</b>}}
"""


@pytest.fixture
def wikitext_multiple_mixed():
    return """<b>Section header</b>
{{center|<b>\'\'Elected unopposed\'\'</b>}}
Some <b>bold word</b> here.
{{center|<b>\'\'Also unopposed\'\'</b>}}
"""


# ─── Tests: Simple bold ────────────────────────────────────────────


def test_fix_simple_bold(wikitext_simple):
    """<b>text</b> → '''text'''"""
    result = fix_simple_bold(wikitext_simple)
    assert '<b>' not in result
    assert '</b>' not in result
    assert "'''25.1'''" in result


def test_fix_simple_bold_preserves_surrounding(wikitext_simple):
    """Surrounding text must be preserved."""
    result = fix_simple_bold(wikitext_simple)
    assert result.startswith("The event is called")
    assert result.endswith("and it's an AMRAP.")


def test_fix_simple_bold_multiple_occurrences():
    """Multiple different <b>...</b> in same text."""
    text = "First <b>bold</b> and second <b>bold2</b>."
    result = fix_simple_bold(text)
    assert "'''bold'''" in result
    assert "'''bold2'''" in result
    assert '<b>' not in result


# ─── Tests: Bold italic ────────────────────────────────────────────


def test_fix_bold_italic(wikitext_bold_italic):
    """<b>''text''</b> → '''''text'''''"""
    result = fix_bold_italic(wikitext_bold_italic)
    assert '<b>' not in result
    assert '</b>' not in result
    # Should become 5 apostrophes
    assert "'''''Elected unopposed'''''" in result


def test_fix_bold_italic_preserves_template(wikitext_bold_italic):
    """Surrounding template markup preserved."""
    result = fix_bold_italic(wikitext_bold_italic)
    assert "{{center|" in result
    assert "}}" in result


def test_fix_bold_italic_twice():
    """Two bold-italic patterns."""
    text = '{{c|<b>\'\'one\'\'</b>}} {{c|<b>\'\'two\'\'</b>}}'
    result = fix_bold_italic(text)
    assert result == "{{c|'''''one'''''}} {{c|'''''two'''''}}"


# ─── Tests: Bold link ──────────────────────────────────────────────


def test_fix_bold_link(wikitext_bold_link):
    """<b>[[link]]</b> → '''[[link]]'''"""
    result = fix_bold_link(wikitext_bold_link)
    assert '<b>' not in result
    assert '</b>' not in result
    assert "'''[[Main Page]]'''" in result


def test_fix_bold_link_italic(wikitext_bold_link_italic):
    """<b>''[[link]]''</b> → '''''[[link]]'''''"""
    result = fix_bold_link(wikitext_bold_link_italic)
    assert '<b>' not in result
    assert '</b>' not in result
    assert "'''''[[The Great Gatsby]]'''''" in result


def test_fix_bold_link_with_pipe():
    """<b>[[link|text]]</b> → '''[[link|text]]'''"""
    text = "Visit <b>[[Main Page|the homepage]]</b> now."
    result = fix_bold_link(text)
    assert "'''[[Main Page|the homepage]]'''" in result


# ─── Tests: Batch identical ────────────────────────────────────────


def test_fix_all_identical(wikitext_multiple_identical):
    """Fix all occurrences of the same pattern."""
    pattern = '{{center|<b>\'\'Elected unopposed\'\'</b>}}'
    replacement = "{{center|'''''Elected unopposed'''''}}"
    result = fix_all_identical(
        wikitext_multiple_identical,
        pattern,
        replacement,
    )
    assert result.count(replacement) == 3
    assert '<b>' not in result


def test_fix_all_identical_no_pattern():
    """If pattern doesn't exist, text is unmodified."""
    text = "Just some <b>text</b> here."
    result = fix_all_identical(text, "<b>nope</b>", "'''nope'''")
    assert result == text


def test_fix_all_identical_partial_pattern():
    """Pattern that is a substring of a larger match should only fix exact matches."""
    text = "<b>foo</b> and <b>foobar</b>"
    result = fix_all_identical(text, "<b>foo</b>", "'''foo'''")
    # Both contain "foo" but only exact "<b>foo</b>" should match
    assert "'''foo'''" in result
    # <b>foobar</b> should remain unchanged (not exact match)
    assert "<b>foobar</b>" in result


# ─── Tests: Edit summary ──────────────────────────────────────────


def test_make_edit_summary_default():
    """Default edit summary for error #26."""
    summary = make_edit_summary('26')
    assert summary == DEFAULT_EDIT_SUMMARY


def test_make_edit_summary_custom():
    """Edit summary for a different error."""
    summary = make_edit_summary('38')
    assert '38' in summary
    assert '<i>' in summary or 'italics' in summary


def test_make_edit_summary_with_count():
    """Edit summary with occurrence count."""
    summary = make_edit_summary('26', count=22)
    assert '22' in summary
    assert DEFAULT_EDIT_SUMMARY in summary


# ─── Tests: Diff generation ────────────────────────────────────────


def test_generate_diff(wikitext_simple):
    """Diff should show old and new text."""
    new_text = fix_simple_bold(wikitext_simple)
    diff = generate_diff(wikitext_simple, new_text)
    assert '<b>25.1</b>' in diff
    assert "'''25.1'''" in diff


def test_generate_diff_no_changes():
    """Diff of identical text should be empty."""
    text = "No changes here."
    diff = generate_diff(text, text)
    assert diff == '' or diff is None or 'no changes' in diff.lower()

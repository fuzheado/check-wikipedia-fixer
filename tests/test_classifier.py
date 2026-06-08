"""Tests for the Classification engine."""

import pytest
import mwparserfromhell

from cwfix.classifier import (
    Classification,
    classify_wikitext,
    classify_tag_from_ast,
    SAFE_TEMPLATES,
    RISKY_TEMPLATES,
)


# ─── Fixtures: Wikitext snippets for each pattern ───────────────────────


@pytest.fixture
def wikitext_simple_bold():
    """Pattern A: Simple bold in prose."""
    return "The event is called <b>25.1</b> and it's an AMRAP."


@pytest.fixture
def wikitext_bold_italic():
    """Pattern B: Bold wrapping italic."""
    return '! colspan="8" | {{center|<b>\'\'Elected unopposed\'\'</b>}}'


@pytest.fixture
def wikitext_bold_link():
    """Pattern C: Bold wrapping a wiki link."""
    return "See <b>[[Main Page]]</b> for details."


@pytest.fixture
def wikitext_template_param_risky():
    """Pattern C variant: <b> inside OSM Location map template."""
    return "{{OSM Location map|legendItem1=<b>Morocco</b>,1|legendItem2=<b>Portugal</b>,7}}"


@pytest.fixture
def wikitext_template_param_safe():
    """<b> inside a template known to accept wiki markup."""
    return "{{center|<b>Header text</b>}}"


@pytest.fixture
def wikitext_no_close():
    """Pattern D: <b> without matching </b>."""
    return "Some stray <b> with no close tag."


@pytest.fixture
def wikitext_inside_nowiki():
    """Pattern E: Inside <nowiki>."""
    return "<nowiki>Some <b>example</b> code</nowiki>"


@pytest.fixture
def wikitext_inside_comment():
    """Pattern E variant: Inside HTML comment."""
    return "<!-- <b>this is not rendering</b> --> visible text"


@pytest.fixture
def wikitext_inside_code():
    """Pattern E variant: Inside <code>."""
    return "Use <code>&lt;b&gt;text&lt;/b&gt;</code> for bold."


@pytest.fixture
def wikitext_inside_infobox():
    """<b> inside an Infobox template parameter."""
    return "{{Infobox|name=<b>bold title</b>|data=some data}}"


@pytest.fixture
def wikitext_multiple_patterns():
    """Article with multiple <b> tags of different types."""
    return """The event is called <b>25.1</b> and it's an AMRAP.
See <b>[[Main Page]]</b> for details.
{{center|<b>\'\'Elected unopposed\'\'</b>}}
<nowiki>literal <b>text</b></nowiki>
Some stray <b> tag
"""


@pytest.fixture
def wikitext_self_closing_b():
    """Edge case: self-closing or malformed <b/>."""
    return "Line break here.<b/>"


@pytest.fixture
def wikitext_empty_b():
    """Edge case: empty <b></b>."""
    return "Some text.<b></b>More text."


@pytest.fixture
def wikitext_bold_template_inside():
    """Bold wrapping a template call."""
    return "The result was <b>{{value|42}}</b> points."


@pytest.fixture
def wikitext_bold_nested_markup():
    """Bold with nested markup: link + italic."""
    return "See <b>\'\'[[The Great Gatsby]]\'\'</b> for details."


# ─── Tests: Classification of individual <b> tags ────────────────────


def test_simple_bold(wikitext_simple_bold):
    """SAFE_SIMPLE: bare <b>text</b> in prose."""
    results = classify_wikitext(wikitext_simple_bold)
    assert len(results) == 1
    assert results[0].classification == Classification.SAFE_SIMPLE


def test_bold_italic(wikitext_bold_italic):
    """SAFE_BOLD_ITALIC: <b>''text''</b> in table cell."""
    results = classify_wikitext(wikitext_bold_italic)
    # Should find the one <b> tag
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) >= 1
    # The <b> wrapping italic should be BI
    bi = [r for r in b_tags if r.classification == Classification.SAFE_BOLD_ITALIC]
    assert len(bi) >= 1, f"Expected BOLD_ITALIC, got: {[r.classification for r in b_tags]}"


def test_bold_link(wikitext_bold_link):
    """SAFE_NESTED: <b>[[link]]</b>."""
    results = classify_wikitext(wikitext_bold_link)
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) == 1
    assert b_tags[0].classification == Classification.SAFE_NESTED


def test_template_param_risky(wikitext_template_param_risky):
    """TEMPLATE_PARAM: <b> inside OSM Location map."""
    results = classify_wikitext(wikitext_template_param_risky)
    b_tags = [r for r in results if r.tag == 'b']
    # Both <b> tags should be TEMPLATE_PARAM
    for t in b_tags:
        assert t.classification == Classification.TEMPLATE_PARAM, (
            f"Expected TEMPLATE_PARAM, got {t.classification}"
        )


def test_template_param_safe(wikitext_template_param_safe):
    """<b> inside a safe template should fall through to content analysis."""
    results = classify_wikitext(wikitext_template_param_safe)
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) >= 1
    # {{center}} is in SAFE_TEMPLATES, so this should be SAFE_SIMPLE
    assert b_tags[0].classification == Classification.SAFE_SIMPLE


def test_no_close_tag(wikitext_no_close):
    """NO_CLOSE_TAG: unmatched <b>."""
    results = classify_wikitext(wikitext_no_close)
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) == 1
    assert b_tags[0].classification == Classification.NO_CLOSE_TAG


def test_inside_nowiki(wikitext_inside_nowiki):
    """INSIDE_NOWIKI: <b> inside <nowiki>."""
    results = classify_wikitext(wikitext_inside_nowiki)
    b_tags = [r for r in results if r.tag == 'b']
    # The <b> tags inside nowiki should be classified as INSIDE_NOWIKI
    for t in b_tags:
        assert t.classification == Classification.INSIDE_NOWIKI


def test_inside_comment(wikitext_inside_comment):
    """INSIDE_NOWIKI: <b> inside HTML comment."""
    results = classify_wikitext(wikitext_inside_comment)
    b_tags = [r for r in results if r.tag == 'b']
    for t in b_tags:
        assert t.classification == Classification.INSIDE_NOWIKI


def test_inside_code(wikitext_inside_code):
    """INSIDE_NOWIKI: <b> inside <code>."""
    results = classify_wikitext(wikitext_inside_code)
    b_tags = [r for r in results if r.tag == 'b']
    for t in b_tags:
        assert t.classification == Classification.INSIDE_NOWIKI


def test_inside_infobox(wikitext_inside_infobox):
    """TEMPLATE_PARAM: <b> inside Infobox."""
    results = classify_wikitext(wikitext_inside_infobox)
    b_tags = [r for r in results if r.tag == 'b']
    for t in b_tags:
        assert t.classification == Classification.TEMPLATE_PARAM


def test_multiple_patterns(wikitext_multiple_patterns):
    """Multiple <b> tags with different classifications."""
    results = classify_wikitext(wikitext_multiple_patterns)
    b_tags = [r for r in results if r.tag == 'b']

    # We should find multiple <b> tags
    classifications = {r.classification for r in b_tags}
    assert Classification.SAFE_SIMPLE in classifications, f"Missing SAFE_SIMPLE in {classifications}"
    assert Classification.SAFE_BOLD_ITALIC in classifications, f"Missing SAFE_BOLD_ITALIC in {classifications}"
    assert Classification.SAFE_NESTED in classifications, f"Missing SAFE_NESTED in {classifications}"
    assert Classification.INSIDE_NOWIKI in classifications, f"Missing INSIDE_NOWIKI in {classifications}"

    # The stray <b> should be NO_CLOSE_TAG
    ncs = [r for r in b_tags if r.classification == Classification.NO_CLOSE_TAG]
    assert len(ncs) == 1

    # Count total (5 <b> opening tags in the fixture)
    assert len(b_tags) >= 5, f"Expected 5+ b tags, got {len(b_tags)}"


def test_self_closing_b(wikitext_self_closing_b):
    """NO_CLOSE_TAG: self-closing <b/>."""
    results = classify_wikitext(wikitext_self_closing_b)
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) == 1
    assert b_tags[0].classification == Classification.NO_CLOSE_TAG


def test_empty_b(wikitext_empty_b):
    """NO_CLOSE_TAG: empty <b></b> (no content)."""
    results = classify_wikitext(wikitext_empty_b)
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) == 1
    assert b_tags[0].classification == Classification.NO_CLOSE_TAG


def test_bold_template_inside(wikitext_bold_template_inside):
    """SAFE_NESTED: <b>{{template}}</b>."""
    results = classify_wikitext(wikitext_bold_template_inside)
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) == 1
    assert b_tags[0].classification == Classification.SAFE_NESTED


def test_bold_nested_markup(wikitext_bold_nested_markup):
    """SAFE_NESTED: <b>''[[link]]''</b>."""
    results = classify_wikitext(wikitext_bold_nested_markup)
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) == 1
    assert b_tags[0].classification == Classification.SAFE_NESTED


# ─── Tests: No <b> tag ──────────────────────────────────────────────


def test_no_b_tags():
    """Article with no <b> tags returns empty list."""
    wikitext = "This is a normal article with '''bold''' markup."
    results = classify_wikitext(wikitext)
    assert len(results) == 0


def test_wiki_bold_not_confused():
    """'''bold''' should not be confused with <b>."""
    wikitext = "This has '''wiki bold''' and <b>HTML bold</b>."
    results = classify_wikitext(wikitext)
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) == 1  # Only the HTML <b>, not the '''
    assert b_tags[0].classification == Classification.SAFE_SIMPLE


# ─── Tests: classify_tag_from_ast (direct unit test) ─────────────────


def test_unknown_template_defaults_to_risky():
    """An unknown template should default to TEMPLATE_PARAM."""
    wikitext = "{{UnknownTemplate|param=<b>bold</b>}}"
    results = classify_wikitext(wikitext)
    b_tags = [r for r in results if r.tag == 'b']
    assert len(b_tags) == 1
    # Unknown template → cautious default of TEMPLATE_PARAM
    assert b_tags[0].classification == Classification.TEMPLATE_PARAM


# ─── Tests: Template registry ──────────────────────────────────────


def test_safe_templates_are_known():
    """Known safe templates should exist in the set."""
    assert 'center' in SAFE_TEMPLATES
    assert 'align' in SAFE_TEMPLATES


def test_risky_templates_are_known():
    """Known risky templates should exist in the set."""
    assert 'OSM Location map' in RISKY_TEMPLATES
    assert 'Infobox' in RISKY_TEMPLATES


def test_safe_template_not_in_risky():
    """No overlap between safe and risky template sets."""
    overlap = SAFE_TEMPLATES & RISKY_TEMPLATES
    assert len(overlap) == 0, f"Templates in both sets: {overlap}"

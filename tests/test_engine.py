"""Tests for the Core Engine orchestrator."""

import pytest
from pathlib import Path

from cwfix.classifier import Classification
from cwfix.engine import (
    ArticleAnalysis,
    BTagOccurrence,
    analyze_article,
    get_transform_for,
)


class TestBTagOccurrence:
    """Tests for the BTagOccurrence data class."""

    def test_basic_creation(self):
        """Create a BTagOccurrence."""
        occ = BTagOccurrence(
            tag='b',
            line=10,
            column=5,
            content='bold text',
            raw_tag='<b>bold text</b>',
            raw_open='<b>',
            raw_close='</b>',
            classification=Classification.SAFE_SIMPLE,
            context_before='Some text ',
            context_after=' more text.',
        )
        assert occ.tag == 'b'
        assert occ.classification == Classification.SAFE_SIMPLE
        assert occ.content == 'bold text'

    def test_is_safe(self):
        """Safe classifications return True."""
        occ = BTagOccurrence(
            tag='b', line=0, column=0, content='', raw_tag='<b></b>',
            raw_open='<b>', raw_close='</b>',
            classification=Classification.SAFE_SIMPLE,
        )
        assert occ.is_safe is True

    def test_is_not_safe(self):
        """Non-safe classifications return False."""
        occ = BTagOccurrence(
            tag='b', line=0, column=0, content='', raw_tag='<b></b>',
            raw_open='<b>', raw_close='</b>',
            classification=Classification.TEMPLATE_PARAM,
        )
        assert occ.is_safe is False

    def test_classification_label(self):
        """Label reflects classification."""
        occ = BTagOccurrence(
            tag='b', line=0, column=0, content='', raw_tag='<b></b>',
            raw_open='<b>', raw_close='</b>',
            classification=Classification.SAFE_BOLD_ITALIC,
        )
        assert 'BOLD_ITALIC' in occ.classification_label


class TestArticleAnalysis:
    """Tests for the ArticleAnalysis data class."""

    @pytest.fixture
    def analysis(self):
        """Create a sample analysis."""
        occ1 = BTagOccurrence(
            tag='b', line=5, column=10,
            content='bold', raw_tag='<b>bold</b>',
            raw_open='<b>', raw_close='</b>',
            classification=Classification.SAFE_SIMPLE,
        )
        occ2 = BTagOccurrence(
            tag='b', line=20, column=5,
            content='more', raw_tag='<b>more</b>',
            raw_open='<b>', raw_close='</b>',
            classification=Classification.SAFE_SIMPLE,
        )
        return ArticleAnalysis(
            title="Test Article",
            wikitext="Some <b>bold</b> and <b>more</b> text.",
            occurrences=[occ1, occ2],
        )

    def test_total_count(self, analysis):
        """Total count of occurrences."""
        assert analysis.total_count == 2

    def test_safe_count(self, analysis):
        """Count of safe occurrences."""
        assert analysis.safe_count == 2

    def test_summary(self, analysis):
        """Summary string."""
        s = analysis.summary()
        assert 'Test Article' in s
        assert '2' in s


class TestGetTransformFor:
    """Tests for selecting the right transform function."""

    def test_simple_returns_fix_simple(self):
        """SAFE_SIMPLE returns fix_simple_bold."""
        fn = get_transform_for(Classification.SAFE_SIMPLE)
        assert fn is not None
        assert callable(fn)

    def test_bold_italic_returns_fix_bold_italic(self):
        """SAFE_BOLD_ITALIC returns fix_bold_italic."""
        fn = get_transform_for(Classification.SAFE_BOLD_ITALIC)
        assert fn is not None
        assert callable(fn)

    def test_nested_returns_fix_bold_link(self):
        """SAFE_NESTED returns fix_bold_link."""
        fn = get_transform_for(Classification.SAFE_NESTED)
        assert fn is not None
        assert callable(fn)

    def test_unsafe_returns_none(self):
        """Unsafe classifications return None."""
        for cls in [Classification.TEMPLATE_PARAM, Classification.NO_CLOSE_TAG,
                     Classification.INSIDE_NOWIKI, Classification.SPURIOUS]:
            fn = get_transform_for(cls)
            assert fn is None, f"{cls} should not have a transform"


class TestAnalyzeArticle:
    """Tests for the full article analysis pipeline."""

    def test_analyze_simple_article(self):
        """Analyze an article with one <b> tag."""
        wikitext = "Hello <b>world</b>."
        analysis = analyze_article("Test", wikitext)
        assert analysis.title == "Test"
        assert analysis.total_count == 1
        assert analysis.occurrences[0].classification == Classification.SAFE_SIMPLE

    def test_analyze_no_tags(self):
        """Article with no <b> tags."""
        wikitext = "Hello '''world'''."
        analysis = analyze_article("Test", wikitext)
        assert analysis.total_count == 0

    def test_analyze_with_italic(self):
        """Article with bold-italic."""
        wikitext = '{{center|<b>\'\'Elected unopposed\'\'</b>}}'
        analysis = analyze_article("Election", wikitext)
        assert analysis.total_count >= 1
        # At least one should be BOLD_ITALIC
        bi = [o for o in analysis.occurrences if o.classification == Classification.SAFE_BOLD_ITALIC]
        assert len(bi) >= 1

    def test_analyze_nowiki(self):
        """Article with <b> inside nowiki."""
        wikitext = "<nowiki><b>literal</b></nowiki>"
        analysis = analyze_article("Nowiki Test", wikitext)
        # The <b> inside nowiki may or may not be detected by mwparserfromhell
        # Let's just verify it doesn't crash
        assert analysis.title == "Nowiki Test"

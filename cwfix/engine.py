"""
Core engine — orchestrates fetching, classifying, fixing, and saving articles.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from cwfix.classifier import (
    Classification,
    ClassifiedTag,
    classify_wikitext,
    CLASSIFICATION_LABELS,
)
from cwfix.fixer import (
    fix_simple_bold,
    fix_bold_italic,
    fix_bold_link,
    fix_all_identical,
    make_edit_summary,
    generate_diff,
    apply_fix_for_classification,
    DEFAULT_EDIT_SUMMARY,
)

logger = logging.getLogger(__name__)


@dataclass
class BTagOccurrence:
    """
    A single <b> tag occurrence within an article, with classification
    and context for the user to review.
    """
    tag: str
    line: int
    column: int
    content: str
    raw_tag: str
    raw_open: str
    raw_close: str
    classification: Classification = Classification.SPURIOUS
    context_before: str = ''
    context_after: str = ''
    template_name: Optional[str] = None
    suggested_fix: Optional[str] = None

    @property
    def is_safe(self):
        return self.classification in (
            Classification.SAFE_SIMPLE,
            Classification.SAFE_BOLD_ITALIC,
            Classification.SAFE_NESTED,
        )

    @property
    def classification_label(self):
        return CLASSIFICATION_LABELS.get(self.classification, str(self.classification))


@dataclass
class ArticleAnalysis:
    """
    Full analysis of an article's <b> tags, ready for the TUI to present.
    """
    title: str
    wikitext: str
    occurrences: list = field(default_factory=list)
    url: str = ''

    @property
    def total_count(self):
        return len(self.occurrences)

    @property
    def safe_count(self):
        return sum(1 for o in self.occurrences if o.is_safe)

    @property
    def safe_occurrences(self):
        return [o for o in self.occurrences if o.is_safe]

    @property
    def unsafe_occurrences(self):
        return [o for o in self.occurrences if not o.is_safe]

    def summary(self):
        safe = self.safe_count
        total = self.total_count
        return (
            f"{self.title}: {total} <b> tag(s) "
            f"({safe} safe, {total - safe} needs review)"
        )


def analyze_article(title: str, wikitext: str, url: str = '') -> ArticleAnalysis:
    """
    Analyze an article's wikitext and classify all <b> tags.

    Args:
        title: Article title.
        wikitext: Raw wikitext content.
        url: Optional Wikipedia URL.

    Returns:
        ArticleAnalysis with all classified occurrences.
    """
    classified_tags = classify_wikitext(wikitext)

    occurrences = []
    lines = wikitext.splitlines(keepends=True)

    for ct in classified_tags:
        # Find line number
        line_num = ct.line_num or 1
        col_num = ct.col_num or 0

        # Extract context
        context_before = _extract_context(lines, line_num, before=3)
        context_after = _extract_context(lines, line_num + 1, after=3)

        # Generate suggested fix
        suggested_fix = _suggest_fix(ct, wikitext)

        occurrences.append(BTagOccurrence(
            tag=ct.tag,
            line=line_num,
            column=col_num,
            content=ct.content,
            raw_tag=ct.raw_tag,
            raw_open=ct.raw_open,
            raw_close=ct.raw_close,
            classification=ct.classification,
            context_before=context_before,
            context_after=context_after,
            template_name=ct.template_name,
            suggested_fix=suggested_fix,
        ))

    return ArticleAnalysis(
        title=title,
        wikitext=wikitext,
        occurrences=occurrences,
        url=url,
    )


def _extract_context(lines, start_line, before=2, after=2):
    """Extract context lines around a given line number."""
    start = max(0, start_line - before - 1)
    end = min(len(lines), start_line + after)
    return ''.join(lines[start:end])


def _suggest_fix(ct: ClassifiedTag, wikitext: str) -> Optional[str]:
    """
    Generate a suggested fix for a classified tag.

    Returns the replacement text, or None if no automatic fix is available.
    """
    if ct.classification == Classification.SAFE_SIMPLE:
        return f"'''{ct.content}'''"
    elif ct.classification == Classification.SAFE_BOLD_ITALIC:
        # <b>''text''</b> → '''''text'''''
        inner_text = ct.content.strip("'").strip()
        return f"'''''{inner_text}'''''"
    elif ct.classification == Classification.SAFE_NESTED:
        if '[[' in ct.content and "''" in ct.content:
            # <b>''[[link]]''</b>
            inner = ct.content.strip("'").strip()
            return f"'''''{inner}'''''"
        elif '[[' in ct.content:
            # <b>[[link]]</b>
            return f"'''{ct.content}'''"
        else:
            return f"'''{ct.content}'''"
    return None


def get_transform_for(classification: Classification):
    """
    Get the appropriate transform function for a classification.

    Returns a callable that takes wikitext and returns transformed wikitext,
    or None if no automatic transform exists.
    """
    mapping = {
        Classification.SAFE_SIMPLE: fix_simple_bold,
        Classification.SAFE_BOLD_ITALIC: fix_bold_italic,
        Classification.SAFE_NESTED: fix_bold_link,
    }
    return mapping.get(classification)


def fix_occurrence(wikitext: str, occurrence: BTagOccurrence) -> str:
    """
    Apply the fix for a single occurrence.

    Args:
        wikitext: Current wikitext.
        occurrence: The occurrence to fix.

    Returns:
        Updated wikitext.
    """
    if occurrence.classification == Classification.SAFE_SIMPLE:
        return fix_simple_bold(wikitext)
    elif occurrence.classification == Classification.SAFE_BOLD_ITALIC:
        return fix_bold_italic(wikitext)
    elif occurrence.classification == Classification.SAFE_NESTED:
        return fix_bold_link(wikitext)
    return wikitext


def fix_all_identical_pattern(wikitext: str, occurrence: BTagOccurrence) -> str:
    """
    Fix all occurrences of the exact same <b> pattern.

    Args:
        wikitext: Current wikitext.
        occurrence: The occurrence whose pattern to match.

    Returns:
        Updated wikitext.
    """
    old_pattern = occurrence.raw_tag
    new_text = occurrence.suggested_fix or ''
    if new_text:
        return fix_all_identical(wikitext, old_pattern, new_text)
    return wikitext


def fix_all_safe_occurrences(wikitext: str, analysis: ArticleAnalysis) -> str:
    """
    Fix all SAFE_* occurrences in the article.

    Applies the appropriate global fixer for each SAFE classification.
    This is more efficient than fixing one at a time since the fixers
    operate on all matching patterns at once.

    Args:
        wikitext: Current wikitext.
        analysis: Article analysis with classified occurrences.

    Returns:
        Updated wikitext.
    """
    result = wikitext

    # Collect which fixers to apply
    fixers_to_apply = set()
    for occ in analysis.safe_occurrences:
        fn = get_transform_for(occ.classification)
        if fn:
            fixers_to_apply.add(fn)

    # Apply each fixer once (they handle all matching patterns)
    for fixer in fixers_to_apply:
        result = fixer(result)

    return result

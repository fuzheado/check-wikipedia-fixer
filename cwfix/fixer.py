"""
Wikitext transformation functions for converting <b> to '''.

Each function takes wikitext and returns transformed wikitext.
"""

import re
import difflib


# Default edit summary for error #26
DEFAULT_EDIT_SUMMARY = "Checkwiki error #26: fix HTML <b> → wiki bold markup"


def fix_simple_bold(wikitext):
    """
    Convert <b>text</b> → '''text''' in wikitext.
    
    Handles multiple occurrences. Works via regex on the text level
    so it's robust regardless of AST parser behavior.
    """
    # Match <b>...</b> where ... does not contain <b>, </b>, wiki apostrophes,
    # wiki links, or template calls — pure text only
    pattern = re.compile(
        r'<b\b[^>]*>'
        r'([^<>\'\'\[\]{{}}]+?)'
        r'</b\s*>',
        re.IGNORECASE | re.DOTALL,
    )

    def replacer(m):
        content = m.group(1).strip()
        if content:
            return f"'''{content}'''"
        return m.group(0)  # preserve empty b tags

    return pattern.sub(replacer, wikitext)


def fix_bold_italic(wikitext):
    """
    Convert <b>''text''</b> → '''''text''''' in wikitext.
    
    Handles the common pattern of bold wrapping italic.
    """
    # Match <b>''text''</b> where the inner content is italic wiki markup
    pattern = re.compile(
        r'<b\b[^>]*>'
        r'(\'\'[^<>\']+?\'\')'
        r'</b\s*>',
        re.IGNORECASE | re.DOTALL,
    )

    def replacer(m):
        inner = m.group(1)
        # inner is ''text'' — we need '''''text'''''
        text = inner.strip("'")
        return f"'''''{text}'''''"

    return pattern.sub(replacer, wikitext)


def fix_bold_link(wikitext):
    """
    Convert <b>[[link]]</b> → '''[[link]]''' and
    <b>''[[link]]''</b> → '''''[[link]]''''' in wikitext.
    
    Handles wiki links, piped links, and links with optional italic wrapping.
    """
    # Case 1: <b>''[[link|text]]''</b> — bold + italic + link
    pattern_bi = re.compile(
        r'<b\b[^>]*>'
        r'(\'\'\[\[[^\]]+\]\]\'\')'
        r'</b\s*>',
        re.IGNORECASE | re.DOTALL,
    )

    def replacer_bi(m):
        inner = m.group(1)
        text = inner.strip("'").strip('[]')
        return f"'''''[[{text}]]'''''"

    result = pattern_bi.sub(replacer_bi, wikitext)

    # Case 2: <b>[[link]]</b> — bold + link only
    pattern_b = re.compile(
        r'<b\b[^>]*>'
        r'(\[\[[^\]]+\]\])'
        r'</b\s*>',
        re.IGNORECASE | re.DOTALL,
    )

    def replacer_b(m):
        inner = m.group(1)
        return f"'''{inner}'''"

    return pattern_b.sub(replacer_b, result)


def fix_all_identical(wikitext, old_pattern, new_text):
    """
    Replace all occurrences of an exact <b> pattern with new text.
    
    Uses exact string replacement, not regex, to avoid false matches.
    
    Args:
        wikitext: The full wikitext.
        old_pattern: The exact <b>...</b> string to find.
        new_text: The replacement string.
    
    Returns:
        Updated wikitext.
    """
    return wikitext.replace(old_pattern, new_text)


def make_edit_summary(error_id='26', count=None):
    """
    Generate an appropriate edit summary.
    
    Args:
        error_id: The CheckWiki error ID.
        count: Optional number of fixes made.
    
    Returns:
        Edit summary string.
    """
    summaries = {
        '26': DEFAULT_EDIT_SUMMARY,
        '38': "Checkwiki error #38: fix HTML <i> → wiki italic markup",
        '4': "Checkwiki error #4: fix HTML <a> → wiki link markup",
    }
    summary = summaries.get(error_id, f"Checkwiki error #{error_id}: fix HTML text style element")
    if count:
        summary = f"{summary} ({count} occurrences)"
    return summary


def generate_diff(old_text, new_text, context=3):
    """
    Generate a unified diff between old and new wikitext.
    
    Args:
        old_text: Original wikitext.
        new_text: Transformed wikitext.
        context: Number of context lines.
    
    Returns:
        String with unified diff, or empty string if no changes.
    """
    if old_text == new_text:
        return "(no changes)"

    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile='original',
        tofile='fixed',
        n=context,
    )

    return ''.join(diff)


def apply_fix_for_classification(wikitext, classification):
    """
    Apply the appropriate fix for a given classification.
    
    Args:
        wikitext: The wikitext to transform.
        classification: A Classification enum value.
    
    Returns:
        Transformed wikitext, or the original if no fix applies.
    """
    if classification is None:
        return wikitext

    # Import here to avoid circular imports
    from cwfix.classifier import Classification as C

    fix_map = {
        C.SAFE_SIMPLE: fix_simple_bold,
        C.SAFE_BOLD_ITALIC: fix_bold_italic,
        C.SAFE_NESTED: fix_bold_link,
    }

    fixer = fix_map.get(classification)
    if fixer:
        return fixer(wikitext)

    return wikitext

"""
Classification engine for CheckWiki Error #26.

Determines the context and safety of each <b> tag found in wikitext.
"""

import re
from enum import Enum, auto

import mwparserfromhell


class Classification(Enum):
    """Taxonomy of <b> tag contexts."""
    SAFE_SIMPLE = auto()       # <b>text</b> in prose — straightforward
    SAFE_BOLD_ITALIC = auto()  # <b>''text''</b> — nested bold + italic
    SAFE_NESTED = auto()       # <b>[[link]]</b> or <b>{{template}}</b>
    TEMPLATE_PARAM = auto()    # Inside template parameter — may need HTML
    NO_CLOSE_TAG = auto()      # Unmatched <b> — needs investigation
    INSIDE_NOWIKI = auto()     # Inside <nowiki>/<code>/<pre>/<!-- -->
    SPURIOUS = auto()          # Non-rendering or false positive


# Labels for human-readable display
CLASSIFICATION_LABELS = {
    Classification.SAFE_SIMPLE: "SAFE_SIMPLE",
    Classification.SAFE_BOLD_ITALIC: "SAFE_BOLD_ITALIC",
    Classification.SAFE_NESTED: "SAFE_NESTED",
    Classification.TEMPLATE_PARAM: "TEMPLATE_PARAM",
    Classification.NO_CLOSE_TAG: "NO_CLOSE_TAG",
    Classification.INSIDE_NOWIKI: "INSIDE_NOWIKI",
    Classification.SPURIOUS: "SPURIOUS",
}

# Templates known to safely accept wiki markup in their parameters
SAFE_TEMPLATES = frozenset({
    'center', 'align', 'color', 'font', 'small', 'big',
    'c',         # shortcut for {{center}}
    'font',
    'nowrap',
    'lang',
    'abbr',
    'tooltip',
})

# Templates where <b> may be necessary for rendering
RISKY_TEMPLATES = frozenset({
    'OSM Location map',
    'Location map',
    'location map',
    'legend',
    'Legend',
    'Infobox',
    'Infobox football biography',
    'Infobox person',
    'Infobox settlement',
    'Infobox country',
    'Infobox film',
    'Infobox television',
    'Infobox album',
    'Infobox book',
    'Infobox officeholder',
    'Infobox military conflict',
    'Infobox university',
    'Infobox company',
    'navbox',
    'Navbox',
    'Sidebar',
    'sidebar',
    'col-begin',
    'col-break',
    'col-end',
})


class ClassifiedTag:
    """Result of classifying a single <b> tag in wikitext."""

    def __init__(self, tag, classification, content, raw_open, raw_close,
                 raw_tag, line_num=0, col_num=0, context_before='',
                 context_after='', template_name=None, position=-1):
        self.tag = tag
        self.classification = classification
        self.content = content  # text between open and close tags
        self.raw_open = raw_open  # the <b> part
        self.raw_close = raw_close  # the </b> part
        self.raw_tag = raw_tag  # full <b>...</b>
        self.line_num = line_num
        self.col_num = col_num
        self.context_before = context_before
        self.context_after = context_after
        self.template_name = template_name
        self.position = position  # byte position in wikitext

    @property
    def classification_label(self):
        return CLASSIFICATION_LABELS.get(self.classification, str(self.classification))

    @property
    def is_safe(self):
        return self.classification in (
            Classification.SAFE_SIMPLE,
            Classification.SAFE_BOLD_ITALIC,
            Classification.SAFE_NESTED,
        )

    @property
    def is_skippable(self):
        return self.classification in (
            Classification.INSIDE_NOWIKI,
            Classification.SPURIOUS,
        )

    def __repr__(self):
        return (
            f"<ClassifiedTag {self.classification_label} "
            f"line={self.line_num} content={self.content!r}>"
        )


# ─── Context detection helpers ─────────────────────────────────────


def _is_inside_nowiki_in_comment(wikitext, position):
    """
    Check if a position in wikitext is inside a <nowiki>, <code>, <pre>,
    or <!-- --> block using raw text scanning.

    This is a position-based check that looks backwards from the tag
    position to see if we're inside one of these blocks.
    """
    # Scan backwards to find the most recent opening of nowiki/code/pre/comment
    # that isn't closed before our position
    text_before = wikitext[:position]

    # Check nowiki
    nowiki_opens = [m.end() for m in re.finditer(r'<nowiki>', text_before, re.IGNORECASE)]
    nowiki_closes = [m.start() for m in re.finditer(r'</nowiki>', text_before, re.IGNORECASE)]

    # Check code
    code_opens = [m.end() for m in re.finditer(r'<code>', text_before, re.IGNORECASE)]
    code_closes = [m.start() for m in re.finditer(r'</code>', text_before, re.IGNORECASE)]

    # Check pre
    pre_opens = [m.end() for m in re.finditer(r'<pre>', text_before, re.IGNORECASE)]
    pre_closes = [m.start() for m in re.finditer(r'</pre>', text_before, re.IGNORECASE)]

    # Check comments
    comment_opens = [m.end() for m in re.finditer(r'<!--', text_before)]
    comment_closes = [m.start() for m in re.finditer(r'-->', text_before)]

    for opens, closes in [
        (nowiki_opens, nowiki_closes),
        (code_opens, code_closes),
        (pre_opens, pre_closes),
        (comment_opens, comment_closes),
    ]:
        if opens and (not closes or opens[-1] > (closes[-1] if closes else -1)):
            return True

    return False


def _find_template_name_at(wikitext, position):
    """
    Check if a position is inside a template parameter value.
    Returns the template name if found, None otherwise.
    
    Walks backwards from position to find the most recent {{ that
    isn't closed by }} before our position.
    """
    text_before = wikitext[:position]

    # Find all {{ and }} positions
    open_positions = []
    i = 0
    while i < len(text_before) - 1:
        if text_before[i:i+2] == '{{':
            open_positions.append(i)
            i += 2
        elif text_before[i:i+2] == '}}':
            if open_positions:
                open_positions.pop()
            i += 2
        else:
            i += 1

    if not open_positions:
        return None

    # The innermost {{ that contains us
    innermost_open = open_positions[-1]
    after_open = text_before[innermost_open + 2:].strip()

    # Extract the template name (up to |, }, or newline)
    template_name = ''
    for ch in after_open:
        if ch in ('|', '}', '\n'):
            break
        template_name += ch
    template_name = template_name.strip()

    return template_name if template_name else None


# ─── Main entry point ─────────────────────────────────────────────


def classify_wikitext(wikitext):
    """
    Analyze wikitext and classify every <b> tag found.

    Args:
        wikitext: Raw wikitext string.

    Returns:
        List of ClassifiedTag objects, one per <b> tag.
    """
    if not wikitext:
        return []

    results = []

    # Use mwparserfromhell to get all tag nodes
    try:
        code = mwparserfromhell.parse(wikitext)
    except Exception:
        # If parsing fails, fall back to regex-based detection
        return _classify_fallback(wikitext)

    # filter_tags also catches wiki ''' bold markup (which it stores as
    # <b> tags with wiki_markup="'''"). We only want real HTML <b> tags,
    # which have wiki_markup=None.
    all_b_tags = list(code.filter_tags(matches=lambda t: t.tag == 'b'))
    tags = [t for t in all_b_tags if t.wiki_markup is None]

    for tag_node in tags:
        tag_position = _find_tag_position(wikitext, tag_node)
        line_num = wikitext[:tag_position].count('\n') + 1 if tag_position >= 0 else 0
        col_num = tag_position - wikitext.rfind('\n', 0, tag_position) if tag_position >= 0 else 0

        # Get raw tag text
        try:
            raw_tag = str(tag_node)
        except Exception:
            continue

        raw_open = _extract_open_tag(raw_tag)
        raw_close = _extract_close_tag(raw_tag)

        # Get content
        try:
            content = str(tag_node.contents) if tag_node.contents else ''
        except Exception:
            content = ''

        # --- Classification logic ---

        # 1. Check if inside nowiki/comment/code/pre
        if tag_position >= 0 and _is_inside_nowiki_in_comment(wikitext, tag_position):
            results.append(ClassifiedTag(
                tag='b', classification=Classification.INSIDE_NOWIKI,
                content=content, raw_open=raw_open, raw_close=raw_close,
                raw_tag=raw_tag, line_num=line_num, col_num=col_num,
                position=tag_position,
            ))
            continue

        # 2. Check if inside a template parameter
        template_name = None
        if tag_position >= 0:
            template_name = _find_template_name_at(wikitext, tag_position)

        if template_name and template_name not in SAFE_TEMPLATES:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.TEMPLATE_PARAM,
                content=content, raw_open=raw_open, raw_close=raw_close,
                raw_tag=raw_tag, line_num=line_num, col_num=col_num,
                template_name=template_name,
                position=tag_position,
            ))
            continue

        # 3. Check for closing tag / empty content
        stripped_content = content.strip()
        if not stripped_content or not raw_close:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.NO_CLOSE_TAG,
                content=content, raw_open=raw_open, raw_close=raw_close,
                raw_tag=raw_tag, line_num=line_num, col_num=col_num,
                position=tag_position,
            ))
            continue

        # 4. Analyze content
        has_italic = "''" in stripped_content
        has_wikilink = "[[" in stripped_content
        has_template_call = "{{" in stripped_content

        if not has_italic and not has_wikilink and not has_template_call:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.SAFE_SIMPLE,
                content=content, raw_open=raw_open, raw_close=raw_close,
                raw_tag=raw_tag, line_num=line_num, col_num=col_num,
                position=tag_position,
            ))
        elif has_italic and not has_wikilink and not has_template_call:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.SAFE_BOLD_ITALIC,
                content=content, raw_open=raw_open, raw_close=raw_close,
                raw_tag=raw_tag, line_num=line_num, col_num=col_num,
                position=tag_position,
            ))
        else:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.SAFE_NESTED,
                content=content, raw_open=raw_open, raw_close=raw_close,
                raw_tag=raw_tag, line_num=line_num, col_num=col_num,
                position=tag_position,
            ))

    # ── Supplement: Find tags mwparserfromhell cannot detect ──
    # mwparserfromhell cannot find: (1) <b> inside <nowiki> blocks,
    # (2) unmatched <b> tags (no closing </b>).
    # For everything else, mwparserfromhell already handled it.
    for match in re.finditer(r'<b\b[^>]*>', wikitext, re.IGNORECASE):
        pos = match.start()
        tag_str = match.group()
        line_num = wikitext[:pos].count('\n') + 1
        col_num = pos - (wikitext.rfind('\n', 0, pos) + 1)

        # Skip tags already found by mwparserfromhell (matched by position).
        already_found = any(r.position == pos for r in results)
        if already_found:
            continue

        if _is_inside_nowiki_in_comment(wikitext, pos):
            results.append(ClassifiedTag(
                tag='b', classification=Classification.INSIDE_NOWIKI,
                content='', raw_open=tag_str, raw_close='',
                raw_tag=tag_str, line_num=line_num, col_num=col_num,
                position=pos,
            ))
            continue

        # Check for closing tag to determine if unmatched
        rest = wikitext[pos + len(tag_str):]
        close_match = re.match(r'.*?</b\s*>', rest, re.IGNORECASE | re.DOTALL)
        if not close_match:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.NO_CLOSE_TAG,
                content='', raw_open=tag_str, raw_close='',
                raw_tag=tag_str, line_num=line_num, col_num=col_num,
                position=pos,
            ))

    return results


def classify_tag_from_ast(tag_node, wikitext):
    """
    Classify a single Tag node from mwparserfromhell.
    Convenience wrapper around classify_wikitext.
    
    Args:
        tag_node: An mwparserfromhell Tag node.
        wikitext: The full wikitext string (for context).
    
    Returns:
        Classification enum value.
    """
    results = classify_wikitext(wikitext)
    for r in results:
        if r.raw_tag == str(tag_node):
            return r.classification
    return Classification.SPURIOUS


# ─── Fallback regex-based classifier ──────────────────────────────


def _classify_fallback(wikitext):
    """
    Fallback classifier that uses regex when mwparserfromhell fails.
    Less accurate but still functional.
    """
    results = []
    pattern = re.compile(r'<b\b[^>]*>(.*?)</b\s*>', re.IGNORECASE | re.DOTALL)

    for match in pattern.finditer(wikitext):
        position = match.start()
        content = match.group(1)
        raw_tag = match.group(0)
        line_num = wikitext[:position].count('\n') + 1

        # Check if inside nowiki/comment
        if _is_inside_nowiki_in_comment(wikitext, position):
            results.append(ClassifiedTag(
                tag='b', classification=Classification.INSIDE_NOWIKI,
                content=content, raw_open='<b>', raw_close='</b>',
                raw_tag=raw_tag, line_num=line_num,
            ))
            continue

        # Check template context
        template_name = _find_template_name_at(wikitext, position)
        if template_name and template_name not in SAFE_TEMPLATES:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.TEMPLATE_PARAM,
                content=content, raw_open='<b>', raw_close='</b>',
                raw_tag=raw_tag, line_num=line_num,
                template_name=template_name,
            ))
            continue

        # Analyze content
        stripped = content.strip()
        if not stripped:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.NO_CLOSE_TAG,
                content=content, raw_open='<b>', raw_close='</b>',
                raw_tag=raw_tag, line_num=line_num,
            ))
        elif "''" in stripped:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.SAFE_BOLD_ITALIC,
                content=content, raw_open='<b>', raw_close='</b>',
                raw_tag=raw_tag, line_num=line_num,
            ))
        elif "[[" in stripped:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.SAFE_NESTED,
                content=content, raw_open='<b>', raw_close='</b>',
                raw_tag=raw_tag, line_num=line_num,
            ))
        else:
            results.append(ClassifiedTag(
                tag='b', classification=Classification.SAFE_SIMPLE,
                content=content, raw_open='<b>', raw_close='</b>',
                raw_tag=raw_tag, line_num=line_num,
            ))

    # Find unmatched <b> tags (no closing </b>)
    # mwparserfromhell only returns properly paired tags, so unmatched
    # <b> tags need separate detection.
    matched_ranges = []
    for r in results:
        pos = wikitext.find(r.raw_tag)
        if pos >= 0:
            matched_ranges.append((pos, pos + len(r.raw_tag)))

    for um in re.finditer(r'<b\b[^>]*>', wikitext, re.IGNORECASE):
        pos = um.start()
        already = any(start <= pos < end for start, end in matched_ranges)
        if already:
            continue
        # Check if this <b> has a closing </b> somewhere after it
        rest = wikitext[pos + len(um.group()):]
        has_close = bool(re.match(r'.*?</b\s*>', rest, re.IGNORECASE | re.DOTALL))
        if not has_close:
            line = wikitext[:pos].count('\n') + 1
            col = pos - (wikitext.rfind('\n', 0, pos) + 1)
            results.append(ClassifiedTag(
                tag='b', classification=Classification.NO_CLOSE_TAG,
                content='', raw_open=um.group(), raw_close='',
                raw_tag=um.group(), line_num=line, col_num=col,
            ))

    return results


# ─── Helpers ──────────────────────────────────────────────────────


def _find_tag_position(wikitext, tag_node):
    """Find the position of a tag node in the wikitext."""
    try:
        tag_str = str(tag_node)
        pos = wikitext.find(tag_str)
        if pos >= 0:
            return pos
        # Try just the opening tag
        for m in re.finditer(r'<b\b[^>]*>', wikitext, re.IGNORECASE):
            return m.start()
    except Exception:
        pass
    return -1


def _extract_open_tag(raw_tag):
    """Extract the opening <b> tag."""
    m = re.match(r'(<b\b[^>]*>)', raw_tag, re.IGNORECASE)
    return m.group(1) if m else '<b>'


def _extract_close_tag(raw_tag):
    """Extract the closing </b> tag."""
    m = re.search(r'(</b\s*>)', raw_tag, re.IGNORECASE)
    return m.group(1) if m else ''

"""
CheckWiki page fetcher — retrieves and parses the article list for error #26.
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

import requests

from cwfix import USER_AGENT

logger = logging.getLogger(__name__)


# URL template for the CheckWiki tool
# {project} = e.g. "enwiki"
# {error_id} = e.g. 26
CW_URL_TEMPLATE = (
    "https://checkwiki.toolforge.org/checkwiki.cgi"
    "?project={project}&view=only&id={error_id}"
)


class CheckWikiError(Exception):
    """Raised when fetching from CheckWiki fails."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class CheckWikiArticle:
    """An article entry from the CheckWiki list."""
    title: str
    url: str
    snippet: Optional[str] = None
    error_id: int = 26

    def __post_init__(self):
        # Normalize title: remove underscores, URL decode
        self.title = self.title.replace('_', ' ')
        # Decode percent-encoded characters
        from urllib.parse import unquote
        self.title = unquote(self.title)

    def __str__(self):
        return f"[#{self.error_id}] {self.title}"


def fetch_article_list(project='enwiki', error_id=26, timeout=30):
    """
    Fetch the list of articles with error #26 from CheckWiki.
    
    Args:
        project: Wiki project name (e.g., 'enwiki').
        error_id: CheckWiki error ID.
        timeout: Request timeout in seconds.
    
    Returns:
        List of CheckWikiArticle objects.
    
    Raises:
        CheckWikiError: If the request fails.
    """
    url = CW_URL_TEMPLATE.format(project=project, error_id=error_id)
    headers = {
        'User-Agent': USER_AGENT,
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        status = e.response.status_code if hasattr(e, 'response') and e.response is not None else None
        raise CheckWikiError(f"Failed to fetch CheckWiki list: {e}", status_code=status)

    articles = parse_article_list(resp.text, error_id=error_id)
    logger.info(f"Fetched {len(articles)} articles from CheckWiki error #{error_id}")
    return articles


def parse_article_list(html, error_id=26):
    """
    Parse the CheckWiki HTML page and extract article entries.
    
    The CheckWiki page has links in the format:
    <a href="https://en.wikipedia.org/w/index.php?title=Article_Title&redirect=no">
    
    Followed by a <b> tag with a snippet of the error context.
    
    Args:
        html: Raw HTML from CheckWiki.
        error_id: Error ID to assign to extracted articles.
    
    Returns:
        List of CheckWikiArticle objects (deduplicated by title).
    """
    articles = []
    seen_titles = set()

    if not html:
        return articles

    # Pattern: find article links
    # Matches: <a href="...title=Article_Name&redirect=no">Article_Name</a>
    link_pattern = re.compile(
        r'<a\s+href="[^"]*title=([^"&]+)&redirect=no"[^>]*>',
        re.IGNORECASE,
    )

    # We also want to extract snippets from <b> tags following links
    # CheckWiki puts the <b> context snippet right after the article link
    article_blocks = re.split(r'<a\s+href="[^"]*title=', html, flags=re.IGNORECASE)

    for i, block in enumerate(article_blocks):
        if i == 0:
            continue  # skip everything before first link

        # Extract title: up to &redirect=no
        title_match = re.match(r'([^"&]+)', block)
        if not title_match:
            continue

        title = title_match.group(1).replace('_', ' ')
        from urllib.parse import unquote
        title = unquote(title)

        if title in seen_titles:
            continue
        seen_titles.add(title)

        # Extract snippet: find <b>...</b> in the block
        snippet_match = re.search(r'<b[^>]*>(.*?)(?:</b>|$)', block, re.IGNORECASE | re.DOTALL)
        snippet = snippet_match.group(1).strip() if snippet_match else None

        # Build the Wikipedia URL
        encoded_title = title_match.group(1)
        url = f"https://en.wikipedia.org/wiki/{encoded_title}"

        articles.append(CheckWikiArticle(
            title=title,
            url=url,
            snippet=snippet,
            error_id=error_id,
        ))

    return articles


def fetch_wikitext(title, session=None, timeout=30):
    """
    Fetch the raw wikitext of a Wikipedia article.
    
    Args:
        title: Article title.
        session: Optional requests.Session (for reusing auth).
        timeout: Request timeout.
    
    Returns:
        Raw wikitext string.
    
    Raises:
        CheckWikiError: If the request fails.
    """
    if session is None:
        session = requests.Session()
        session.headers.update({'User-Agent': USER_AGENT})

    params = {
        'action': 'parse',
        'page': title,
        'prop': 'wikitext',  # Changed from 'text' to 'wikitext' for cleaner output
        'format': 'json',
        'formatversion': '2',
    }

    try:
        resp = session.get(
            'https://en.wikipedia.org/w/api.php',
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        if 'error' in data:
            raise CheckWikiError(f"API error: {data['error'].get('info', 'unknown')}")

        return data['parse']['wikitext']
    except requests.RequestException as e:
        status = e.response.status_code if hasattr(e, 'response') and e.response is not None else None
        raise CheckWikiError(f"Failed to fetch wikitext for '{title}': {e}", status_code=status)


def signal_done(title, project='enwiki', error_id=26, timeout=10):
    """
    Signal to the CheckWiki tool that an article has been processed.

    Marks the article as 'done' so it disappears from the error list
    for other volunteers. This is the same action as clicking the
    [Done] link on the CheckWiki page.

    Args:
        title: Article title.
        project: Wiki project name (e.g., 'enwiki').
        error_id: CheckWiki error ID.
        timeout: Request timeout in seconds.
    """
    url = (
        "https://checkwiki.toolforge.org/checkwiki.cgi"
        f"?project={project}&view=done&id={error_id}&title={title}"
    )
    headers = {
        'User-Agent': USER_AGENT,
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        logger.info(f"Marked as done on CheckWiki: {title}")
        return True
    except requests.RequestException as e:
        logger.warning(f"Failed to mark done on CheckWiki for '{title}': {e}")
        return False

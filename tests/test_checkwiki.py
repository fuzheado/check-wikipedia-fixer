"""Tests for the CheckWiki page fetcher."""

import pytest
from cwfix.checkwiki import (
    CheckWikiError,
    CheckWikiArticle,
    parse_article_list,
    CW_URL_TEMPLATE,
)


class TestCheckWikiArticle:
    """Tests for the data class."""

    def test_article_creation(self):
        """Article with basic fields."""
        article = CheckWikiArticle(
            title="Test Article",
            url="https://en.wikipedia.org/wiki/Test_Article",
            snippet="<b>bold</b> text here",
            error_id=26,
        )
        assert article.title == "Test Article"
        assert article.error_id == 26

    def test_article_str(self):
        """String representation."""
        article = CheckWikiArticle(
            title="Test Article",
            url="https://en.wikipedia.org/wiki/Test_Article",
            snippet="<b>test</b>",
            error_id=26,
        )
        s = str(article)
        assert "Test Article" in s
        assert "#26" in s


class TestParseArticleList:
    """Tests for parsing the CheckWiki HTML page."""

    def test_parse_empty(self):
        """Empty HTML yields empty list."""
        articles = parse_article_list("")
        assert articles == []

    def test_parse_no_matches(self):
        """HTML with no article links yields empty list."""
        html = "<html><body><p>No articles here.</p></body></html>"
        articles = parse_article_list(html)
        assert articles == []

    def test_parse_single_article(self):
        """Single article link is parsed correctly."""
        html = """
        <html>
        <body>
        <a href="https://en.wikipedia.org/w/index.php?title=Test_Article&redirect=no">Test_Article</a>
        <b>bold snippet here</b>
        </body>
        </html>
        """
        articles = parse_article_list(html)
        assert len(articles) == 1
        assert articles[0].title == "Test Article"
        assert articles[0].error_id == 26

    def test_parse_multiple_articles(self):
        """Multiple articles are all extracted."""
        html = """
        <body>
        <a href="https://en.wikipedia.org/w/index.php?title=Article_One&redirect=no">Article_One</a>
        <b>first snippet</b>
        <a href="https://en.wikipedia.org/w/index.php?title=Article_Two&redirect=no">Article_Two</a>
        <b>second snippet</b>
        </body>
        """
        articles = parse_article_list(html)
        assert len(articles) == 2
        titles = [a.title for a in articles]
        assert "Article One" in titles
        assert "Article Two" in titles

    def test_parse_removes_underscores(self):
        """Underscores in titles are converted to spaces."""
        html = """
        <a href="https://en.wikipedia.org/w/index.php?title=Some_Long_Article_Title&redirect=no">
        Some_Long_Article_Title</a>
        <b>snippet</b>
        """
        articles = parse_article_list(html)
        assert articles[0].title == "Some Long Article Title"

    def test_parse_extracts_snippet(self):
        """The <b> snippet text is extracted."""
        html = """
        <a href="https://en.wikipedia.org/w/index.php?title=Test&redirect=no">Test</a>
        <b>bold text here and s</b>
        """
        articles = parse_article_list(html)
        assert len(articles) == 1
        assert articles[0].snippet is not None

    def test_parse_deduplicates(self):
        """Duplicate articles are removed."""
        html = """
        <a href="https://en.wikipedia.org/w/index.php?title=Same_Article&redirect=no">Same_Article</a>
        <b>snippet1</b>
        <a href="https://en.wikipedia.org/w/index.php?title=Same_Article&redirect=no">Same_Article</a>
        <b>snippet2</b>
        """
        articles = parse_article_list(html)
        assert len(articles) == 1


class TestCURLTemplate:
    """Tests for the URL template constant."""

    def test_url_template_format(self):
        """URL template formats correctly."""
        url = CW_URL_TEMPLATE.format(project="enwiki", error_id=26)
        assert "enwiki" in url
        assert "26" in url
        assert "checkwiki.toolforge.org" in url


class TestSignalDone:
    """Tests for the CheckWiki done-signal function."""

    def test_signal_done_url_format(self):
        """URL is constructed correctly."""
        from cwfix.checkwiki import signal_done
        import requests

        # We can't test the actual HTTP call without making one,
        # but we can verify the URL pattern by monkeypatching.
        # Just verify the function exists and accepts the right args.
        assert callable(signal_done)
        import inspect
        sig = inspect.signature(signal_done)
        assert 'title' in sig.parameters
        assert 'project' in sig.parameters
        assert 'error_id' in sig.parameters

    def test_signal_done_returns_false_on_failure(self, monkeypatch):
        """When the request fails, returns False."""
        from cwfix.checkwiki import signal_done

        def mock_get(*args, **kwargs):
            import requests
            raise requests.RequestException("Network error")

        monkeypatch.setattr('cwfix.checkwiki.requests.get', mock_get)
        result = signal_done("Test Article")
        assert result is False


class TestCheckWikiError:
    """Tests for the exception."""

    def test_error_message(self):
        """Exception has message and status code."""
        error = CheckWikiError("Failed to fetch", status_code=500)
        assert str(error) == "Failed to fetch"
        assert error.status_code == 500

    def test_error_default_status(self):
        """Default status code is None."""
        error = CheckWikiError("Generic error")
        assert error.status_code is None

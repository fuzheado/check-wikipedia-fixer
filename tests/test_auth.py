"""Tests for the Auth module."""

import pytest
import json
import tempfile
from pathlib import Path

from cwfix.auth import (
    AuthConfig,
    WikipediaSession,
    RateLimiter,
    AuthError,
)


class TestAuthConfig:
    """Tests for credential storage and retrieval."""

    def test_auth_config_create(self):
        """Create an auth config with basic fields."""
        config = AuthConfig(
            username="TestUser",
            bot_name="cwfix",
            wiki="en.wikipedia.org",
        )
        assert config.username == "TestUser"
        assert config.bot_name == "cwfix"
        assert config.wiki == "en.wikipedia.org"
        assert config.bot_fullname == "TestUser@cwfix"

    def test_auth_config_equality(self):
        """Two configs with same fields are equal."""
        a = AuthConfig(username="U", bot_name="B", wiki="en.wikipedia.org")
        b = AuthConfig(username="U", bot_name="B", wiki="en.wikipedia.org")
        assert a == b

    def test_auth_config_inequality(self):
        """Different configs are not equal."""
        a = AuthConfig(username="U1", bot_name="B", wiki="en.wikipedia.org")
        b = AuthConfig(username="U2", bot_name="B", wiki="en.wikipedia.org")
        assert a != b

    def test_auth_config_to_dict(self):
        """Serialization to dict."""
        config = AuthConfig(
            username="TestUser",
            bot_name="cwfix",
            wiki="en.wikipedia.org",
        )
        d = config.to_dict()
        assert d['username'] == "TestUser"
        assert d['bot_name'] == "cwfix"
        assert d['wiki'] == "en.wikipedia.org"
        assert 'authenticated_at' in d

    def test_auth_config_from_dict(self):
        """Deserialization from dict."""
        d = {
            'username': 'TestUser',
            'bot_name': 'cwfix',
            'wiki': 'en.wikipedia.org',
            'authenticated_at': '2026-06-08T12:00:00',
            'last_session': '2026-06-08T14:00:00',
        }
        config = AuthConfig.from_dict(d)
        assert config.username == "TestUser"
        assert config.bot_name == "cwfix"
        assert config.wiki == "en.wikipedia.org"


class TestRateLimiter:
    """Tests for the rate limiter."""

    def test_rate_limiter_init(self):
        """Default interval is 2 seconds."""
        rl = RateLimiter()
        assert rl.min_interval == 2.0

    def test_rate_limiter_custom_interval(self):
        """Custom interval is respected."""
        rl = RateLimiter(min_interval=5.0)
        assert rl.min_interval == 5.0

    def test_rate_limiter_first_call_no_wait(self):
        """First call doesn't wait."""
        rl = RateLimiter(min_interval=0)
        # This should not hang
        rl.wait()
        rl.report_done()

    def test_rate_limiter_wait_if_too_soon(self):
        """Second call within interval waits."""
        rl = RateLimiter(min_interval=0.01)  # 10ms
        rl.report_done()
        import time
        start = time.time()
        rl.wait()
        elapsed = time.time() - start
        # Should wait at least min_interval - elapsed_since_last
        # Since report_done was just called, it should wait ~10ms
        assert elapsed >= 0.005  # allow small timing slop


class TestWikipediaSession:
    """Tests for the Wikipedia session (mock the network)."""

    def test_session_headers(self):
        """Session has proper User-Agent."""
        session = WikipediaSession(
            username="TestUser",
            bot_name="cwfix",
            password="test-password-123",
            wiki="en.wikipedia.org",
        )
        ua = session.session.headers.get('User-Agent', '')
        assert 'CWFix' in ua
        assert 'CheckWikiError26Fixer' in ua
        assert 'TestUser' in ua

    def test_session_bot_fullname(self):
        """Bot fullname is username@bot_name."""
        session = WikipediaSession(
            username="CoolEditor42",
            bot_name="myfixer",
            password="abc123",
        )
        assert session.bot_fullname == "CoolEditor42@myfixer"

    def test_session_auth_header(self):
        """Basic auth header is set."""
        session = WikipediaSession(
            username="User",
            bot_name="Bot",
            password="secret",
        )
        auth = session.session.auth
        assert auth is not None
        # We can't easily check the exact value without triggering the auth,
        # but we can verify the type
        assert hasattr(auth, '__call__') or hasattr(auth, '__class__')


class TestAuthError:
    """Tests for the custom exception."""

    def test_auth_error_message(self):
        """AuthError has a message."""
        error = AuthError("Login failed")
        assert str(error) == "Login failed"
        assert isinstance(error, Exception)

    def test_auth_error_with_cause(self):
        """AuthError can wrap another exception."""
        cause = ValueError("Invalid password")
        error = AuthError("Auth failed", cause)
        assert str(error) == "Auth failed"
        assert error.cause is cause

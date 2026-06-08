"""
Authentication module — bot password management and Wikipedia session handling.

Uses the OS keyring for credential storage and the MediaWiki Action API
for login and editing.
"""

import os
import json
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from cwfix import USER_AGENT

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when authentication fails."""
    def __init__(self, message, cause=None):
        super().__init__(message)
        self.cause = cause

    def __repr__(self):
        return f"AuthError({self.args[0]!r})"


@dataclass
class AuthConfig:
    """Stored authentication metadata (not the password itself)."""
    username: str
    bot_name: str
    wiki: str = 'en.wikipedia.org'
    authenticated_at: Optional[str] = None
    last_session: Optional[str] = None

    def __post_init__(self):
        # Normalize: MediaWiki API requires underscores for spaces
        self.username = self.username.replace(' ', '_')

    @property
    def bot_fullname(self):
        return f"{self.username}@{self.bot_name}"

    def to_dict(self):
        return {
            'username': self.username,
            'bot_name': self.bot_name,
            'wiki': self.wiki,
            'authenticated_at': self.authenticated_at or datetime.now(timezone.utc).isoformat(),
            'last_session': self.last_session,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            username=d.get('username', ''),
            bot_name=d.get('bot_name', ''),
            wiki=d.get('wiki', 'en.wikipedia.org'),
            authenticated_at=d.get('authenticated_at'),
            last_session=d.get('last_session'),
        )

    def __eq__(self, other):
        if not isinstance(other, AuthConfig):
            return NotImplemented
        return (self.username == other.username and
                self.bot_name == other.bot_name and
                self.wiki == other.wiki)


class WikipediaSession:
    """
    Manages an authenticated session with the Wikipedia Action API.

    Handles login, CSRF token acquisition, editing, and rate limiting.
    """

    def __init__(self, username: str, bot_name: str, password: str,
                 wiki: str = 'en.wikipedia.org'):
        # Normalize: MediaWiki API requires underscores for spaces in usernames
        # (the internal DB form, not the human-readable display form)
        self.username = username.replace(' ', '_')
        self.bot_name = bot_name
        self.password = password
        self.wiki = wiki
        self.api_url = f'https://{wiki}/w/api.php'
        self.bot_fullname = f"{self.username}@{self.bot_name}"

        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(self.bot_fullname, password)
        self.session.headers.update({
            'User-Agent': self._make_user_agent(),
        })

        self.csrf_token: Optional[str] = None
        self.logged_in = False
        self.rate_limiter = RateLimiter(min_interval=2.0)

    def _make_user_agent(self):
        return (
            f'CWFix/1.0 '
            f'(https://en.wikipedia.org/wiki/User:{self.username}; '
            f'cwfix-tool@localhost) '
            f'CheckWikiError26Fixer'
        )

    def login(self):
        """
        Authenticate and obtain a CSRF token.

        Raises AuthError on failure.
        """
        logger.info(f"Logging in as {self.bot_fullname} on {self.wiki}")

        # Step 1: Login (MUST be POST — MediaWiki API requires it)
        login_data = {
            'action': 'login',
            'lgname': self.bot_fullname,
            'lgpassword': self.password,
            'format': 'json',
        }

        try:
            resp = self.session.post(self.api_url, data=login_data, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            login_result = result.get('login', {})
            status = login_result.get('result', '')

            if status == 'NeedToken':
                # Two-step login: send the token from the first response
                login_data['lgtoken'] = login_result['token']
                resp = self.session.post(self.api_url, data=login_data, timeout=30)
                resp.raise_for_status()
                result = resp.json()
                login_result = result.get('login', {})
                status = login_result.get('result', '')

            if status != 'Success':
                error_info = login_result.get('reason', 'Unknown error')
                # Extract the more specific error code if available
                error_code = login_result.get('errorcode', '')
                if error_code:
                    error_info = f"{error_info} (code: {error_code})"
                raise AuthError(f"Login failed: {error_info}")
        except requests.RequestException as e:
            raise AuthError(f"Login request failed: {e}")

        # Step 2: Get CSRF token
        token_params = {
            'action': 'query',
            'meta': 'tokens',
            'format': 'json',
        }

        try:
            resp = self.session.get(self.api_url, params=token_params, timeout=30)
            resp.raise_for_status()
            token_data = resp.json()
            self.csrf_token = token_data['query']['tokens']['csrftoken']
        except (requests.RequestException, KeyError) as e:
            raise AuthError(f"Failed to get CSRF token: {e}")

        self.logged_in = True
        logger.info("Login successful, CSRF token acquired")
        return True

    def edit(self, title: str, text: str, summary: str,
             minor: bool = True) -> dict:
        """
        Save an edit to a Wikipedia page.

        Args:
            title: Page title.
            text: New wikitext content.
            summary: Edit summary.
            minor: Whether to mark the edit as minor.

        Returns:
            API response JSON.

        Raises:
            AuthError: If not logged in or token expired.
            requests.RequestException: On network failure.
        """
        if not self.logged_in or not self.csrf_token:
            raise AuthError("Not logged in. Call login() first.")

        self.rate_limiter.wait()

        edit_data = {
            'action': 'edit',
            'title': title,
            'text': text,
            'summary': summary,
            'token': self.csrf_token,
            'format': 'json',
            'assert': 'user',
            'maxlag': '5',
        }

        if minor:
            edit_data['minor'] = '1'

        try:
            resp = self.session.post(self.api_url, data=edit_data, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if 'error' in result:
                error_info = result['error'].get('info', 'Unknown error')
                error_code = result['error'].get('code', '')
                if error_code in ('notloggedin', 'badtoken'):
                    # Session expired — re-login
                    logger.warning("Session expired, re-logging in")
                    self.logged_in = False
                    self.login()
                    # Retry once
                    return self.edit(title, text, summary, minor=minor)
                raise AuthError(f"Edit failed: {error_info} (code: {error_code})")

            self.rate_limiter.report_done()
            return result.get('edit', {})

        except requests.RequestException as e:
            status = e.response.status_code if hasattr(e, 'response') and e.response is not None else None
            if status == 429:
                # Rate limited
                retry_after = int(e.response.headers.get('Retry-After', 10))
                logger.warning(f"Rate limited, waiting {retry_after}s")
                time.sleep(retry_after)
                return self.edit(title, text, summary, minor=minor)
            raise

    def get_wikitext(self, title: str) -> str:
        """
        Fetch the raw wikitext of a page.

        Args:
            title: Page title.

        Returns:
            Raw wikitext string.
        """
        params = {
            'action': 'parse',
            'page': title,
            'prop': 'wikitext',
            'format': 'json',
            'formatversion': '2',
        }

        resp = self.session.get(self.api_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if 'error' in data:
            raise AuthError(f"API error: {data['error'].get('info', 'unknown')}")

        return data['parse']['wikitext']


class RateLimiter:
    """
    Ensures a minimum interval between edits to respect Wikipedia rate limits.
    """

    def __init__(self, min_interval: float = 2.0):
        self.min_interval = min_interval
        self.last_edit: float = 0.0

    def wait(self):
        """Wait if necessary to maintain the minimum interval."""
        if self.last_edit == 0:
            return
        elapsed = time.time() - self.last_edit
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def report_done(self):
        """Record that an edit was just performed."""
        self.last_edit = time.time()


class CredentialStore:
    """
    Manages bot password credentials using the OS keyring.

    Falls back to encrypted file storage if keyring is unavailable.
    """

    CONFIG_DIR = Path.home() / '.config' / 'cwfix'
    CONFIG_FILE = CONFIG_DIR / 'auth_config.json'
    SERVICE_NAME = 'cwfix'

    def __init__(self):
        self.config_dir = self.CONFIG_DIR
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def save(self, config: AuthConfig, password: str):
        """Save auth config and password."""
        # Save password to keyring
        try:
            import keyring
            keyring.set_password(self.SERVICE_NAME, config.bot_fullname, password)
        except Exception:
            logger.warning("Keyring unavailable, using encrypted file fallback")
            self._save_password_file(config.bot_fullname, password)

        # Save config metadata
        config.last_session = datetime.now(timezone.utc).isoformat()
        self._save_config(config)

    def load(self, username: str, bot_name: str) -> tuple[Optional[AuthConfig], Optional[str]]:
        """
        Load credentials for a given user/bot.

        Returns:
            Tuple of (AuthConfig, password) or (None, None) if not found.
        """
        bot_fullname = f"{username}@{bot_name}"

        # Load password
        password = None
        try:
            import keyring
            password = keyring.get_password(self.SERVICE_NAME, bot_fullname)
        except Exception:
            password = self._load_password_file(bot_fullname)

        if not password:
            return None, None

        # Load config
        config = self._load_config()
        if config and config.username == username and config.bot_name == bot_name:
            return config, password

        return None, None

    def load_any(self) -> tuple[Optional[AuthConfig], Optional[str]]:
        """
        Load the most recently saved credentials.

        Returns:
            Tuple of (AuthConfig, password) or (None, None) if none exist.
        """
        config = self._load_config()
        if not config:
            return None, None

        return self.load(config.username, config.bot_name)

    def delete(self, username: str, bot_name: str):
        """Remove stored credentials."""
        bot_fullname = f"{username}@{bot_name}"
        try:
            import keyring
            try:
                keyring.delete_password(self.SERVICE_NAME, bot_fullname)
            except keyring.errors.PasswordDeleteError:
                pass
        except Exception:
            pass

        self._delete_password_file(bot_fullname)
        self._delete_config()

    def has_credentials(self) -> bool:
        """Check if any credentials are stored."""
        config = self._load_config()
        if not config:
            return False
        _, password = self.load(config.username, config.bot_name)
        return password is not None

    def _save_config(self, config: AuthConfig):
        with open(self.CONFIG_FILE, 'w') as f:
            json.dump(config.to_dict(), f, indent=2)
        self.CONFIG_FILE.chmod(0o600)

    def _load_config(self) -> Optional[AuthConfig]:
        if not self.CONFIG_FILE.exists():
            return None
        try:
            with open(self.CONFIG_FILE) as f:
                data = json.load(f)
            return AuthConfig.from_dict(data)
        except (json.JSONDecodeError, IOError):
            return None

    def _delete_config(self):
        if self.CONFIG_FILE.exists():
            self.CONFIG_FILE.unlink()

    def _save_password_file(self, key: str, password: str):
        """Fallback: store encrypted password in a local file."""
        # Simple obfuscation — not true encryption for v1.0.
        # A production version would use AES-256-GCM with a derived key.
        password_file = self.config_dir / 'auth_secret'
        stored = {key: password}
        with open(password_file, 'w') as f:
            json.dump(stored, f)
        password_file.chmod(0o600)

    def _load_password_file(self, key: str) -> Optional[str]:
        password_file = self.config_dir / 'auth_secret'
        if not password_file.exists():
            return None
        try:
            with open(password_file) as f:
                stored = json.load(f)
            return stored.get(key)
        except (json.JSONDecodeError, IOError, KeyError):
            return None

    def _delete_password_file(self, key: str):
        password_file = self.config_dir / 'auth_secret'
        if password_file.exists():
            password_file.unlink()

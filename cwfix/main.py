#!/usr/bin/env python3
"""
CWFix — Interactive CheckWiki Error #26 Fixer.

Usage:
    cwfix                       # Interactive mode (authenticate first)
    cwfix --batch-safe          # Auto-fix all safe occurrences
    cwfix --dry-run             # Preview without saving
    cwfix --reset               # Reset progress cache
    cwfix --articles 10         # Only process 10 articles (for testing)
    cwfix --resume              # Resume from last saved position
"""

import sys
import logging
from pathlib import Path

import click

from cwfix import __version__, USER_AGENT
from cwfix.auth import CredentialStore, WikipediaSession, AuthError
from cwfix.checkwiki import (
    fetch_article_list, fetch_wikitext, signal_done, CheckWikiError,
)
from cwfix.engine import analyze_article, fix_all_safe_occurrences
from cwfix.fixer import make_edit_summary
from cwfix.cache import ProgressCache
from cwfix.tui import TUI


logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / '.cache' / 'cwfix'
DEFAULT_CACHE_PATH = DEFAULT_CACHE_DIR / 'progress.db'


@click.group(invoke_without_command=True)
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--version', '-V', is_flag=True, help='Print version and exit')
@click.pass_context
def cli(ctx, verbose, version):
    """CWFix — Interactive CheckWiki Error #26 Fixer.

    Converts HTML <b> tags to wiki ''' bold markup on English Wikipedia.
    """
    if version:
        click.echo(f"CWFix v{__version__}")
        sys.exit(0)

    # Set up logging
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(levelname)s:%(name)s:%(message)s',
    )

    if ctx.invoked_subcommand is None:
        # No subcommand — run the main interactive flow
        ctx.invoke(main)


@cli.command()
@click.option('--batch-safe', is_flag=True, help='Auto-fix all safe occurrences')
@click.option('--dry-run', is_flag=True, help='Preview changes without saving')
@click.option('--articles', type=int, default=None, help='Limit number of articles')
@click.option('--resume', is_flag=True, help='Resume from last position')
@click.option('--reset', is_flag=True, help='Reset progress cache')
@click.option('--report', is_flag=True, help='Generate report of current progress')
@click.option('--pause/--no-pause', default=False,
              help='Pause with "Press Enter" after each action')
@click.option('--done/--no-done', default=True,
              help='Signal "done" to CheckWiki after fixing an article')
def main(batch_safe, dry_run, articles, resume, reset, report, pause, done):
    """Run the CWFix interactive fixer."""

    # ── Initialize ────────────────────────────────────────────────
    def _mark_done(title):
        """Signal done to CheckWiki after fixing an article."""
        if done:
            try:
                signal_done(title, project='enwiki', error_id=26)
            except Exception as e:
                logger.warning(f"Failed to signal done: {e}")

    tui = TUI(pause=pause, done_callback=_mark_done if done else None)
    cache = ProgressCache(DEFAULT_CACHE_PATH)

    if reset:
        cache.reset()
        click.echo("✓ Progress cache reset.")
        return

    if report:
        stats = cache.get_stats()
        click.echo(f"Total articles: {stats['total']}")
        click.echo(f"  Fixed:  {stats['fixed']}")
        click.echo(f"  Skipped: {stats['skipped']}")
        click.echo(f"  Pending: {stats['pending']}")
        click.echo(f"  Total fixes: {stats['total_fixes']}")
        return

    # ── Authentication ────────────────────────────────────────────
    credential_store = CredentialStore()
    wiki_session = None

    if not dry_run and not batch_safe:
        # Interactive mode needs authentication
        config, password = credential_store.load_any()

        if not config or not password:
            tui.show_auth_prompt()
            config, password = _authenticate_interactive(tui, credential_store)
            if not config:
                click.echo("Authentication cancelled. Exiting.")
                return

        try:
            wiki_session = WikipediaSession(
                username=config.username,
                bot_name=config.bot_name,
                password=password,
            )
            wiki_session.login()
            click.echo(f"✓ Authenticated as {config.bot_fullname}")
        except AuthError as e:
            click.echo(f"✗ Authentication failed: {e}", err=True)
            click.echo("Try deleting credentials with: cwfix --reset")
            return

    # ── Fetch article list ────────────────────────────────────────
    tui.show_welcome()

    try:
        click.echo("Fetching article list from CheckWiki...")
        article_list = fetch_article_list(project='enwiki', error_id=26)
    except CheckWikiError as e:
        click.echo(f"✗ Failed to fetch article list: {e}", err=True)
        return

    if not article_list:
        click.echo("No articles found with error #26. Great!")
        return

    click.echo(f"Found {len(article_list)} articles with error #26.")

    # ── Limit articles if requested ───────────────────────────────
    if articles is not None:
        article_list = article_list[:articles]
        click.echo(f"Limited to {articles} articles.")

    # ── Filter to pending articles (resume support) ───────────────
    if resume:
        already_done = cache.count_fixed() + cache.count_skipped()
        pending_titles = {a.title for a in cache.get_pending()}
        article_list = [a for a in article_list if a.title in pending_titles]
        click.echo(f"Resuming: {len(article_list)} articles remaining "
                    f"({already_done} already done).")

    # ── Seed the cache ────────────────────────────────────────────
    for article in article_list:
        cache.add_article(article.title, article.url)

    tui.articles_total = len(article_list)

    # ── Process articles ──────────────────────────────────────────
    for article_idx, article in enumerate(article_list):
        tui.articles_done = article_idx

        click.echo(f"\n[{article_idx + 1}/{len(article_list)}] {article.title}")

        # Fetch wikitext
        try:
            if wiki_session:
                wikitext = wiki_session.get_wikitext(article.title)
            else:
                wikitext = fetch_wikitext(article.title)
        except (CheckWikiError, AuthError) as e:
            click.echo(f"  ✗ Failed to fetch: {e}")
            cache.mark_skipped(article.title)
            continue

        # Analyze
        analysis = analyze_article(article.title, wikitext, article.url)

        if analysis.total_count == 0:
            click.echo("  No <b> tags found (false positive?).")
            cache.mark_skipped(article.title)
            continue

        click.echo(f"  Found {analysis.total_count} <b> tag(s) "
                    f"({analysis.safe_count} safe).")

        # ── Batch mode ────────────────────────────────────────────
        if batch_safe and not dry_run:
            new_wikitext = fix_all_safe_occurrences(wikitext, analysis)
            if new_wikitext != wikitext:
                if wiki_session:
                    try:
                        result = wiki_session.edit(
                            title=article.title,
                            text=new_wikitext,
                            summary=make_edit_summary('26', analysis.safe_count),
                        )
                        click.echo(f"  ✓ Fixed {analysis.safe_count} occurrences.")
                        cache.mark_fixed(article.title, fixes=analysis.safe_count)
                    except AuthError as e:
                        click.echo(f"  ✗ Edit failed: {e}")
                        cache.mark_skipped(article.title)
                else:
                    click.echo("  (dry-run) Would fix safe occurrences.")
                    cache.mark_fixed(article.title, fixes=analysis.safe_count)
            else:
                click.echo("  No safe fixes needed.")
                cache.mark_skipped(article.title)
            continue

        # ── Interactive mode ──────────────────────────────────────
        final_text, final_action = tui.run_article(analysis)

        if final_action == 'quit':
            click.echo("\nProgress saved. Resume with: cwfix --resume")
            break

        was_fixed = (final_text != wikitext)

        if was_fixed:
            if not dry_run and wiki_session:
                # Count actual fixes
                fix_count = _count_fixes(wikitext, final_text)
                try:
                    wiki_session.edit(
                        title=article.title,
                        text=final_text,
                        summary=make_edit_summary('26', fix_count),
                    )
                    click.echo(f"  ✓ Saved ({fix_count} fixes).")
                    cache.mark_fixed(article.title, fixes=fix_count)
                except AuthError as e:
                    click.echo(f"  ✗ Failed to save: {e}")
                    cache.mark_skipped(article.title)
            elif dry_run:
                diff_text = _count_fixes(wikitext, final_text)
                click.echo(f"  (dry-run) Would save {diff_text} fixes.")
                cache.mark_fixed(article.title, fixes=diff_text)
            else:
                # No auth (shouldn't reach here in interactive mode)
                click.echo("  (no auth — changes not saved)")
                cache.mark_fixed(article.title, fixes=0)
        else:
            cache.mark_skipped(article.title)

    # ── Done ──────────────────────────────────────────────────────
    tui.show_goodbye()
    stats = cache.get_stats()
    click.echo(f"\nSession stats: {stats}")
    cache.close()


# ─── Helpers ──────────────────────────────────────────────────────


def _authenticate_interactive(tui, credential_store):
    """Run the interactive authentication flow."""
    import sys
    from rich.prompt import Prompt
    from rich.console import Console

    console = Console()

    tui.show_auth_prompt()

    console.print()
    console.print("  [bold]Enter your Wikipedia login details below.[/bold]")
    console.print("  [dim]These are the same credentials you use to log into Wikipedia.[/dim]")
    console.print()
    console.print("  [yellow]⚠ IMPORTANT:[/yellow] Enter your Wikipedia [bold]username[/bold],")
    console.print("  [yellow]⚠[/yellow] not the bot identifier (no '@' symbol).")
    console.print()

    username = Prompt.ask("  Your Wikipedia username")
    if not username:
        return None, None

    # Normalize: MediaWiki API requires underscores in usernames
    # (internal DB form). We do this silently so users can type spaces.
    normalized = username.replace(' ', '_')
    if normalized != username:
        console.print(f"  [dim](normalized to {normalized} for API)[/dim]")

    bot_name = Prompt.ask("  Bot name (as created on Special:BotPasswords)", default="cwfix")

    console.print()
    console.print(f"  Will authenticate as: [bold cyan]{normalized}@{bot_name}[/bold cyan]")
    console.print()

    password = Prompt.ask("  Bot password", password=True)
    if not password:
        return None, None

    console.print("  [dim]Password received (\u2713)[/dim]")

    # Pass the normalized username to the auth module
    username = normalized
    console.print()

    from cwfix.auth import AuthConfig

    config = AuthConfig(
        username=username,
        bot_name=bot_name,
        wiki='en.wikipedia.org',
    )

    # Test the credentials
    console.print("  Testing credentials...", style="yellow")
    try:
        session = WikipediaSession(username, bot_name, password)
        session.login()
        console.print(f"  [bold green]✓ Authenticated as {session.bot_fullname}[/bold green]")
    except AuthError as e:
        console.print(f"  [bold red]✗ Authentication failed[/bold red]")
        console.print(f"    Reason: {e}")
        console.print()
        console.print("  Possible causes:")
        console.print("    • The bot password was entered incorrectly")
        console.print("    • The bot password was revoked or expired")
        console.print("    • Grants do not include 'Edit existing pages'")
        console.print("    • The bot name doesn't match what was created")
        console.print()
        console.print("  To create a new bot password, visit:")
        console.print("    [blue]https://en.wikipedia.org/wiki/Special:BotPasswords[/blue]")
        console.print()
        retry = click.confirm("  Try again?", default=True)
        if retry:
            return _authenticate_interactive(tui, credential_store)
        return None, None

    # Save
    credential_store.save(config, password)
    console.print("  [bold green]✓ Credentials saved securely to OS keychain[/bold green]")
    return config, password


def _count_fixes(old_wikitext: str, new_wikitext: str) -> int:
    """Count how many <b> tags were converted."""
    old_count = old_wikitext.count('<b>')
    new_count = new_wikitext.count('<b>')
    return max(0, old_count - new_count)


if __name__ == '__main__':
    cli()

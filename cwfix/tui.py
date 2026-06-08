"""
Terminal UI — interactive prompt loop with rich color rendering.

Presents each <b> occurrence to the user with context, classification,
and a proposed fix. Dispatches user actions.
"""

import sys
import textwrap
import logging
from typing import Optional

from rich.console import Console
from rich.text import Text
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.progress import Progress, BarColumn, TextColumn
from rich.syntax import Syntax
from rich.prompt import Prompt, Confirm
from rich.markup import escape as rich_escape

from cwfix.classifier import Classification, CLASSIFICATION_LABELS
from cwfix.fixer import generate_diff, make_edit_summary
from cwfix.engine import (
    BTagOccurrence,
    ArticleAnalysis,
    fix_occurrence,
    fix_all_identical_pattern,
    fix_all_safe_occurrences,
    get_transform_for,
)

logger = logging.getLogger(__name__)


class TUI:
    """
    Interactive terminal UI for fixing <b> tags.

    Presents each occurrence with context, classification, and proposed fix.
    Dispatches user actions and tracks undo history.
    """

    # Classification → (emoji, color, label)
    BADGE_STYLES = {
        Classification.SAFE_SIMPLE: ("🟢", "green", "SAFE_SIMPLE"),
        Classification.SAFE_BOLD_ITALIC: ("🟢", "green", "SAFE_BOLD_ITALIC"),
        Classification.SAFE_NESTED: ("🟢", "green", "SAFE_NESTED"),
        Classification.TEMPLATE_PARAM: ("🟡", "yellow", "TEMPLATE_PARAM"),
        Classification.NO_CLOSE_TAG: ("🔴", "red", "NO_CLOSE_TAG"),
        Classification.INSIDE_NOWIKI: ("⚪", "white", "INSIDE_NOWIKI"),
        Classification.SPURIOUS: ("🔴", "red", "SPURIOUS"),
    }

    def __init__(self, console: Optional[Console] = None, pause: bool = False,
                 done_callback=None):
        self.console = console or Console()
        self.undo_stack = []  # List of (wikitext_before, wikitext_after)
        self.current_analysis: Optional[ArticleAnalysis] = None
        self.current_wikitext: str = ''
        self.articles_total = 0
        self.articles_done = 0
        self.fixes_in_session = 0
        self.pause = pause          # If True, pause after each action
        self.done_callback = done_callback  # Called after article is fixed

    def _pause_if_needed(self):
        """Pause with 'Press Enter to continue' if pause mode is enabled."""
        if self.pause:
            Prompt.ask("  [dim]Press Enter to continue[/dim]", default="")

    # ─── Main loop ────────────────────────────────────────────────

    def run_article(self, analysis: ArticleAnalysis) -> tuple[Optional[str], str]:
        """
        Run the interactive fix loop for a single article.

        Args:
            analysis: ArticleAnalysis with classified occurrences.

        Returns:
            Tuple of (final_wikitext, final_action) where final_action
            is 'fixed', 'skipped', 'all_fixed', or 'quit'.
        """
        self.current_analysis = analysis
        self.current_wikitext = analysis.wikitext
        self.undo_stack = []

        if analysis.total_count == 0:
            return analysis.wikitext, 'skipped'

        # Process each occurrence
        idx = 0
        while idx < len(analysis.occurrences):
            occurrence = analysis.occurrences[idx]

            # After a batch fix, skip occurrences whose raw_tag no longer exists
            # in the current wikitext (they were already fixed by the batch op)
            if occurrence.raw_tag and occurrence.raw_tag not in self.current_wikitext:
                idx += 1
                continue

            action = self._process_occurrence(idx, occurrence)

            if action == 'quit':
                return self.current_wikitext, 'quit'

            elif action == 'undo':
                if self.undo_stack:
                    self.current_wikitext, _ = self.undo_stack.pop()
                    self.fixes_in_session = max(0, self.fixes_in_session - 1)
                # After undo, re-check all remaining occurrences
                idx = 0
                continue

            elif action == 'list_all':
                self._show_list_all()
                continue

            elif action == 'help':
                self._show_help()
                continue

            # Fixed, all_fixed, or skipped — move to next
            idx += 1

        # Article complete
        was_fixed = (self.current_wikitext != analysis.wikitext)
        final_action = 'fixed' if was_fixed else 'skipped'

        # Signal 'done' to CheckWiki if edits were made and callback is set
        if was_fixed and self.done_callback:
            self.console.print(
                "  [dim]Marking as done on CheckWiki...[/dim]"
            )
            self.done_callback(analysis.title)

        self._pause_if_needed()
        return self.current_wikitext, final_action

    def _process_occurrence(self, idx: int, occurrence: BTagOccurrence) -> str:
        """Process a single occurrence. Returns the action taken."""
        while True:
            self._render_occurrence(idx, occurrence)
            action = self._get_action(occurrence)

            if action == 'f':
                # Fix this occurrence
                old_text = self.current_wikitext
                new_text = fix_occurrence(self.current_wikitext, occurrence)
                if new_text != old_text:
                    self.undo_stack.append((old_text, new_text))
                    self.current_wikitext = new_text
                    self.fixes_in_session += 1
                    self.console.print(
                        "  [green]✓ Fixed![/green]",
                        style="bold green",
                    )
                self._pause_if_needed()
                return 'fixed'

            elif action == 'e':
                # Edit the fix manually
                return self._handle_edit(occurrence)

            elif action == 'a':
                # Fix all identical
                old_text = self.current_wikitext
                new_text = fix_all_identical_pattern(self.current_wikitext, occurrence)
                if new_text != old_text:
                    count = old_text.count(occurrence.raw_tag)
                    self.undo_stack.append((old_text, new_text))
                    self.current_wikitext = new_text
                    self.fixes_in_session += count
                    self.console.print(
                        f"  [green]✓ Fixed {count} identical occurrences![/green]",
                        style="bold green",
                    )
                self._pause_if_needed()
                return 'all_fixed'

            elif action == 'F':
                # Fix all safe
                old_text = self.current_wikitext
                new_text = fix_all_safe_occurrences(
                    self.current_wikitext, self.current_analysis
                )
                if new_text != old_text:
                    safe_count = self.current_analysis.safe_count
                    self.undo_stack.append((old_text, new_text))
                    self.current_wikitext = new_text
                    self.fixes_in_session += safe_count
                    self.console.print(
                        f"  [green]✓ Fixed all {safe_count} safe occurrences![/green]",
                        style="bold green",
                    )
                self._pause_if_needed()
                return 'all_fixed'

            elif action == 's':
                return 'skipped'

            elif action == 'd':
                self._show_diff(occurrence)
                continue  # come back to same occurrence

            elif action == 'c':
                self._show_extended_context(idx)
                continue

            elif action == 'l':
                return 'list_all'

            elif action == '!':
                self._flag_false_positive(occurrence)
                return 'skipped'

            elif action == 'u':
                return 'undo'

            elif action == '?':
                return 'help'

            elif action == 'q':
                return 'quit'

    # ─── Rendering ────────────────────────────────────────────────

    def _render_occurrence(self, idx: int, occurrence: BTagOccurrence):
        """Render the main occurrence view."""
        self.console.clear()

        total = self.current_analysis.total_count
        article_title = self.current_analysis.title
        emoji, color, label = self.BADGE_STYLES.get(
            occurrence.classification,
            ("⚪", "white", "UNKNOWN"),
        )

        # ── Header ──
        header_lines = []
        # First line: article title (full, no truncation)
        header_lines.append(f"{article_title}")
        # Second line: position within article and overall progress
        position = f"Occurrence {idx + 1} of {total}"
        if self.articles_total > 0:
            position += f"  —  Article {self.articles_done + 1} of {self.articles_total}"
        header_lines.append(position)
        header_text = "\n".join(header_lines)
        self.console.print(Panel(header_text, style="cyan"))

        # ── Progress bar ──
        if total > 0:
            progress_pct = idx / total
            bar_width = 30
            filled = int(bar_width * progress_pct)
            bar = "█" * filled + "░" * (bar_width - filled)
            self.console.print(f"  Progress: [{bar}]  {int(progress_pct * 100)}%")
            self.console.print()

        # ── Context ──
        context_panel = self._build_context_panel(occurrence)
        self.console.print(context_panel)

        # ── Classification badge ──
        badge = f"  {emoji}  [bold {color}]{label}[/bold {color}]"
        if occurrence.is_safe:
            badge += " — [green]Safe to fix[/green]"
        elif occurrence.classification == Classification.TEMPLATE_PARAM:
            tmpl = occurrence.template_name or "unknown"
            badge += f" — [yellow]Template: {tmpl}[/yellow]"
        elif occurrence.classification == Classification.INSIDE_NOWIKI:
            badge += " — [dim]Inside nowiki/comment — skipping[/dim]"
        elif occurrence.classification == Classification.NO_CLOSE_TAG:
            badge += " — [red]Unmatched tag — needs manual review[/red]"
        self.console.print(badge)
        self.console.print()

        # ── Suggested fix ──
        if occurrence.suggested_fix:
            old_styled = Text()
            old_styled.append(f"  {rich_escape(occurrence.raw_tag)}", style="red")
            self.console.print(old_styled)

            arrow = Text("  ───────────────────────────────────────────→\n", style="bold cyan")
            self.console.print(arrow)

            new_styled = Text()
            new_styled.append(f"  {rich_escape(occurrence.suggested_fix)}", style="green")
            self.console.print(new_styled)
        else:
            self.console.print("  [yellow]No automatic fix available.[/yellow]")

        self.console.print()

    def _build_context_panel(self, occurrence: BTagOccurrence) -> Panel:
        """Build the context panel with highlighted <b> tags."""
        # Show the line containing the <b> tag with surrounding context
        lines = self.current_wikitext.splitlines()
        start = max(0, occurrence.line - 3)
        end = min(len(lines), occurrence.line + 2)

        context_text = Text()
        for i in range(start, end):
            line_num = i + 1
            line = lines[i]

            # Highlight indicator for the target line
            prefix = "  " if line_num != occurrence.line else "→ "

            line_text = Text(f"{prefix}[{line_num:4d}] ", style="dim")
            line_text.append(rich_escape(line))
            context_text.append(line_text)
            context_text.append("\n")

        return Panel(
            context_text,
            title="[bold]Context[/bold]",
            border_style="dim",
            padding=(0, 1),
        )

    def _show_list_all(self):
        """Show a summary table of all <b> tags in the article."""
        self.console.clear()

        table = Table(
            title=f"All <b> tags in: {self.current_analysis.title}",
            box=None,
        )
        table.add_column("#", style="dim")
        table.add_column("Line", style="dim")
        table.add_column("Class", no_wrap=True)
        table.add_column("Context snippet")
        table.add_column("Status", style="dim")

        for i, occ in enumerate(self.current_analysis.occurrences):
            emoji, color, label = self.BADGE_STYLES.get(
                occ.classification, ("⚪", "white", "UNKNOWN")
            )
            marker = "→" if i == 0 else ""
            snippet = occ.content[:50] + "..." if len(occ.content) > 50 else occ.content
            table.add_row(
                f"{marker} {i + 1}",
                str(occ.line),
                f"[{color}]{emoji} {label}[/{color}]",
                rich_escape(snippet),
                "PENDING",
            )

        self.console.print(table)
        self.console.print()
        self.console.print("[dim]→ = current position[/dim]")
        self.console.print()

        Prompt.ask("  Press Enter to return", default="")

    def _show_diff(self, occurrence: BTagOccurrence):
        """Show a unified diff of the proposed change."""
        new_text = fix_occurrence(self.current_wikitext, occurrence)
        diff = generate_diff(self.current_wikitext, new_text, context=3)

        self.console.clear()
        self.console.print("[bold]Proposed diff:[/bold]")
        self.console.print()

        if diff == "(no changes)":
            self.console.print("  [yellow]No changes would be made.[/yellow]")
        else:
            syntax = Syntax(diff, "diff", theme="ansi_dark", line_numbers=False)
            self.console.print(syntax)

        self.console.print()
        Prompt.ask("  Press Enter to continue", default="")

    def _show_extended_context(self, idx: int):
        """Show an expanded context window (30 lines)."""
        occurrence = self.current_analysis.occurrences[idx]
        lines = self.current_wikitext.splitlines()
        start = max(0, occurrence.line - 15)
        end = min(len(lines), occurrence.line + 15)

        self.console.clear()
        self.console.print("[bold]Extended context (30 lines):[/bold]")
        self.console.print()

        for i in range(start, end):
            line_num = i + 1
            prefix = "  " if line_num != occurrence.line else "→ "
            style = "" if line_num != occurrence.line else "bold white on #444444"
            self.console.print(f"{prefix}[{line_num:4d}] {lines[i]}", style=style)

        self.console.print()
        Prompt.ask("  Press Enter to continue", default="")

    def _flag_false_positive(self, occurrence: BTagOccurrence):
        """Flag a pattern as a false positive."""
        # For v1.0, just acknowledge. A future version would persist rules.
        self.console.print(
            "  [yellow]Pattern flagged as false positive.[/yellow]"
        )
        self.console.print(
            "  [dim](Rule persistence will be added in a future version)[/dim]"
        )

    def _show_help(self):
        """Show the keybinding reference."""
        self.console.clear()
        help_text = """
  [bold cyan]CWFix — Keybinding Reference[/bold cyan]

  [bold]Core actions:[/bold]
    [blue]f[/blue]  — Fix this occurrence
    [blue]e[/blue]  — Edit the fix manually before applying
    [blue]s[/blue]  — Skip this occurrence
    [blue]q[/blue]  — Quit (progress is saved)

  [bold]Batch actions:[/bold]  (shown for safe classifications only)
    [blue]a[/blue]  — Fix all identical patterns in this article
    [blue]F[/blue]  — Fix all safe occurrences in this article

  [bold]Investigative actions:[/bold]
    [blue]c[/blue]  — Show extended context (30 lines)
    [blue]l[/blue]  — List all <b> tags in this article
    [blue]d[/blue]  — Show unified diff of proposed change

  [bold]Meta actions:[/bold]
    [blue]![/blue]  — Flag this pattern as a false positive
    [blue]u[/blue]  — Undo the last fix
    [blue]?[/blue]  — Show this help screen
"""
        self.console.print(help_text)
        self.console.print()
        Prompt.ask("  Press Enter to return", default="")

    def _handle_edit(self, occurrence: BTagOccurrence) -> str:
        """
        Let the user edit the proposed fix before applying.

        Shows old and new text, asks for confirmation or manual override.
        """
        suggested = occurrence.suggested_fix or occurrence.raw_tag
        self.console.print()
        self.console.print(
            f"  [bold]Original:[/bold] {rich_escape(occurrence.raw_tag)}"
        )
        self.console.print(
            f"  [bold]Proposed:[/bold] [green]{rich_escape(suggested)}[/green]"
        )
        self.console.print()

        choice = Prompt.ask(
            "  Apply this fix?",
            choices=["y", "n", "e"],
            default="y",
        )

        if choice == 'y':
            old_text = self.current_wikitext
            new_text = fix_occurrence(self.current_wikitext, occurrence)
            if new_text != old_text:
                self.undo_stack.append((old_text, new_text))
                self.current_wikitext = new_text
                self.fixes_in_session += 1
                self.console.print("  [green]✓ Applied![/green]")
            return 'fixed'

        elif choice == 'e':
            # Let user type a replacement manually
            self.console.print()
            self.console.print(
                "  [yellow]Enter the replacement text"
                " (or leave empty to cancel):[/yellow]"
            )
            replacement = Prompt.ask("  > ", default="")
            if replacement:
                old_text = self.current_wikitext
                new_text = old_text.replace(occurrence.raw_tag, replacement, 1)
                if new_text != old_text:
                    self.undo_stack.append((old_text, new_text))
                    self.current_wikitext = new_text
                    self.fixes_in_session += 1
                    self.console.print("  [green]✓ Applied![/green]")
                return 'fixed'

        return 'skipped'

    # ─── Action input ─────────────────────────────────────────────

    def _get_action(self, occurrence: BTagOccurrence) -> str:
        """Prompt the user for an action. Returns the action key."""
        # Build available actions based on classification
        actions = []

        if occurrence.suggested_fix:
            actions.append(("[blue]f[/blue]ix", "f"))
        actions.append(("[blue]e[/blue]dit fix", "e"))

        if occurrence.is_safe:
            actions.append(("[blue]a[/blue]ll identical", "a"))
            actions.append(("[blue]F[/blue]ix all safe", "F"))
            # Show count of identical patterns
            if self.current_analysis:
                count = self.current_wikitext.count(occurrence.raw_tag)
                if count > 1:
                    actions[-2] = (f"[blue]a[/blue]ll identical ({count})", "a")

        actions.append(("[blue]s[/blue]kip", "s"))
        actions.append(("[blue]c[/blue]ontext", "c"))
        actions.append(("[blue]l[/blue]ist all", "l"))
        actions.append(("[blue]d[/blue]iff", "d"))

        if not occurrence.is_safe:
            actions.append(("[blue]![/blue] false positive", "!"))

        if self.undo_stack:
            actions.append(("[blue]u[/blue]ndo", "u"))

        actions.append(("[blue]?[/blue] help", "?"))
        actions.append(("[blue]q[/blue]uit", "q"))

        # Format the prompt line
        prompt_parts = [a[0] for a in actions]
        prompt_line = "  " + "  ".join(prompt_parts)

        self.console.print(prompt_line)
        self.console.print()

        valid_keys = {a[1] for a in actions}
        choice = Prompt.ask(
            "  Action",
            choices=list(valid_keys),
            default="s",
            show_choices=False,
        )

        return choice.lower()

    # ─── Session display ──────────────────────────────────────────

    def show_welcome(self):
        """Show the welcome/authentication banner."""
        self.console.clear()
        welcome = Panel(
            Text.from_markup(
                "[bold cyan]CWFix — CheckWiki Error #26 Fixer[/bold cyan]\n\n"
                "[dim]HTML [/dim][red]<b>[/red][dim] → wiki [/dim][green]'''[/green]\n\n"
                "This tool walks you through fixing CheckWiki Error #26\n"
                "on English Wikipedia, one article at a time.\n\n"
                "Every edit is attributed to YOUR Wikipedia account.",
            ),
            title="🔧",
            border_style="cyan",
        )
        self.console.print(welcome)
        self.console.print()

    def show_goodbye(self):
        """Show the farewell message with session stats."""
        self.console.print()
        summary = Panel(
            Text.from_markup(
                f"[bold green]Session complete![/bold green]\n\n"
                f"  Articles processed: {self.articles_done}\n"
                f"  Total fixes: [bold]{self.fixes_in_session}[/bold]\n\n"
                "[dim]Thank you for improving Wikipedia![/dim]"
            ),
            border_style="green",
        )
        self.console.print(summary)
        self.console.print()

    def show_auth_prompt(self):
        """Show the authentication setup prompt (rich version)."""
        self.console.clear()

        auth_panel = Panel(
            Text.from_markup(
                "[bold yellow]🔑 Authentication Required[/bold yellow]\n\n"
                "This tool uses a [bold]bot password[/bold] — a special,\n"
                "limited-use credential from Wikipedia.\n\n"
                "[green]✓[/green] Your main password is [bold]NEVER[/bold] used or stored\n"
                "[green]✓[/green] A bot password can only edit pages\n"
                "[green]✓[/green] It can be revoked at any time\n\n"
                "[bold]To create one:[/bold]\n\n"
                "  1. Open [blue]https://en.wikipedia.org/wiki/Special:BotPasswords[/blue]\n"
                "  2. Click \"Create a new bot password\"\n"
                "  3. Bot name: [bold]cwfix[/bold] (or anything you like)\n"
                "  4. Grant: [bold]Edit existing pages[/bold] only\n"
                "  5. Click \"Create\" and copy the generated password\n\n"
                "[yellow]⚠ When you're asked for your username later,[/yellow]\n"
                "[yellow]  enter just your Wikipedia username[/yellow]\n"
                "[yellow]  (like [bold]CoolEditor42[/bold]), not the full bot ID.[/yellow]\n"
                "[yellow]  The bot name and username are separate prompts.[/yellow]\n\n"
                "[dim]The password is stored in your OS keychain.[/dim]"
            ),
            border_style="yellow",
        )
        self.console.print(auth_panel)
        self.console.print()

# CWFix — CheckWiki Error #26 Interactive Fixer

**HTML `<b>` → wiki `'''` — convert bold markup on English Wikipedia**

CWFix is an interactive TUI tool that walks you through fixing [CheckWiki Error #26](https://checkwiki.toolforge.org/checkwiki.cgi?project=enwiki&view=only&id=26) (HTML `<b>` tags that should be wiki `'''` markup) on English Wikipedia, one article at a time.

## Quick Start

### Option A: Install globally (if you prefer)

```bash
pip install cwfix
cwfix
```

### Option B: Run from a virtual environment (recommended)

```bash
# Clone or cd into the project directory
cd cwfix/

# Create a virtual environment (keeps dependencies isolated)
python3 -m venv .venv

# Activate it
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate       # Windows

# Install the package and its dependencies
pip install -e .

# Run the tool
cwfix

# Later, when you're done:
deactivate
```

The next time you want to run the tool, just activate the venv again:

```bash
cd cwfix/
source .venv/bin/activate
cwfix
```

On first run, you'll be guided to create a [bot password](https://en.wikipedia.org/wiki/Special:BotPasswords) — a limited-use credential that only grants edit permissions. Your main password is never used or stored.

## Features

- **Smart classification** — distinguishes 7 contexts for `<b>` tags (simple bold, bold-italic, inside templates, inside nowiki, unmatched, etc.)
- **Safe auto-fix** — converts known-safe patterns automatically; flags risky ones for review
- **Interactive TUI** — color-coded terminal interface with rich context display
- **Batch operations** — fix all identical patterns or all safe occurrences in one keystroke
- **Progress persistence** — quit and resume with `cwfix --resume`
- **Screenreader context** — shows surrounding wikitext, classification badge, and proposed fix
- **Undo support** — revert the last fix if something looks wrong

### Actions

| Key | Action |
|-----|--------|
| `f` | Fix this occurrence |
| `e` | Edit the fix manually |
| `a` | Fix all identical patterns in this article |
| `F` | Fix all safe occurrences in this article |
| `s` | Skip this occurrence |
| `c` | Show extended context |
| `l` | List all `<b>` tags in this article |
| `d` | Show unified diff of proposed change |
| `!` | Flag as false positive |
| `u` | Undo last fix |
| `?` | Help |
| `q` | Quit (progress saved) |

## CLI Options

```bash
cwfix                        # Interactive mode
cwfix --batch-safe           # Auto-fix all safe occurrences
cwfix --batch-safe --auto    # Non-interactive batch mode
cwfix --dry-run              # Preview without saving
cwfix --articles 10          # Process only 10 articles
cwfix --resume               # Resume from last position
cwfix --reset                # Reset progress cache
cwfix --report               # Show progress statistics
cwfix --pause                # Pause with "Press Enter" after each action
cwfix --no-done              # Skip signaling "done" to CheckWiki
```

### Options explained

| Flag | Default | Effect |
|------|---------|--------|
| `--pause` | off | After each fix action, wait for Enter before moving to the next occurrence. Useful for slow readers or reviewing batch fixes. |
| `--no-done` | on | By default, after fixing an article the tool signals "done" to the CheckWiki queue (same as clicking the [Done] link on the web page). Use `--no-done` to skip this. |
| `--batch-safe` | off | Auto-fix all safe classifications without interactive prompts. |
| `--dry-run` | off | Show what would be changed without actually saving. |
| `--articles N` | all | Only process N articles (useful for testing). |
| `--resume` | off | Resume from the last saved position. |
| `--reset` | off | Clear all saved progress. |
| `--report` | off | Show statistics of articles fixed so far. |

## How Authentication Works

CWFix uses [bot passwords](https://en.wikipedia.org/wiki/Special:BotPasswords) — a Wikipedia security feature that lets you create scoped, revocable credentials for automated tools:

1. Go to `Special:BotPasswords` on enwiki
2. Create a bot named "cwfix" with "Edit existing pages" grant
3. Paste the generated password into the tool
4. The password is stored securely in your OS keychain

Every edit is attributed to **your Wikipedia username**, not an anonymous proxy.

### ⚠️ Username quirk: spaces → underscores

The MediaWiki API requires the **internal database form** of usernames, where spaces
are replaced with underscores (`_`). You can type your username with spaces (e.g.,
`"AL Wiki MIT"`) — the tool normalizes this automatically. But if you're writing your
own scripts against the API, remember that `lgname="AL Wiki MIT"` will fail with
"Unknown error" while `lgname="AL_Wiki_MIT"` will work.

## Design

See [DESIGN.md](DESIGN.md) for the full design document covering:
- Classification engine taxonomy
- TUI color scheme design
- Authentication architecture
- Implementation decisions
- Future enhancement roadmap

## Tests

```bash
# From the project directory with venv activated:
pip install -e ".[test]"
pytest
```

97 tests covering classification, fixer transformations, caching, auth, CheckWiki parsing, and the engine orchestrator.

## License

MIT

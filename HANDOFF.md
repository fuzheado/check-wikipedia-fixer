# Handoff: CWFix — CheckWiki Interactive Fixer

> **Status:** Working prototype. Successfully fixes Error #26 (`<b>` → `'''`) on enwiki interactively.
> **Repo:** https://github.com/fuzheado/check-wikipedia-fixer

---

## Quick Start

```bash
git clone https://github.com/fuzheado/check-wikipedia-fixer.git
cd check-wikipedia-fixer
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
cwfix                          # run interactively
cwfix --help                   # see all options
pytest -q                      # 99 tests
```

---

## What Exists

### Files

| Module | Lines | What it does |
|--------|-------|-------------|
| `cwfix/classifier.py` | ~450 | 7-category classification engine (SAFE_SIMPLE, SAFE_BOLD_ITALIC, SAFE_NESTED, TEMPLATE_PARAM, NO_CLOSE_TAG, INSIDE_NOWIKI, SPURIOUS). Uses `mwparserfromhell` AST + regex supplement for edge cases. Template registry (SAFE_TEMPLATES / RISKY_TEMPLATES). |
| `cwfix/fixer.py` | ~180 | Transform functions: `fix_simple_bold`, `fix_bold_italic`, `fix_bold_link`, `fix_all_identical`. Also: `generate_diff`, `make_edit_summary`. |
| `cwfix/engine.py` | ~210 | Orchestrator: `BTagOccurrence` / `ArticleAnalysis` dataclasses, `analyze_article()`, `fix_occurrence()`, `fix_all_identical_pattern()`, `fix_all_safe_occurrences()`. |
| `cwfix/auth.py` | ~300 | Bot password auth via `WikipediaSession` (POST login + CSRF token), `CredentialStore` (OS keyring with encrypted file fallback), `RateLimiter`. |
| `cwfix/checkwiki.py` | ~230 | Fetches article list from CheckWiki (HTML parser), fetches wikitext via Action API, `signal_done()` to mark articles as done. |
| `cwfix/cache.py` | ~180 | SQLite progress cache. Tracks article status (pending/fixed/skipped), fix counts, supports resume. |
| `cwfix/tui.py` | ~540 | Rich-based interactive UI. 12 actions across 4 tiers. Color-coded classification badges, context panels, diff viewer, list-all table, help screen. |
| `cwfix/main.py` | ~320 | Click CLI. Flags: `--batch-safe`, `--dry-run`, `--articles N`, `--resume`, `--reset`, `--report`, `--pause`, `--done/--no-done`. |
| `tests/` | 6 files | 99 tests: classifier (25), fixer (15), auth (14), cache (18), checkwiki (15), engine (12). |

### Project docs

| File | What it covers |
|------|---------------|
| `DESIGN.md` | Full design spec: motivation, problem analysis, classification taxonomy, TUI design, architecture, implementation plan, future roadmap. |
| `README.md` | User-facing: quick start, features, CLI options, auth guide, roadmap. |

---

## Architecture

```
main.py (click CLI)
  ├── auth.py         — Bot password + Wikipedia session
  ├── checkwiki.py    — Fetch article list + signal done
  ├── cache.py        — SQLite progress tracker
  ├── engine.py       — Orchestrator (fetch → classify → fix)
  │   ├── classifier.py  — AST parsing + 7-class taxonomy
  │   └── fixer.py       — <b>→''' transformations
  └── tui.py          — Rich terminal UI
```

**Data flow:** CheckWiki URL → article list → for each article: fetch wikitext → parse with mwparserfromhell → classify each `<b>` tag → present to user → apply fix → save via API → signal done to CheckWiki.

---

## Known Issues & Gotchas

### 1. CheckWiki pagination is not implemented
The fetcher currently only grabs what appears on the first page of results (default ~25 entries). The CheckWiki tool supports `offset=N&limit=M` parameters and `sort=name|text|date` but these are not used. See [Future Work](#priority-1-fetching--queue-management) below.

### 2. Username normalization (spaces → underscores)
The MediaWiki `action=login` API requires underscores in usernames where the wiki display has spaces. Fixed in `auth.py` with automatic normalization, but worth knowing if you're writing raw API calls. The `Special:BotPasswords` confirmation message shows spaces, which is misleading.

### 3. `action=login` requires POST
The MediaWiki login endpoint rejects GET requests. Currently using `session.post()` with two-step token handling (`NeedToken` → retry with `lgtoken`). This is working but fragile if the API changes.

### 4. `mwparserfromhell` interprets wiki ''' as HTML `<b>`
The parser converts `'''bold'''` to internal `<b>` tag nodes with `wiki_markup="'''"`. The classifier filters these out by checking `t.wiki_markup is None`. If a newer version of mwparserfromhell changes this behavior, the classifier will break.

### 5. Auth tests don't test actual network
Auth tests mock the network layer. There's no integration test that actually logs in and makes an edit. Manual testing is required for any auth changes.

### 6. Done-signal is fire-and-forget
`signal_done()` makes a GET request to CheckWiki's done URL but doesn't verify the article was actually marked done. The CheckWiki tool may silently ignore the signal if the article format doesn't match.

### 7. Undo is session-only
Undo only reverts changes made within the current session. There's no cross-session undo via page history lookups yet.

### 8. "a" action after edits to same pattern
If the user manually edits a `<b>` tag and then presses "a", the `str.replace()` uses the original `raw_tag` from the analysis, which may no longer match. The tool handles this gracefully (no-op), but it can confuse the user.

---

## Future Work (Prioritized)

### Priority 1: Fetching & Queue Management

**Problem:** Currently only fetches the first ~25 results from CheckWiki. The tool has no way to process the full error list, and articles are processed in whatever order CheckWiki returns them.

**What's needed:**
1. **Pagination** — Use `offset=N&limit=M` URL parameters to fetch ALL entries across multiple pages. The limit parameter accepts up to 200+ per page.
2. **Sorting** — Use `sort=name|text|date` to control the order articles are fetched. The fetcher needs to sort client-side or via URL params.
3. **Processing order** — After fetching the full list, let the user choose the order to process: alphabetically (good for avoiding topic bias), by date (oldest errors first), by error snippet (group similar patterns for efficient batch fixes), or randomly.
4. **Queue file** — Save the fetched queue to a local JSON file so the user can inspect, reorder, or splice lists before starting.

**How to implement:**
- Modify `fetch_article_list()` in `checkwiki.py` to accept `offset`, `limit`, `sort` params
- Add a loop that pages through all results until empty
- Add a `--order` CLI flag (`alpha`, `date`, `text`, `random`)
- Store the full ordered list in the cache before processing begins

### Priority 2: Multi-Error Support

**Problem:** The tool is hardcoded to Error #26. The classification engine and fixer are error-type-agnostic, but the CLI, TUI, and CheckWiki fetcher all assume `<b>` → `'''`.

**What's needed:**
1. Add `--error N` / `-e N` flag to specify the error ID
2. Make `checkwiki.py` parameterize the error ID throughout
3. Make `fixer.py` accept the error type and dispatch to the right transform
4. Make `classifier.py` accept the tag name to filter on (`b`, `i`, `a`, etc.)
5. Update the edit summary to reference the correct error ID

**Low-hanging fruit:** Error #38 (`<i>` → `''`) shares almost the same classification logic and just needs a new transform function. Error #4 (`<a>` → wiki links) needs different classification (check for proper link syntax).

### Priority 3: Rendered Preview (action `p`)

**Problem:** The `p` action exists in the TUI action reference but is not implemented. It was postponed from v1.0 because it requires Parsoid API calls.

**What's needed:**
- Call the MediaWiki REST API `/page/html/{title}` endpoint
- Parse the HTML and highlight the region around the `<b>` tag
- Display it in a side panel alongside the wikitext

### Priority 4: False Positive Rule Persistence

**Problem:** The `!` (flag as false positive) action exists in the TUI but only prints an acknowledgment. Rules are not saved to disk.

**What's needed:**
- Save flagged patterns to `~/.config/cwfix/rules/user.json`
- Load them at startup and auto-skip matching patterns
- Provide `--share-rules` / `--import-rules` for community curation

### Priority 5: Web Version on Toolforge

**Problem:** CLI-only limits the audience to terminal-savvy editors. A web version would reach more volunteers.

**What's needed:**
- Flask/FastAPI app with OAuth 2.0 login (instead of bot passwords)
- Same classification engine, called as a library
- Web-based yes/no/skip interface
- Hosted on Toolforge Kubernetes

### Priority 6: Automated Bot Mode

**Problem:** The tool requires a human in the loop for every decision. For the ~70% of occurrences classified as SAFE_*, a bot could fix them automatically.

**What's needed:**
- When enough human-reviewed data exists, train a classifier to predict safety
- Run as a Toolforge bot account (like WikiCleanerBot)
- Only fix SAFE classifications; flag everything else for human review

---

## Tests

```bash
pytest -q                           # 99 tests, all pass
pytest tests/test_classifier.py -v  # classification tests
pytest tests/test_fixer.py -v       # transformation tests
pytest tests/test_auth.py -v        # auth + session tests
pytest tests/test_cache.py -v       # cache tests
pytest tests/test_checkwiki.py -v   # CheckWiki parsing tests
pytest tests/test_engine.py -v      # engine orchestration tests
```

No integration tests exist that make real API calls. Any changes to auth or edit flow should be tested manually with a bot password.

---

## Key Design Decisions (for new contributors)

| Decision | Rationale |
|----------|-----------|
| **TUI not web** | Lower infrastructure cost, zero server setup, single `pip install`. Web version is a future port. |
| **`mwparserfromhell` not regex** | Proper AST handles comments, nowiki, nested templates. Regex would miss edge cases. Regex supplement fills gaps (unmatched tags, nowiki). |
| **Bot passwords not OAuth** | Standard for single-user CLI tools. Scoped, revocable, no server needed. OAuth is better for multi-user web apps. |
| **Rich for TUI** | Mature, well-documented, handles dark/light terminals, progress bars, tables, panels. |
| **SQLite cache** | Zero-dependency, supports resume, simple schema. Good enough for single-user CLI. |
| **Position-based dedup** | Between mwparserfromhell and regex paths, positions in the wikitext are used to avoid double-counting tags. |

---

## Contact / Origins

Built for the [WikiProject Check Wikipedia](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_Check_Wikipedia) community. Started as a prototype for Error #26 (HTML `<b>` → wiki `'''`) with the goal of generalizing to a modular fixer framework.

Questions about design decisions can be found in `DESIGN.md`. Bug reports and feature requests should go to the GitHub Issues page.

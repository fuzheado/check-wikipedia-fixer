# CWFix — CheckWiki Error #26 Interactive Fixer

> **HTML `<b>` → wiki `'''` — an interactive TUI tool for fixing bold markup on English Wikipedia**

---

## Table of Contents

1. [Motivation](#1-motivation)
2. [The Problem: Error #26](#2-the-problem-error-26)
3. [Design Decisions](#3-design-decisions)
4. [Classification Engine](#4-classification-engine)
5. [Interactive TUI Design](#5-interactive-tui-design)
6. [Authentication](#6-authentication)
7. [Architecture](#7-architecture)
8. [Implementation Plan (v1.0)](#8-implementation-plan-v10)
9. [Future Enhancements (Beyond v1.0)](#9-future-enhancements-beyond-v10)
10. [References](#10-references)

---

## 1. Motivation

The [Check Wikipedia project](https://checkwiki.toolforge.org/) scans English Wikipedia and identifies over 80 classes of wikitext errors. **Error #26** — "HTML text style element `<b>` (bold)" — currently flags **hundreds of articles** that use HTML `<b>` tags instead of the standard wiki markup `'''` (three apostrophes).

This is a **maintenance debt problem**. The errors accumulate faster than volunteers fix them because:

- **Existing tools are too crude** — WPCleaner and AWB can auto-fix, but they don't handle context-dependent cases (template parameters, nested markup) well, so editors avoid running them blindly.
- **Manual fixing is tedious** — Opening each article, scanning for `<b>`, and editing one-by-one is slow and unrewarding.
- **The error is low priority** — CheckWiki categorizes it as "low," so it gets deprioritized against broken links, missing references, and malformation issues. But it affects **accessibility** and **source readability**, and fixing it makes the wikitext consistent with community norms (see [WP:Deviations](https://en.wikipedia.org/wiki/Wikipedia:Deviations)).

**CWFix** is designed to fill the gap: an interactive TUI tool that walks an editor through each `<b>` occurrence, classifies whether it's safe to fix, shows context, and lets them decide — with batch operations for obvious patterns. Every fix is attributed to the user's own Wikipedia account.

---

## 2. The Problem: Error #26

### 2.1 What CheckWiki Detects

| Field | Value |
|---|---|
| **Error ID** | 26 |
| **Description** | HTML text style element `<b>` (bold) |
| **Priority** | Low |
| **Bot-fixable** | Yes |
| **Reason** | Accessibility, Source readability |
| **Detection** | Any `<b>` tag in the wikitext |
| **Policy** | Should use wiki markup `'''`. See [WP:Deviations](https://en.wikipedia.org/wiki/Wikipedia:Deviations) |

### 2.2 Real-World Patterns Found in the Wild

After examining the wikitext of dozens of flagged articles, all uses of `<b>` fall into one of these categories:

#### Pattern A: Simple bold — prose text

```wikitext
<b>25.1</b> – 15-minute AMRAP: 3 Lateral
```

**Verdict:** ✅ Always safe. Convert to `'''25.1'''`.

#### Pattern B: Bold + italic (nested)

```wikitext
{{center|<b>''Elected unopposed''</b>}}
```

The `<b>` wraps an already-italic `''...''` span. The correct conversion is `'''''Elected unopposed'''''` (5 apostrophes). This appears **massively** in Indian election articles — in one article alone there were 22 identical occurrences.

**Verdict:** ✅ Always safe. Convert to `'''''Elected unopposed'''''`.

#### Pattern C: Bold wrapping a wiki link

```wikitext
|legendItem1=<b>Morocco</b>,1 |legendItem2=<b>Portugal</b>,7,14
```

This is inside an `{{OSM Location map}}` template's `legendItem` parameter. These template parameters may or may not accept wiki markup — the `<b>` may be the only way to get bold rendering there.

**Verdict:** ⚠️ Context-dependent. Must check the template documentation. Auto-fix may break rendering.

#### Pattern D: Unmatched `<b>` (no closing tag)

```wikitext
Some stray <b> with no close
```

**Verdict:** 🚫 Can't auto-fix. Requires manual investigation — the tag may be a remnant of a broken edit.

#### Pattern E: Inside `<nowiki>` / `<code>` / `<pre>`

```wikitext
<nowiki>Some <b>example</b> code</nowiki>
```

**Verdict:** 🚫 Skip. The `<b>` is not rendering as bold — it's being displayed literally.

### 2.3 Frequency & Distribution

- **~500+ articles** currently flagged on enwiki (fluctuates as articles are fixed and new ones are scanned)
- **Common topics**: Indian legislative election results (hundreds of table cells with `<b>''Elected unopposed''</b>`), sports tournament pages (legend maps, standings tables), CrossFit Games articles
- **Pattern B dominates** — roughly 60-70% of all occurrences are the safe bold-italic pattern
- **Pattern C is the minority** — maybe 10-15%, but requires the most judgment

---

## 3. Design Decisions

### 3.1 Why Not Just Use WPCleaner or AWB?

| Tool | Limitations for this task |
|------|--------------------------|
| **WPCleaner** | GUI-only (Java). Doesn't classify risky vs safe — batch mode may break template params. No way to review by classification. |
| **AWB** | Windows-only (or Mono). Regex-based find/replace with no AST awareness. Can't handle nested bold-italic correctly in all cases. |
| **WikiCleanerBot** | Already fixes this error automatically on dump analysis, but only catches a subset. Many articles slip through. |
| **Manual editing** | Unbearably slow for 500+ articles × dozens of occurrences each. |

CWFix is **not competing with these** — it's filling the gap between "fully automatic bot" (which can't handle edge cases) and "manual editing" (which is too slow).

### 3.2 Why a TUI, Not a Web App?

| Consideration | TUI (this project) | Web app |
|---|---|---|
| **Setup friction** | Install via pip, run once | Need server, OAuth registration, hosting |
| **Latency** | Zero for UI; API calls only for fetch/save | Network latency for every interaction |
| **Offline capability** | Can cache article lists, work offline on decisions | Requires connection |
| **Credential security** | Stored locally in OS keychain | Must manage OAuth tokens server-side |
| **Target audience** | Wiki editors comfortable with terminal | Broader audience, but higher infrastructure cost |
| **Development complexity** | Low (rich, click, requests) | High (Flask/Django, OAuth, hosting on Toolforge) |

For v1.0, a TUI keeps the scope tight and the deployment simple: `pip install cwfix && cwfix`.

### 3.3 Why `mwparserfromhell` Instead of Regex?

Regex against wikitext is **brittle** and **dangerous**. Consider:

```wikitext
<!-- <b>this is not rendering</b> -->
{{template|param=<b>value</b>}}
<nowiki><b>literal text</b></nowiki>
```

A regex would catch all four. But only the second one might be a real bold. `mwparserfromhell` produces a proper AST that tells us: "this `<b>` tag is inside a comment node," or "this `<b>` tag is inside a template parameter value." That classification is impossible with regex.

**Counterpoint:** `mwparserfromhell` is slower than regex. But for a single-article parse (~100KB of wikitext max), the difference is negligible (~50ms vs ~5ms). The correctness gain is enormous.

### 3.4 Why Nine Actions Instead of Three?

Detailed rationale in [Section 5: Interactive TUI Design](#5-interactive-tui-design). The short version is that real-world `<b>` usage falls into multiple categories with different fix strategies, and a binary yes/no forces the user to either skip fixable patterns or break template params. The classification engine drives **which actions are available**, keeping the prompt uncluttered.

### 3.5 Why Bot Passwords Instead of OAuth 2.0?

Detailed rationale in [Section 6: Authentication](#6-authentication). The short version: bot passwords are the Wikipedia-recommended standard for single-user CLI tools — scoped, revocable, and requiring no server infrastructure. OAuth 2.0 is better for multi-user web apps but adds heavy setup friction for a CLI tool.

---

## 4. Classification Engine

### 4.1 Classification Taxonomy

Every `<b>` tag found by the parser is assigned one of these classifications:

| Class | Code | Color | Meaning | Auto-fix available? |
|-------|------|-------|---------|---------------------|
| **SAFE_SIMPLE** | `SS` | 🟢 Green | `<b>text</b>` in article text. Straightforward conversion. | ✅ Yes |
| **SAFE_BOLD_ITALIC** | `BI` | 🟢 Green | `<b>''text''</b>` — nested bold-italic. | ✅ Yes |
| **SAFE_NESTED** | `SN` | 🟢 Green | `<b>[[link]]</b>` or other wiki markup inside bold. | ✅ Yes |
| **TEMPLATE_PARAM** | `TP` | 🟡 Yellow | Inside a template parameter value. May or may not be safe. | ⚠️ With preview |
| **NO_CLOSE_TAG** | `NC` | 🔴 Red | `<b>` without matching `</b>`. Needs investigation. | ❌ No |
| **INSIDE_NOWIKI** | `NW` | ⚪ Gray | Inside `<nowiki>`, `<code>`, `<pre>`, or `<!-- comment -->`. | ❌ No (skip) |
| **SPURIOUS** | `SP` | 🔴 Red | Appears to be a false positive or non-rendering usage. | ❌ Skip |

### 4.2 Classification Algorithm

```python
def classify(tag_node, parent_nodes, wikitext_context):
    """
    Determine the classification of a single <b> tag.
    
    Args:
        tag_node: The mwparserfromhell Tag node for <b>
        parent_nodes: List of ancestor nodes in the AST
        wikitext_context: Surrounding raw wikitext string
    
    Returns:
        Classification enum value
    """
    
    # 1. Is it inside a nowiki/comment/code/pre?
    for ancestor in parent_nodes:
        if ancestor.tag in ('nowiki', 'code', 'pre'):
            return Classification.INSIDE_NOWIKI
        if isinstance(ancestor, mwparserfromhell.nodes.Comment):
            return Classification.INSIDE_NOWIKI
    
    # 2. Is there a matching closing tag?
    content = tag_node.contents  # text between <b> and </b>
    if content is None or tag_node.self_closing:
        return Classification.NO_CLOSE_TAG
    
    # 3. Is it inside a template parameter?
    for ancestor in parent_nodes:
        if isinstance(ancestor, mwparserfromhell.nodes.Template):
            # Check if the <b> is inside a parameter value
            param = ancestor.parameters.get(ancestor.parameters.index_of(tag_node))
            if param:
                # Check our known-safe and known-risky template lists
                template_name = str(ancestor.name).strip()
                if template_name in SAFE_TEMPLATES:
                    break  # fall through to content analysis
                elif template_name in RISKY_TEMPLATES:
                    return Classification.TEMPLATE_PARAM
                else:
                    # Unknown template — cautious default
                    return Classification.TEMPLATE_PARAM
    
    # 4. Analyze the content inside <b>...</b>
    stripped = content.strip()
    
    # Check for italic inside bold
    has_italic = "''" in stripped
    
    # Check for wiki links
    has_wikilink = "[[" in stripped
    
    # Check for template calls
    has_template = "{{" in stripped
    
    if not has_italic and not has_wikilink and not has_template:
        return Classification.SAFE_SIMPLE
    elif has_italic and not has_wikilink:
        return Classification.SAFE_BOLD_ITALIC
    else:
        return Classification.SAFE_NESTED
```

### 4.3 Known Template Registry

The engine maintains a registry of templates where `<b>` behavior is known:

```python
# Templates that SAFELY accept wiki markup in their parameters
SAFE_TEMPLATES = {
    'center', 'align', 'color', 'font', 'small', 'big',
}

# Templates where <b> may be necessary for rendering
RISKY_TEMPLATES = {
    'OSM Location map',
    'Location map',
    'legend',
    'Legend',
    'Infobox',       # Infobox params often render raw HTML
    'Infobox football biography',
}

# This registry is user-extensible via ! (flag as false positive)
```

---

## 5. Interactive TUI Design

### 5.1 Color Scheme

The design uses the `rich` library for terminal rendering. Colors are chosen to be distinguishable on both light and dark terminals and colorblind-safe for the critical parts.

| Element | Color | Purpose |
|---------|-------|---------|
| **Safe badge** (SS/BI/SN) | `bold green` | "Go ahead — this fix is safe" |
| **Risky badge** (TP) | `bold yellow` | "Proceed with caution" |
| **Badge** (NC/SP) | `bold red` | "Stop — needs manual review" |
| **Skip badge** (NW) | `dim white` | "Not applicable, moving on" |
| **`<b>` / `</b>` tags** | `white on #880000` | Red background — the problem target |
| **Bold content** | `bold white` | What the bold applies to |
| **Surrounding wikitext** | `dim` (gray) | Background context |
| **Transformation arrow** | `bold cyan` | `────→` visually separates old from new |
| **Proposed fix** | `green` | What the wikitext will become |
| **Article title** | `bold cyan` | Navigation landmark |
| **Progress counter** | `yellow` | "Article 12 of 53" |
| **Action keys** | `bold blue` | The letter in `[f]ix`, `[s]kip` |

### 5.2 Main Interactive View

```
 ┌─────────────────────────────────────────────────────────────────┐
 │ Article 12 of 53  —  1957 Mysore State Legislative Assembly...  │
 │ Progress: ██████████████░░░░░░░░░░░░  23%                       │
 │ Identical patterns remaining: 21                                 │
 └─────────────────────────────────────────────────────────────────┘

 ╔══════════════════════════════════════════════════════════════════╗
 ║  ┌────────────────────────────────────────────────────────┐     ║
 ║  │  [line 578] ═══════════════════════════════════════════ │     ║
 ║  │                                                         │     ║
 ║  │  | 15 || [[Sampagaon II Assembly constituency|...]]     │     ║
 ║  │  || Nagnur Mugatsab Nabisab|| {{party name with color…  │     ║
 ║  │  ! colspan="8" | {{center|  ██''Elected unopposed''██ }}│     ║
 ║  │  |                                                      │     ║
 ║  │  16||[[Khanapur, Karnataka...]] ════════════════════════│     ║
 ║  └────────────────────────────────────────────────────────┘     ║
 ║                                                                ║
 ║   🟢  SAFE_BOLD_ITALIC — Safe to fix                            ║
 ║                                                                ║
 ║   <b>''Elected unopposed''</b>                                  ║
 ║   ───────────────────────────────────────────→                  ║
 ║   '''''Elected unopposed'''''                                   ║
 ║                                                                ║
 ╚══════════════════════════════════════════════════════════════════╝

 [f]ix  [e]dit fix  [a]ll identical (21)  [F]ix all safe  [s]kip
 [c]ontext  [l]ist all  [d]iff  [!] false positive  [q]uit  [?] help
```

### 5.3 Action Reference

#### Tier 1: Core (always shown)

| Key | Action | Behavior |
|-----|--------|----------|
| `f` | **Fix** | Apply the suggested transformation and save. Moves to the next occurrence. |
| `e` | **Edit** | Open the proposed fix in an editable inline buffer (or `$EDITOR`). User modifies, then confirms. Applies the edited version. |
| `s` | **Skip** | Skip this occurrence. Moves to the next without changing anything. |
| `q` | **Quit** | Save progress (record which occurrences were handled), exit. On restart, resume from last position. |

#### Tier 2: Batch / Power (shown for SAFE classifications only)

| Key | Action | Behavior |
|-----|--------|----------|
| `a` | **All identical** | Find every occurrence in this article with the exact same `<b>content</b>` string and apply the same fix. After fixing, reports: "Fixed 22 of 22 identical occurrences." |
| `F` | **Fix all safe** | Fix every occurrence classified as SAFE_SIMPLE, SAFE_BOLD_ITALIC, or SAFE_NESTED in this article in one batch. Presents a summary before committing: "The following 26 occurrences will be fixed. Proceed? [y/N]" |

#### Tier 3: Investigative (shown for all classifications)

| Key | Action | Behavior |
|-----|--------|----------|
| `c` | **Context+** | Expand the context window from 10 lines to 30 lines around the `<b>` tag. Useful when the tag is in a complex template. |
| `p` | **Preview rendered** | Fetch the rendered HTML for this section of the page (via Parsoid REST API) and display it. Shows what the bold *looks like* in the browser. Only available when rendered preview differs from source. |
| `l` | **List all** | Show a summary table of **every** `<b>` in the current article — line number, classification, context snippet, and status (fixed/skipped/pending). The user can jump to a specific occurrence by number. |
| `d` | **Diff** | Show a full unified diff (`git diff`-style) of the wikitext change that will be made. Green lines for additions, red for removed. |

#### Tier 4: Meta (always shown)

| Key | Action | Behavior |
|-----|--------|----------|
| `!` | **Flag as false positive** | Mark this pattern (e.g. `<b>` inside `legendItem=` of `{{OSM Location map}}`) so the tool remembers to skip it in future articles. Added to a local rules file under `~/.config/cwfix/rules/`. |
| `?` | **Help** | Show the full keybinding reference. |
| `u` | **Undo last** | Revert the most recent fix. Useful after a batch `a` or `F` went wrong. Only available if there's a fix to undo. |

### 5.4 The "List All" View (action `l`)

```
 ╔══════════════════════════════════════════════════════════════════╗
 ║  All <b> tags in: 1957 Mysore State Legislative Assembly...     ║
 ║  Total: 28 occurrences  (22 safe  |  0 risky  |  6 skip)       ║
 ║                                                                  ║
 ║  #    Line  Class       Context snippet                     Status║
 ║  ─── ───── ─────────── ─────────────────────────────────── ───── ║
 ║  →1    578 🟢 BOLD_ITAL  {{center|<b>''Elected unopposed''… PEND ║
 ║   2    712 🟢 BOLD_ITAL  {{center|<b>''Elected unopposed''… PEND ║
 ║   3    801 🟢 BOLD_ITAL  {{center|<b>''Elected unopposed''… PEND ║
 ║  ...                                                             ║
 ║  22   2450 🟢 BOLD_ITAL  {{center|<b>''Elected unopposed''… PEND ║
 ║  23   2490 ⚪ NOWIKI     <nowiki>foo <b>bar</b> baz</nowiki… SKIP ║
 ║  24   2512 ⚪ NOWIKI     <nowiki>foo <b>bar</b> baz</nowiki… SKIP ║
 ║  25   2601 🔴 NO_CLOSE   Some stray <b> with no close …      PEND ║
 ║  26   2700 🔴 NO_CLOSE   Another stray <b> …                 PEND ║
 ║  27   2803 🟡 TEMPLATE   |legendItem1=<b>Canada</b> …        PEND ║
 ║  28   2810 🟡 TEMPLATE   |legendItem2=<b>United S…           PEND ║
 ║                                                                  ║
 ║  → = current position                                           ║
 ║                                                                  ║
 ║  [j]ump to #  [f]ix all safe  [a]ll identical  [r]eturn         ║
 ╚══════════════════════════════════════════════════════════════════╝
```

### 5.5 Batch Mode (non-interactive)

For users who want to fix all safe occurrences across ALL articles without reviewing each one:

```bash
cwfix --batch-safe          # Fix all SAFE_* classifications, skip the rest
cwfix --batch-safe --auto   # Same, but non-interactive (no prompts at all)
cwfix --dry-run             # Show what would be changed, don't actually save
cwfix --articles N          # Only process N articles (for testing)
cwfix --resume              # Resume from last saved position
cwfix --report              # Generate a markdown report of all articles and fixes
```

---

## 6. Authentication

### 6.1 Why Bot Passwords

Wikipedia provides `Special:BotPasswords` as the recommended way to delegate edit permissions to a tool. A bot password is a **scoped, revocable credential** that:

- Can only do what the user explicitly grants (e.g., "Edit existing pages" and nothing else)
- Can be revoked at any time without affecting the user's main password
- Is a one-time generated string — not the user's real password
- Shows up separately in the user's contributions and logs
- Is the standard used by AWB, Pywikibot, and hundreds of other tools

### 6.2 First-Run Authentication Flow

```
$ cwfix

  ╔══════════════════════════════════════════════════════════════════╗
  ║            🔧 CWFix — CheckWiki Error #26 Fixer                  ║
  ║        HTML <b> → wiki ''' bold markup converter                 ║
  ║                                                                  ║
  ║  This tool will walk you through Fixing CheckWiki Error #26      ║
  ║  on English Wikipedia, one article at a time.                    ║
  ║                                                                  ║
  ║  Every edit you make will be attributed to YOUR Wikipedia         ║
  ║  account — never an anonymous proxy.                             ║
  ╚══════════════════════════════════════════════════════════════════╝

  ✓ No saved credentials found.

  ┌─────────────────────────────────────────────────────────────────┐
  │  🔑 HOW AUTHENTICATION WORKS                                    │
  │                                                                  │
  │  This tool uses a "bot password" — a special, limited-use        │
  │  credential that Wikipedia provides specifically for scripts     │
  │  and automated tools.                                            │
  │                                                                  │
  │  ✅ YOUR MAIN PASSWORD IS NEVER USED OR STORED                   │
  │                                                                  │
  │  A bot password:                                                 │
  │    • Can ONLY edit pages (if you grant that permission)          │
  │    • Can be REVOKED at any time from Wikipedia                   │
  │    • Is a one-time generated string (not your real password)     │
  │    • Shows edits under YOUR username                             │
  │    • Is safe to store locally on your machine                    │
  │                                                                  │
  │  The credential is encrypted on disk using your OS keychain.     │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │  📋 SETUP INSTRUCTIONS                                          │
  │                                                                  │
  │  STEP 1: Open this link in your browser:                         │
  │                                                                  │
  │    https://en.wikipedia.org/wiki/Special:BotPasswords            │
  │                                                                  │
  │  STEP 2: Click "Create a new bot password"                       │
  │                                                                  │
  │    • Bot name:  cwfix                                            │
  │      (or anything you like — this is just for your reference)    │
  │                                                                  │
  │    • Grants: Check the following permissions:                   │
  │                                                                  │
  │      ☑ Edit existing pages                                       │
  │      ☑ (optional) View deleted history and information          │
  │         (useful for reviewing page history before editing)       │
  │                                                                  │
  │      Do NOT check: High-volume editing, Move pages, Delete       │
  │      pages, Create accounts, or any other admin-level grants.    │
  │      This tool only needs to edit existing pages.                │
  │                                                                  │
  │  STEP 3: Click "Create"                                          │
  │                                                                  │
  │    Wikipedia will show you a password like:                      │
  │      abcd1234567890abcdef1234567890abcdef12                      │
  │                                                                  │
  │    Copy it. It will never be shown again.                        │
  │                                                                  │
  │  STEP 4: Enter your details below                                │
  └─────────────────────────────────────────────────────────────────┘

  Wikipedia username: ████████████████████████████████████████████████
  Bot name [cwfix]: █████████████████████████████████████████████████
  Bot password: ██████████████████████████████████████████████████████

  [Test & Save]

  Testing credentials... ✓ Authenticated as CoolEditor42

  → Credentials saved securely to OS keychain.
  → Session initialized. Ready to fix 527 articles.

  Starting interactive session? [Y/n]: █
```

### 6.3 What Gets Stored

Credentials are stored using the **OS-native keyring** (via the `keyring` Python library):

- **macOS**: Keychain Access (`~/Library/Keychains/`)
- **Linux**: libsecret / gnome-keyring / KDE Wallet
- **Windows**: Windows Credential Locker
- **Fallback**: Encrypted file at `~/.config/cwfix/auth.json` (AES-256-GCM, key derived from a master password prompt)

```python
import keyring

# Store
keyring.set_password("cwfix", "CoolEditor42@cwfix", bot_password)

# Retrieve
password = keyring.get_password("cwfix", "CoolEditor42@cwfix")

# Delete (on logout / revoke)
keyring.delete_password("cwfix", "CoolEditor42@cwfix")
```

The auth config also stores metadata:

```json
{
  "username": "CoolEditor42",
  "bot_name": "cwfix",
  "wiki": "en.wikipedia.org",
  "authenticated_at": "2026-06-08T14:30:00Z",
  "last_session": "2026-06-08T15:00:00Z"
}
```

**The bot password itself never touches disk in plaintext** — it lives only in the OS keyring or encrypted file.

### 6.4 Session Management

```python
class WikipediaSession:
    """Manages an authenticated session with the Wikipedia Action API."""
    
    def __init__(self, username, bot_name, password):
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(f"{username}@{bot_name}", password)
        self.session.headers.update({
            'User-Agent': (
                'CWFix/1.0 '
                '(https://en.wikipedia.org/wiki/User:USERNAME; '
                'user@example.com) '
                'CheckWikiError26Fixer'
            ),
            'Api-User-Agent': 'CWFix/1.0'
        })
        self.username = username
        self.csrf_token = None
    
    def login(self):
        """Obtain cookies and CSRF token."""
        # Login
        login_resp = self.session.get('https://en.wikipedia.org/w/api.php', params={
            'action': 'login',
            'lgname': f"{self.username}@{self.bot_name}",
            'lgpassword': self.password,
            'format': 'json'
        }).json()
        
        # Get CSRF token
        token_resp = self.session.get('https://en.wikipedia.org/w/api.php', params={
            'action': 'query',
            'meta': 'tokens',
            'format': 'json'
        }).json()
        self.csrf_token = token_resp['query']['tokens']['csrftoken']
    
    def edit(self, title, text, summary):
        """Save an edit to a page."""
        resp = self.session.post('https://en.wikipedia.org/w/api.php', data={
            'action': 'edit',
            'title': title,
            'text': text,
            'summary': summary,
            'token': self.csrf_token,
            'format': 'json',
            'assert': 'user',         # asserts we're logged in
            'maxlag': 5,               # respects server load
        })
        resp.raise_for_status()
        return resp.json()
    
    def get_wikitext(self, title):
        """Fetch the raw wikitext of a page."""
        resp = self.session.get('https://en.wikipedia.org/w/api.php', params={
            'action': 'parse',
            'page': title,
            'prop': 'text',
            'format': 'json',
        })
        resp.raise_for_status()
        return resp.json()['parse']['text']['*']
```

### 6.5 Rate Limiting

Wikipedia enforces rate limits per user. The tool must play nicely:

```python
import time

class RateLimiter:
    def __init__(self, min_interval=2.0):
        self.min_interval = min_interval  # seconds between edits
        self.last_edit = 0
    
    def wait(self):
        elapsed = time.time() - self.last_edit
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
    
    def report_done(self):
        self.last_edit = time.time()
```

- **2-second minimum gap** between saves (configurable via `--throttle`)
- **429 handling**: Respect `Retry-After` header, exponential backoff
- **`maxlag=5`**: Standard Wikipedia parameter telling the server to delay if replication lag exceeds 5 seconds

### 6.6 Re-authentication

Bot passwords do not expire by default, but the session cookies do. The tool detects a 401 or "not logged in" error during an edit attempt and automatically re-authenticates:

```python
def safe_edit(self, title, text, summary):
    try:
        return self.edit(title, text, summary)
    except PermissionError:
        # Session expired — re-login and retry
        self.login()
        return self.edit(title, text, summary)
```

If the bot password itself was revoked (permanent 401 after re-login), the tool exits with a message telling the user to create a new one.

---

## 7. Architecture

### 7.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         cwfix CLI Entry Point                        │
│                              main.py                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐     │
│  │  Auth Module   │  │  CheckWiki Client │  │  Article Cache      │     │
│  │  auth.py       │  │  checkwiki.py     │  │  cache.py           │     │
│  │                │  │                  │  │                    │     │
│  │  • keyring     │  │  • fetch error   │  │  • SQLite-based    │     │
│  │    integration │  │    list from CW   │  │  • stores article  │     │
│  │  • credential  │  │  • parse CW page │  │    list + metadata │     │
│  │    encryption  │  │  • extract URLs  │  │  • tracks progress │     │
│  │  • session mgmt│  │  • deduplicate   │  │  • resume support  │     │
│  └──────┬─────────┘  └────────┬─────────┘  └────────────────────┘     │
│         │                     │                                       │
│         ▼                     ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                      Core Engine                              │    │
│  │                      engine.py                                │    │
│  │                                                               │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐   │    │
│  │  │ WikiFetcher   │  │  Classifier  │  │  Fixer             │   │    │
│  │  │               │  │              │  │                    │   │    │
│  │  │ • get_wikitext│  │ • parse AST  │  │ • transform <b>→'''│   │    │
│  │  │ • get_rendered│  │ • classify   │  │ • nested bold-    │   │    │
│  │  │ • page info   │  │ • registry   │  │   italic handling │   │    │
│  │  │ • error       │  │   lookup     │  │ • diff generation │   │    │
│  │  │   handling    │  │              │  │ • batch operations │   │    │
│  │  └───────────────┘  └──────────────┘  └────────────────────┘   │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                      TUI Layer                                 │    │
│  │                      tui.py                                    │    │
│  │                                                               │    │
│  │  • interactive prompt loop   • color-coded rendering          │    │
│  │  • action dispatcher         • progress tracking              │    │
│  │  • context display           • badge rendering                │    │
│  │  • diff viewer               • list-all summary table         │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.2 Data Flow (per occurrence)

```
 1. FETCH ARTICLE LIST
    checkwiki.py ──→ https://checkwiki.toolforge.org/...&id=26
                    ←── HTML page with articles + snippets
    
 2. FOR EACH ARTICLE:
    a. FETCH WIKITEXT
       engine.py ──→ https://en.wikipedia.org/w/api.php?action=parse
                   ←── Raw wikitext string
    
    b. PARSE & CLASSIFY
       parser ──→ mwparserfromhell.parse(wikitext)
                ←── AST with all <b> tag nodes
       classifier ──→ classify(tag_node, parents, context)
                    ←── Classification enum
    
    c. PRESENT TO USER
       tui.py ──→ render(context, classification, old_text, new_text)
                ←── User presses [f] / [e] / [s] / etc.
    
    d. IF FIX:
       fixer.py ──→ old_text = str(wikitext)
                  → new_text = transform(wikitext, tag_node)
       auth.py ──→ session.edit(title, new_text, summary)
                 ←── {edit: {result: "Success", pageid: 12345, ...}}
    
    e. SAVE PROGRESS
       cache.py ──→ UPDATE progress SET status='fixed' WHERE article=...
```

### 7.3 File Layout

```
cwfix/
├── main.py                 # Entry point, CLI argument parsing
├── auth.py                 # Bot password authentication & session management
├── checkwiki.py            # CheckWiki page fetcher & parser
├── engine.py               # Core engine: fetch, classify, fix orchestrator
├── tui.py                  # Terminal UI with rich
├── classifier.py           # Classification logic & template registry
├── fixer.py                # Transform <b> → ''' with awareness
├── cache.py                # SQLite-based progress & article cache
├── rules/                  # User-extensible false-positive rules (JSON)
│   └── default.json        # Built-in known-risky template patterns
├── pyproject.toml          # Package metadata & dependencies
└── README.md               # Quick-start guide
```

### 7.4 Dependencies

```toml
# pyproject.toml
[project]
name = "cwfix"
version = "0.1.0"
description = "Interactive CheckWiki Error #26 fixer (HTML <b> → wiki ''')"
requires-python = ">=3.10"
dependencies = [
    "mwparserfromhell>=0.6",     # Wikitext AST parser
    "requests>=2.28",             # HTTP client
    "rich>=13.0",                 # Terminal UI
    "keyring>=24.0",              # OS keychain access
    "click>=8.0",                 # CLI argument parsing
]
```

---

## 8. Implementation Plan (v1.0)

### 8.1 What v1.0 Covers

| Feature | Ships in v1.0? | Notes |
|---------|---------------|-------|
| Fetch article list from CheckWiki | ✅ Yes | Scrape the CW page, extract titles + snippets |
| Parse wikitext with `mwparserfromhell` | ✅ Yes | Reliable AST-based tag detection |
| Classification engine (all 7 classes) | ✅ Yes | SS, BI, SN, TP, NC, NW, SP |
| Known template registry | ✅ Yes | SAFE_TEMPLATES + RISKY_TEMPLATES lookup |
| Interactive TUI with color | ✅ Yes | `rich`-based rendering |
| Core actions: `f`, `e`, `s`, `q`, `?` | ✅ Yes | Fix, Edit, Skip, Quit, Help |
| Batch actions: `a`, `F` | ✅ Yes | All identical, All safe |
| Investigative actions: `c`, `l`, `d` | ✅ Yes | Context+, List all, Diff |
| Meta actions: `!`, `u` | ✅ Yes | False positive flag, Undo last |
| `p` (Preview rendered) | ❌ No v1.0 | Requires Parsoid API — low value, postponable |
| Bot password authentication | ✅ Yes | Keyring integration, encrypted storage, rate limiting |
| Edit summary generation | ✅ Yes | `"Checkwiki error #26: fix HTML <b> → wiki bold markup"` |
| Dry-run mode | ✅ Yes | `--dry-run` flag |
| Resume from last position | ✅ Yes | SQLite progress cache |
| Batch non-interactive mode | ✅ Yes | `--batch-safe` |
| `--articles N` limit | ✅ Yes | For testing |

### 8.2 What's Explicitly Out of Scope for v1.0

- **Support for other CheckWiki error IDs** — v1.0 focuses exclusively on error #26. The architecture is modular; supporting other errors is a future concern.
- **Other Wikimedia wikis** (Commons, Wikidata, other languages) — v1.0 targets enwiki only. The CW tool already supports multiple wikis; the modular site config will make this easy to add.
- **Web GUI** — v1.0 is a CLI/TUI tool. A web version would be a separate project with different auth (OAuth 2.0) and hosting requirements.
- **Automatic bot mode** — v1.0 requires human judgment for non-SAFE classifications. A fully autonomous bot would need a much more sophisticated classification engine and is best done as a separate bot account (like WikiCleanerBot).
- **Multiple accounts** — v1.0 stores a single credential. Supporting credential switching is straightforward but not needed for launch.
- **Parsoid rendered preview** (action `p`) — Low user impact for the implementation cost. Postponed.

### 8.3 Milestones

| Milestone | Deliverable | Estimated effort |
|-----------|-------------|-----------------|
| **M1: Core pipeline** | Fetch CW list → parse wikitext → classify → suggest fix | 2-3 days |
| **M2: TUI** | Interactive prompt, color rendering, action dispatcher | 2-3 days |
| **M3: Authentication** | Bot password setup flow, keyring, session management, rate limiting | 1-2 days |
| **M4: Integration** | Wire everything together: fetch → classify → present → auth → save | 1 day |
| **M5: Batch & save** | `a`/`F` batch ops, progress cache, resume, `--dry-run` | 1 day |
| **M6: Polish** | Error handling, edge cases, documentation, packaging (`pip install`) | 1-2 days |
| **M7: Beta testing** | Fix 50-100 articles manually, gather feedback, iterate | 2-3 days |

**Total estimate**: 10-15 days for a working v1.0.

### 8.4 Test Plan

- **Unit tests** for classifier (20+ fixture cases including all patterns)
- **Unit tests** for fixer transformations (simple, bold-italic, nested)
- **Integration test** dry-run against 5 known articles (verify suggested fixes are correct)
- **Auth test**: login with a real bot password (test account), verify edit attribution
- **Edge cases**: articles with no `<b>` tags, articles with 100+ occurrences, very large articles (200KB+)

---

## 9. Future Enhancements (Beyond v1.0)

### 9.1 Short-term (next 3 months)

| Enhancement | Value | Complexity |
|-------------|-------|------------|
| **Support for error #38** (`<i>` → `''`) | Same classification engine, trivial to add another error ID | Low |
| **Support for error #4** (`<a>` → wiki links) | Same engine, slightly different fix logic | Low |
| **Customizable template registry via config file** | Users can add their own known templates | Low |
| **Multi-wiki support** (Commons, other Wikipedias) | Parameterize the wiki domain; CW tool already supports this | Low |
| **Session statistics** — "You fixed 142 `<b>` tags across 53 articles in this session" | Motivation and progress tracking | Low |
| **Edit summary customization** | Let user override the default summary per article or per session | Low |

### 9.2 Medium-term (3-12 months)

| Enhancement | Value | Complexity |
|-------------|-------|------------|
| **Rendered preview** (action `p` via Parsoid API) | See how the bold renders before committing | Medium |
| **`git`-style interactive staging** — review a batch of changes before committing | Safety net for batch operations | Medium |
| **Undo across sessions** — tracking changes via page history lookups | Revert a fix that was made in a previous session | Medium |
| **False positive sharing** — optionally upload false positive rules to a shared registry | Community curation of template knowledge | Medium |
| **CONFIGURABLE color scheme** ("light mode" / "dark mode" / custom) | Accessibility — some users need different contrast | Low |

### 9.3 Long-term (12+ months)

| Enhancement | Value | Complexity |
|-------------|-------|------------|
| **Autonomous bot mode** — after enough training data, automatically fix SAFE classifications without human review | Full automation for the 70% that are safe | High |
| **Machine learning classification** — train a model on human decisions to predict which `<b>` tags are safe | Smarter default suggestions, fewer risky auto-fix errors | High |
| **Web version on Toolforge** — OAuth 2.0, browser-based, shareable | Accessible to non-CLI users | High |
| **API** — expose the classification engine as a web service for other tools to consume | Ecosystem play — other tools could use the classifier | Medium |
| **Integration with WikiCleanerBot** — feed human-reviewed decisions back to improve the bot | Multiplicative effect — every human decision trains the automated system | High |

### 9.4 Architectural Notes for Future Extensibility

The classifier and fixer are designed to be **error-ID-agnostic**. The same engine that detects and fixes `<b>` tags can work for `<i>`, `<a>`, `<strike>`, `<font>`, and other HTML text style elements. Adding a new error type is a matter of:

1. Adding a new classification flag to the enum
2. Adding a new transformation function
3. Wiring it into the TUI with a different badge color

The template registry, false-positive rules, authentication, and progress caching are all shared infrastructure.

---

## 10. References

- **CheckWiki Error #26**: https://checkwiki.toolforge.org/checkwiki.cgi?project=enwiki&view=only&id=26
- **CheckWiki List of Errors**: https://en.wikipedia.org/wiki/Wikipedia:WikiProject_Check_Wikipedia/List_of_errors
- **WP:Deviations**: https://en.wikipedia.org/wiki/Wikipedia:Deviations
- **mwparserfromhell**: https://github.com/earwig/mwparserfromhell
- **Rich (TUI library)**: https://github.com/Textualize/rich
- **Bot Passwords**: https://en.wikipedia.org/wiki/Special:BotPasswords
- **User-Agent Policy**: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
- **Pywikibot Auth Docs**: https://doc.wikimedia.org/pywikibot/stable/authentication.html
x`
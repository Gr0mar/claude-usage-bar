# Claude Usage Bar

[![tests](https://github.com/Gr0mar/claude-usage-bar/actions/workflows/tests.yml/badge.svg)](https://github.com/Gr0mar/claude-usage-bar/actions/workflows/tests.yml)
[![licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
![macOS 13+](https://img.shields.io/badge/macOS-13%2B-lightgrey)

A macOS menu bar tracker for Claude Code: how much of your subscription window is left,
and what your usage would cost at API list prices. Click the spark for the full report.

![the dropdown](docs/dropdown.gif)

*(Rendered from synthetic data — `scripts/make-gif.py`. No real project names or spend.)*

## What it shows

| Section | What it answers |
|---|---|
| Session (5h) / Weekly | How much of the subscription quota is used, when it resets, and - once the burn rate is measurable - when it will run out |
| Running now | The session writing to a log right now: project, model, cost, burn rate per hour |
| Today / 7 days / 30 days | Cost and tokens for the window, with a 14-day daily-cost sparkline |
| Top projects | Which repos the spend went to |
| Models | Opus / Sonnet / Haiku split, and what prompt caching saved |

It also notifies you once the session window passes 80% and again at 95%, so the cap
does not arrive mid-thought. Turn that off in the menu.

The menu bar label shows the 5h quota by default; the menu switches it to the weekly
quota, today's cost, or the icon alone, and toggles the icon between monochrome and
Claude's coral.

Every dollar figure is the **API list price** of the tokens used, not a bill: on a
subscription you pay a flat fee, so read it as "what this usage would cost
pay-as-you-go".

## Requirements

- macOS 13 or later
- Python 3.9+ (the system `/usr/bin/python3` is fine; it needs the Xcode Command Line
  Tools, which `xcode-select --install` provides)
- Claude Code, with at least one session already logged

## Install

```bash
brew trust gr0mar/tap                              # third-party taps need this once
brew install --cask gr0mar/tap/claude-usage-bar
xattr -dr com.apple.quarantine /Applications/ClaudeUsageBar.app
open -a ClaudeUsageBar
```

Or grab the zip from [Releases](https://github.com/Gr0mar/claude-usage-bar/releases),
unzip it into `/Applications`, then right-click the app and choose **Open**.

That third line is the honest part: the app is **ad-hoc signed, not notarised**, so
Gatekeeper refuses to open it silently until the quarantine flag is cleared (the
right-click → Open dance does the same thing). Notarising needs a paid Apple Developer
account; if this project earns one, the step disappears.

The bundle carries its own copy of PyObjC and runs on the system `/usr/bin/python3` —
1.4 MB, nothing to install, no virtualenv.

**macOS will ask once for keychain access.** That is the OAuth token read described
below. Deny it and everything still works — the app falls back to the statusline file or
to a local token count.

"Launch at login" in the menu writes a LaunchAgent to `~/Library/LaunchAgents` — no
admin rights, no installer.

### From source

```bash
git clone https://github.com/Gr0mar/claude-usage-bar.git
cd claude-usage-bar
./scripts/setup.sh          # venv, tests, and a bundle in /Applications
```

`setup.sh` calls `install.sh`, which puts the runtime under
`~/Library/Application Support/ClaudeUsageBar`. That split from the checkout is
deliberate: an app launched from Finder cannot read `~/Desktop` or `~/Documents`, so a
bundle pointing back at a checkout there would die on startup.

## Where the numbers come from

**Spend** is read from the session logs Claude Code already writes to
`~/.claude/projects/**/*.jsonl`. Each assistant response carries a `usage` block; those
tokens are priced against a table of published per-million rates — list prices, which is
why the totals dwarf a subscription fee. A model with no published price still has its
tokens counted and is shown as `—` rather than guessed at. Nothing leaves your machine
to compute this.

**Quota windows** come from one of two places, whichever answers first:

1. `https://api.anthropic.com/api/oauth/usage`, called with the OAuth token Claude Code
   stores in your login keychain. The token is read for that single request; it is never
   written to disk or logged, the request refuses redirects so the header cannot be
   replayed to another host, and it goes to Anthropic and nowhere else.
2. `~/.claude/usage-bar/limits.json`, written by the bundled statusline hook. No
   credentials at all, but it only refreshes while a Claude Code session is running.

If neither answers, the header falls back to a local count of the tokens billed in the
last five hours and says so. The endpoint rate-limits, so it is polled every five
minutes and backs off to half-hourly after a failure; a reading older than five minutes
is shown with its timestamp rather than as current.

### Optional: the statusline hook

Claude Code pipes a JSON blob into your statusline command on every turn, and for
subscribers it contains the quota windows. `scripts/statusline-limits.sh` saves them and
then hands the untouched input to whatever statusline command you already use:

```json
"statusLine": {
  "type": "command",
  "command": "/path/to/claude-usage-bar/scripts/statusline-limits.sh 'your existing command'"
}
```

With no argument it prints a small `5h 42% · 7d 8%` line of its own.

## Accuracy

Claude Code writes one log line per content block, and every line of the same response
repeats the same message id and the same complete `usage` object — often seconds apart,
so a response routinely straddles two scans. The scanner therefore remembers every event
id it has already counted; without that, roughly a third of all responses would be
counted twice. The same set makes re-reading a file idempotent, so a `/rewind`, a
rotation, or a full rescan cannot inflate the totals.

## Projecting the cap

The reset time comes from the API - it is a fact, not a guess. The *arrival* time is
the guess: the API says how much of a window is used, never how fast, so the app
measures the slope itself from successive readings of the same window.

The span is measured to the present moment, not to the last reading, which is what
makes an idle machine stop predicting. A window only reports a new percentage when it
moves, so a burst of work followed by an hour of nothing would otherwise keep the last
steep rate on screen forever; measured against the clock, that same burst dilutes from
30%/h to 10%/h over the following hour and eventually falls under the floor, taking the
prediction with it.

A line appears only when the readings span at least eight minutes, the window is
actually moving, and the rate would empty it *before* it resets - otherwise there is
nothing to warn about.

## Performance

The first launch parses every log once and caches the day-level rollup in
`~/Library/Caches/com.github.gr0mar.ClaudeUsageBar`. After that each pass reads only the bytes
a log has grown by, tracked per file, and a half-written trailing line is left for the
next pass rather than dropped. Idle cost is one `stat` per log every five seconds; the
directory tree itself is re-walked at most once a minute.

## Uninstall

```bash
rm -rf /Applications/ClaudeUsageBar.app
rm -rf ~/Library/Application\ Support/ClaudeUsageBar
rm -rf ~/Library/Caches/com.github.gr0mar.ClaudeUsageBar
launchctl bootout gui/$(id -u)/com.github.gr0mar.ClaudeUsageBar 2>/dev/null
rm -f ~/Library/LaunchAgents/com.github.gr0mar.ClaudeUsageBar.plist
defaults delete com.github.gr0mar.ClaudeUsageBar 2>/dev/null
rm -rf ~/.claude/usage-bar
```

## Development

```bash
.venv/bin/python -m unittest discover -s tests   # no network, no display, no keychain
.venv/bin/python scripts/preview.py /tmp 7       # renders the dropdown to PNGs
.venv/bin/python scripts/preview.py docs 7 --demo  # the README screenshot, synthetic data
./scripts/run.sh                                 # foreground, prints tracebacks
.venv/bin/python scripts/make-icon.py docs/AppIcon.icns  # rebuild the app icon
.venv/bin/python scripts/make-gif.py docs/dropdown.gif   # rebuild the README animation
./scripts/build-release.sh 1.0.0                 # self-contained bundle + release zip
```

The app's identity - bundle id, cache directory, LaunchAgent label - lives in
`claude_usage_bar/identity.py`, and the install script reads it from there.

`claude_usage_bar/` splits into pure logic (`parser`, `pricing`, `aggregate`, `scanner`,
`live`, `limits`, `formatting`, `store`) and the AppKit layer (`ui/`). Only `ui/` imports
AppKit; everything else is testable without a display. The store owns one background
thread that publishes an immutable snapshot, and the UI reads that snapshot once per
layout pass — so a repaint can never mix values from two different scans.

PRs welcome; run the tests before opening one.

## Licence

MIT — see [LICENSE](LICENSE).

Not affiliated with Anthropic. "Claude" and the Claude mark are Anthropic's; the mark
in `claude_usage_bar/assets/claude-mark.svg` comes from
[simple-icons](https://github.com/simple-icons/simple-icons) (CC0 icon set, trademarks
remain their owners') and is used here to identify what the app reports on.

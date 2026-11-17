# rhtop

A minimal, **read-only** Robinhood MCP terminal dashboard.
Free of charge, with no paid rhtop features.

```text
┌─ Overview ────┐ ┌─ Positions ─────────────────┐ ┌─ Assets & Watchlists─┐
│               │ │ Symbol  Asset   Qty  Value  │ │ Crypto ▾             │
│ Account   *** │ │ AAPL    equity  ***  ***    │ │ Search / filter      │
│ Portfolio *** │ │ BTC     crypto  ***  ***    │ │ BTC-USD · Bitcoin    │
│ Cash      *** │ └─────────────────────────────┘ │ ETH-USD · Ethereum   │
│ Buying power  │ ┌─ Orders ────────────────────┐ │ DEMO-USD … 🚫 ALL    │
│           *** │ │ Symbol  Side  State   Qty   │ │                      │
│               │ │ AAPL    buy   queued  ***   │ │ Recent selections    │
└───────────────┘ └─────────────────────────────┘ └──────────────────────┘
q Quit   m Mask   r Refresh   p Pause   a Account   / Filter   l Layout   ? Help
```

## Run on Unix

Python **3.11+** and an interactive terminal are required. Start with the offline
demo; it never authenticates or contacts Robinhood.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run.sh --demo
```

For a standalone install from this checkout, use `pipx install .`, or install into
your own virtual environment with `python -m pip install .`. This installs the
`rhtop` command. It runs independently and does not require an MCP plugin inside another
application.

Homebrew, Chocolatey, apt, and npm have explicit placeholders under
[packaging](packaging/README.md); those installers and public registry releases
are not implemented yet. Unix Python installation is the supported path today.

## Connect your own MCP account

```sh
./run.sh login       # optional: authorize before launching the dashboard
./run.sh             # connect and show live account data
# Or, after installing the package:
rhtop
```

Authorize your own Robinhood MCP connection. The sole active **MCP / Agentic**
account is selected automatically. Use `a` to explicitly choose among the active
accounts the connection can read; all accounts are display-only in rhtop. If the
MCP default is ambiguous or missing, rhtop asks for a selection rather than
silently falling back. Explicit selection is encrypted and restored on restart.

**Headless OAuth is always enforced.** rhtop shows an authorization URL and binds
its callback to `127.0.0.1`; it never launches a browser. Open the URL manually on
the same machine, authorize, and return to the terminal. `--headless` is accepted
for clarity; no browser-enabled mode exists. The default callback port is 8766;
use `--oauth-port PORT` consistently if you need a different port. No SSH, remote
forwarding, or remote-machine setup is required or provided.

In the authorization dialog, click **Copy URL** or press **Ctrl+y** to copy the
entire URL; selection is not required. Terminal clipboard support varies. If
pasting fails, click **Show in terminal** or press **Ctrl+t** to temporarily leave
the dashboard and copy the plain URL with your terminal's normal controls.
Press Enter to return; the OAuth callback continues listening while you copy.
Alternatively, run `rhtop login` (`./run.sh login` from the checkout) to authorize
entirely from ordinary terminal output. No browser is launched by these actions.

On a desktop with a secure native keyring, the vault encryption key lives there.
On headless Linux without a usable keyring, enter a vault passphrase of at least
12 characters before the UI starts. For unattended startup, supply
`RHTOP_PASSPHRASE` through your secret manager. rhtop does not load `.env` files or
accept broker passwords or access tokens as command-line arguments.

## Dashboard controls

| Key | Action |
| --- | --- |
| `Tab` / `Shift+Tab` | Move focus between panels and controls |
| Arrows / `j`, `k` | Navigate table rows (arrows also work in asset lists) |
| `Enter` | Inspect a row or select an asset; no trading actions |
| `m` / `Ctrl+h` | Toggle `***` for personal financial values and identifiers |
| `/` / `Esc` | Filter account tables / clear filter or close a dialog |
| `s` / `S` | Cycle sort column / reverse sort direction |
| Click table header | Sort that column |
| `a` | Select an active account (MCP / Agentic is the initial default) |
| `r` | Refresh / retry a failed connection |
| `p` | Pause / resume automatic account polling and crypto catalog refresh |
| `1`, `2`, `3`, `4`, `5` | Toggle Overview, Positions, Orders, Assets, Watchlists panels |
| `l` | Cycle classic, mirrored, and stacked layouts |
| `?` | Show keyboard help |
| `q` / `Ctrl+c` / `Ctrl+q` | Quit (`Ctrl+c` and `Ctrl+q` also work inside inputs and dialogs) |

Text inputs consume normal character keys while you type. Use Tab to leave an
input before using the single-character dashboard shortcuts. `Ctrl+h` toggles
privacy while an input has focus. At least one panel stays visible.
Click the `ACCOUNT` label in Overview to open the same account selector as `a`.
Click the green Account ID value to copy the full ID to the clipboard, including
when it is displayed as `***`; copying leaves the privacy toggle unchanged.

Privacy starts **on at every launch**; revealing values is session-only. Masking
covers balances, account numbers, quantities, cost basis, position value/P&L,
order prices and IDs, and IDs in asset detail dialogs. Public market symbols,
option contract descriptions (including strikes), names, sides, order states,
timestamps, row counts, and saved asset titles remain visible. This is a display
privacy control, not an anonymization mode.

The classic layout puts the Overview column on the left, positions/orders in the
middle, and assets on the right. Press `l` once for the second layout: Overview
above Assets in a shared right-hand column, with Positions above Orders on the
left. Press `l` again for the existing stacked layout, and again to return to
classic. The saved layout names remain `classic`, `mirrored`, and `stacked`.
Narrow terminals adapt the layout and allow scrolling. A terminal of at least
140×32 is recommended for the full five-panel view. Watchlists appears to the
right of Assets on wide terminals and below the other panels on narrow ones.
Press `5` to toggle it. Choose a watchlist to read its symbols and asset types;
`r` refreshes it along with the dashboard. Custom and followed curated lists are
supported. Options lists show single-leg contracts through the dedicated MCP
options watchlist reader. Watchlists cannot be edited in rhtop.

The dashboard uses compact, single-line controls and flush panel borders, with
no blank outer rows around the header or footer. Connection status is on the
right of the header; hover it for the last successful update time and full notices.
A live clock with the machine's local timezone sits at the far right and continues
ticking while account polling is paused or disconnected.
On Unix, it requests the
standard arrow pointer throughout the UI and restores the prior pointer when
exiting or temporarily showing the authorization URL in the normal terminal.
This uses the [Kitty pointer-shape protocol](https://sw.kovidgoyal.net/kitty/pointer-shapes/);
unsupported terminals retain their own pointer behavior. Terminals may also
override the shape during native text selection or when hovering over links.

## Asset browser

The right-hand picker **defaults to Crypto on every launch**. Change the category
with the dropdown (keyboard: focus it, Enter, arrows, Enter).
Asset results and recents stay on one line, with ellipses for overflow; select a
row to inspect its full details.

* **Crypto:** all supported pairs returned by `get_currency_pairs`, following
  every catalog page. Halted pairs are retained and their titles end in
  `🚫` followed by space-separated regions, such as `🚫 NY TX` (`🚫 ALL` for a
  global halt, or just `🚫` when regions are unavailable). A regional halt can be one-sided.
  Enter a name or symbol in the search field to filter the catalog. The catalog
  refreshes alongside automatic polling and on `r`.
* **Equities:** enter a company name or ticker and press Enter. Select a result
  to inspect it and save it to recent selections.
* **Options:** search a company or ticker, select an underlying, then select a
  contract to inspect and save it. To narrow a large chain, search directly using
  `AAPL 2026-12-18 call 250` (expiry, right, and strike are optional). Contract
  browsing is limited to 500 results per lookup and explicitly reports when
  truncated; narrow the query to see the relevant contracts.

The most recent **30 equities and 30 option contracts** are deduplicated and
restored on restart. Recent entries are saved metadata, not fresh quotes; search
again to refresh a contract's status. Live recents are encrypted in the same
vault as the saved account selection. Offline demo recents use a separate private
`demo-recents.json` file, and never write to the live credential vault. Asset
selection performs no Robinhood watchlist write and no trade.

## Settings and data

`rhtop paths` prints the local paths. On Linux the defaults are
`~/.config/rhtop/settings.json` and `~/.local/share/rhtop/` for the vault.
The standard XDG directory variables are respected.

Non-secret settings (layout, panels, poll interval, sort direction) are saved
atomically in a file with mode `0600`; new app directories use `0700`. Polling
defaults to 30 seconds, configurable with `rhtop --poll-seconds 60` (10–3600).
Credentials, selected account, and live asset recents are encrypted with Fernet;
passphrase fallback keys are derived with scrypt and a random salt. The vault is
dedicated to rhtop; credentials from other applications are not read or migrated.
No account snapshots, response bodies, or portfolio history are written to disk.

`rhtop auth-reset` removes the local vault for the selected callback port,
including its saved account and asset recents. It does not revoke Robinhood-side
authorization. Use Robinhood's connection controls for revocation.

Unknown values show `—`, never fabricated zeroes. Values and P&L are displayed
only when supplied by the broker; rhtop does not synthesize live prices. Optional
sections that fail are reported in the status bar. Paginated account positions
or orders are marked **partial (first page)**. A failed core refresh keeps the
last successful snapshot with a **STALE** notice; retries back off to 60 seconds.
Crypto catalogs are never silently presented as complete after truncation or a
pagination failure.

## Development and CI

```sh
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/python -m pytest -q
.venv/bin/python -m build --no-isolation
```

Tests use synthetic data and the official SDK's in-process transport. The OAuth
callback test binds a temporary loopback port; no live account is used. Textual
tests exercise keyboard flows, privacy, layouts, asset browsing, and persistence.
Live authentication must be verified manually with your own account.

The commands above run offline checks and build the Python package. Tests use
synthetic data; live authentication must be verified manually with your own
account.

## Architecture and license

`broker/` contains the MCP transport, schema validation, response
parsing, catalog traversal, and read-only view models. `ui/` contains reusable
panels, overlays, privacy formatting, and layout logic. `assets.py` owns recent
selection persistence; `auth.py` owns encrypted storage and loopback OAuth.

An exact allowlist permits dashboard reads and asset search/catalog reads only.
Server-discovered placement, cancellation, review/preview, watchlist mutation,
and other tools are never exposed through the client. No execution engine,
trading strategy, order builder, or trading UI is included.

rhtop is published under the [PolyForm Noncommercial 1.0.0 license](LICENSE).
See [NOTICE](NOTICE) for copyright and licensing information.
This license allows public redistribution and permitted noncommercial use free
of charge, and restricts commercial use. It is not a permissive MIT/Apache
license.
This project is independent of and not endorsed by Robinhood.

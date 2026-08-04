# USPTO Portfolio Automation (Operator Helpers)

Automates **public ODP review** and **authorized private import**. It does **not**
sign, pay, file, store Patent Center passwords, or bypass MFA.

## Components

| Piece | Path |
| --- | --- |
| Library | `ipfs_datasets_py/processors/domains/uspto/portfolio_automation.py` |
| CLI | `scripts/ops/uspto/portfolio_cli.py` |
| Attended browser export | `scripts/ops/uspto/attended_patent_center_export.py` |
| Local state (default) | `~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/` |
| ODP key env file | `~/.config/ipfs_datasets_py/uspto.env` |

## Setup

```bash
source ~/.config/ipfs_datasets_py/uspto.env   # exports USPTO_ODP_API_KEY
cd /path/to/ipfs_datasets_py
export PYTHONPATH=.
```

## Public automation

```bash
# Discover candidate apps by inventor display name (ownership unconfirmed)
python3 scripts/ops/uspto/portfolio_cli.py discover \
  --inventor-name "Benjamin Barber"

# Confirm which apps are yours
python3 scripts/ops/uspto/portfolio_cli.py confirm \
  --application-number 18654466

# Or replace the seed with only your apps
python3 scripts/ops/uspto/portfolio_cli.py keep-only \
  --application-number 18654466 --application-number 12252942

# Drop false same-name hits
python3 scripts/ops/uspto/portfolio_cli.py drop --application-number 18844946

# Refresh public ODP status for the whole seed
python3 scripts/ops/uspto/portfolio_cli.py refresh

# Also sync public document inventory/bytes for *confirmed* matters
python3 scripts/ops/uspto/portfolio_cli.py refresh --with-documents

# Inspect seed
python3 scripts/ops/uspto/portfolio_cli.py show
```

Public document bytes land under
`~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/public_docs/`.

## Scheduled public refresh

```bash
# Write systemd user timer templates (every 24h) and enable them
python3 scripts/ops/uspto/portfolio_cli.py schedule install \
  --interval-hours 24 --activate

# Include public document sync for confirmed matters on the schedule
python3 scripts/ops/uspto/portfolio_cli.py schedule install \
  --interval-hours 24 --with-documents --activate

python3 scripts/ops/uspto/portfolio_cli.py schedule status
python3 scripts/ops/uspto/portfolio_cli.py schedule tick   # run once now
```

The timer only runs public ODP refresh (status and optional public documents).
It never opens Patent Center, signs, pays, files, or pushes git.

## Private import (no browser)

1. Log into Patent Center yourself and download documents for a matter.
2. Put files in a folder.
3. Seal + import:

```bash
python3 scripts/ops/uspto/portfolio_cli.py prepare-import \
  --export-dir ~/exports/18654466 \
  --application-number 18654466

python3 scripts/ops/uspto/portfolio_cli.py import-folder \
  --export-dir ~/exports/18654466 \
  --application-number 18654466 \
  --authorizing-user "operator:you"
```

## Patent Center login CLI / MCP (password + OTP)

Prefer **credential references** over typing secrets on the command line:

```bash
# ~/.config/ipfs_datasets_py/uspto.env (mode 600) may also hold:
#   export USPTO_USERNAME='you@example.com'
#   export USPTO_PASSWORD='...'
#   export USPTO_TOTP_SECRET='BASE32SEED'   # optional authenticator

source ~/.config/ipfs_datasets_py/uspto.env

# Login (headed browser by default via portfolio_cli → uspto_login_cli)
python3 scripts/ops/uspto/portfolio_cli.py login --otp-mode totp
# or interactive OTP:
python3 scripts/ops/uspto/portfolio_cli.py login --otp-mode prompt
# or one-shot code (not stored):
python3 scripts/ops/uspto/portfolio_cli.py login --otp-mode code --otp-code 123456

python3 scripts/ops/uspto/portfolio_cli.py login-status
python3 scripts/ops/uspto/portfolio_cli.py logout
```

Direct CLI:

```bash
python3 scripts/ops/uspto/uspto_login_cli.py login \
  --username-ref env:USPTO_USERNAME \
  --password-ref env:USPTO_PASSWORD \
  --otp-mode totp \
  --totp-secret-ref env:USPTO_TOTP_SECRET
```

MCP operator tools (separate from read-only USPTO MCP surface):

| Tool | Purpose |
| --- | --- |
| `uspto_operator_login` | Login with refs; saves local session |
| `uspto_operator_session_status` | Session present? |
| `uspto_operator_logout` | Delete local session |

Responses never include passwords, OTP seeds, or raw cookies.

Session file (mode 0600):

`~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/sessions/patent_center.storage_state.json`

## Patent Center UI export (saved session; automated)

After `portfolio_cli login`, `export-ui` drives Patent Center headless:

1. Completes Patent Center SSO (`userLoggedIn`)
2. Reads SPA tokens from `sessionStorage` (not written to disk receipts)
3. Fetches private metadata (bib data, addresses, fees, eGrant, IFW inventory)
4. Clicks eGrant Download PDF / XML controls
5. Optionally downloads IFW PDFs via public ODP (`USPTO_ODP_API_KEY`) using
   document identifiers from the Patent Center IFW inventory
6. Seals `package/` with `export_manifest.json` + `authorization.json`

```bash
source ~/.config/ipfs_datasets_py/uspto.env
export PYTHONPATH=.

python3 scripts/ops/uspto/portfolio_cli.py login --otp-mode totp
python3 scripts/ops/uspto/portfolio_cli.py export-ui \
  --application-number 18654466 \
  --authorizing-user "operator:you"

# Metadata + eGrant only (skip ODP IFW PDFs)
python3 scripts/ops/uspto/portfolio_cli.py export-ui \
  --application-number 18654466 --no-odp-ifw

# Import sealed package
python3 scripts/ops/uspto/portfolio_cli.py import-folder \
  --export-dir ~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/exports/18654466/patent_center_ui/package \
  --application-number 18654466
```

Artifacts land under:

`~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/exports/<app>/patent_center_ui/`

## Browser export (attended; uses saved session when available)

Uses the saved login session from `portfolio_cli login` when present; otherwise
opens a headed browser for interactive login. After auth it may navigate and
attempt download clicks; if the UI does not cooperate, download manually into
the export directory (or `private_inbox/<app>/`), then seal/import.

Prefer **`export-ui`** for unattended headless runs with a saved session.
Use **`attended-export`** when you need a human in the loop (watch-folder,
training env, or stubborn UI).

```bash
# Prefer: login first (refs/TOTP), then automated UI export
python3 scripts/ops/uspto/portfolio_cli.py login --otp-mode totp
python3 scripts/ops/uspto/portfolio_cli.py export-ui \
  --application-number 18654466 \
  --authorizing-user "operator:you"

# Attended / watch-folder fallback
python3 scripts/ops/uspto/portfolio_cli.py attended-export \
  --application-number 18654466 \
  --authorizing-user "operator:you"

# After files are present:
python3 scripts/ops/uspto/portfolio_cli.py attended-export \
  --application-number 18654466 \
  --export-dir ~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/exports/18654466 \
  --seal-only

python3 scripts/ops/uspto/portfolio_cli.py import-folder \
  --export-dir ~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/exports/18654466 \
  --application-number 18654466
```

Optional persistent profile (session cookies on disk, never commit):

```bash
python3 scripts/ops/uspto/portfolio_cli.py attended-export \
  --application-number 18654466 \
  --user-data-dir ~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/browser-profile
```

## Dashboard and private inbox auto-import

```bash
# Full operator dashboard (seed, public docs, exports, inbox, schedule)
python3 scripts/ops/uspto/portfolio_cli.py dashboard

# After Patent Center downloads (manual or attended-export), drop files here:
#   ~/.local/state/.../private_inbox/<application_number>/
# Optionally add a READY marker file when the download batch is complete.

python3 scripts/ops/uspto/portfolio_cli.py inbox-import \
  --authorizing-user "operator:$USER"

# Or poll for 5 minutes and auto-import settled folders
python3 scripts/ops/uspto/portfolio_cli.py watch-inbox \
  --duration-seconds 300 --authorizing-user "operator:$USER"
```

Without a `READY` file, a folder imports only after its newest file is stable
for `--min-stable-seconds` (default 15) so in-progress downloads are not sealed
early.

## Revise a submission (deficiency letter / office action)

When USPTO mails a deficiency notice, missing-parts letter, non-compliant
amendment notice, or office action, use the **revise** workflow. It never
auto-files; it tracks the letter, builds a response package, and reuses
filing-assist hard barriers.

```bash
# 1) Refresh IFW inventory (if needed)
python3 scripts/ops/uspto/portfolio_cli.py export-ui --application-number 18654466

# 2) Scan local IFW metadata for letters that likely need a reply
python3 scripts/ops/uspto/portfolio_cli.py revise scan \
  --application-number 18654466

# 3) Open a revision case for a specific letter
python3 scripts/ops/uspto/portfolio_cli.py revise open \
  --application-number 18654466 \
  --document-code CTNF \
  --document-id OA123 \
  --document-description "Non-Final Rejection" \
  --official-date 2024-05-03

# 4) Attach human-authored revised documents
python3 scripts/ops/uspto/portfolio_cli.py revise attach \
  --revision-id rev-18654466-… \
  --file ~/drafts/amended_claims.pdf \
  --role amended_claims

python3 scripts/ops/uspto/portfolio_cli.py revise attach \
  --revision-id rev-18654466-… \
  --file ~/drafts/remarks.docx \
  --role remarks

# 5) Prepare package digest + filing checklist
python3 scripts/ops/uspto/portfolio_cli.py revise prepare \
  --revision-id rev-18654466-…

# 6) Attended Patent Center assist (YOU still Sign / Pay / Submit)
python3 scripts/ops/uspto/portfolio_cli.py revise filing-assist \
  --revision-id rev-18654466-… \
  --watch-seconds 600

# 7) After you file: record human assertion + import EAR
python3 scripts/ops/uspto/portfolio_cli.py revise mark-submitted \
  --revision-id rev-18654466-… \
  --authorizing-user "operator:you"

python3 scripts/ops/uspto/portfolio_cli.py revise close \
  --revision-id rev-18654466-…
```

Cases live under:

`~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/revisions/`

Reply-date fields are **review-only candidates** (calendar-month stub + weekend
adjustment). Always confirm the period on the face of the USPTO letter.

Attachment roles: `amended_claims`, `amended_specification`,
`substitute_specification`, `amended_drawings`, `remarks`,
`amendment_transmittal`, `ids`, `declaration`, `fee_transmittal`, `evidence`,
`other`, `triggering_letter`.

## Filing assist (human Sign / Pay / Submit)

Automation **never** signs, pays, or performs final submission. It *does*
prepare a checklist, open Patent Center for view-only navigation, watch a local
folder for receipts **you** download after Submit, and import those receipts.

```bash
# 1) Content-free checklist + receipt drop folder
python3 scripts/ops/uspto/portfolio_cli.py filing-checklist \
  --application-number 18654466 \
  --package-dir ~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/exports/18654466/patent_center_ui/package \
  --metadata-dir ~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/exports/18654466/patent_center_ui/metadata

# 2) Attended assist (saved session; hard barrier banner; no Sign/Pay/Submit clicks)
python3 scripts/ops/uspto/portfolio_cli.py filing-assist \
  --application-number 18654466 \
  --package-dir ~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/exports/18654466/patent_center_ui/package \
  --navigate application \
  --watch-seconds 600

# Checklist-only (no browser)
python3 scripts/ops/uspto/portfolio_cli.py filing-assist \
  --application-number 18654466 --no-browser

# 3) After YOU Submit: drop EAR + payment PDFs into
#    ~/.local/state/.../post_submit_receipts/<app>/
# then seal+import:
python3 scripts/ops/uspto/portfolio_cli.py watch-receipts \
  --application-number 18654466 \
  --authorizing-user "operator:you"
```

Hard-barrier controls (never auto-clicked): Sign, Certify / 11.18, Pay / Payment,
Submit, checkout, charge, credit card, etc.

Payment prep is **labels only** (e.g. fees-due indicators from prior export
metadata). No card numbers or deposit-account secrets are stored.

For the formal handoff state machine (package digest → human assertion →
receipt-verified), see `PATENT_CENTER_HUMAN_HANDOFF.md`.

## Hard rules

**Allowed:** public ODP discovery/sync; build manifest from local files; import
authorized exports; attended browser with human login; filing checklist;
view-only Patent Center navigation; post-submit receipt watch/import.

**Forbidden:** unattended Patent Center scrape; storing passwords/MFA; typing
credentials from env; **sign / pay / final submission automation**; committing
exports or browser profiles.

## Policy

See `data/agent_supervisor/patent_legal_intelligence/bundles/private_boundary_policy.json`.

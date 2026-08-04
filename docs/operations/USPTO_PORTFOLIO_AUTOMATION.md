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

## Attended browser export (human login)

Opens a **headed** Chromium window. **You** complete USPTO login and MFA.
The helper never types passwords. It may navigate to application numbers and
attempt download clicks; if the UI does not cooperate, download manually into
the export directory, then seal.

```bash
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

## Hard rules

**Allowed:** public ODP discovery/sync; build manifest from local files; import
authorized exports; attended browser with human login.

**Forbidden:** unattended Patent Center scrape; storing passwords/MFA; typing
credentials from env; sign / pay / final submission; committing exports or
browser profiles.

## Policy

See `data/agent_supervisor/patent_legal_intelligence/bundles/private_boundary_policy.json`.

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

## Submission compliance audit (MPEP / CFR + prior art)

Audit a response package (or revision case) against:

1. **Filing-obligation rule packs** — baseline utility/OA rules cite 37 C.F.R.
   (e.g. §§ 1.111, 1.121) and related surfaces; required evidence kinds are
   compared to package files/attachment roles.
2. **Prior-art coverage** — latest (or selected) `prior-art search` run:
   report/journal presence, foreign/NPL gaps, PPS verification, human
   coverage acknowledgment, claim-chart density.
3. **Authority surface** — local `authority_corpus/` excerpts for cited
   MPEP/CFR tokens; optional HF hybrid index (`--with-law-index`).

Review only — **not** a completeness certification or legal advice. Never
Sign / Pay / Submit.

```bash
# After preparing a revision package + prior-art search:
python3 scripts/ops/uspto/portfolio_cli.py audit-submission \
  --application-number 18654466 \
  --revision-id rev-18654466-… \
  --package-dir ~/.local/state/.../revisions/cases/18654466/rev-…/response_package

# Or via revise:
python3 scripts/ops/uspto/portfolio_cli.py revise audit \
  --revision-id rev-18654466-…

# Bind a specific prior-art run + query public legal index:
python3 scripts/ops/uspto/portfolio_cli.py audit-submission \
  --application-number 18654466 \
  --package-dir ~/drafts/response_package \
  --prior-art-run-id run-… \
  --with-law-index
```

Artifacts: `state-root/compliance_audits/<app>/audit_…/submission_compliance_audit.json`

Also produced on audit:

* **`action_plan`** — ordered CLI next steps (attach missing evidence, foreign/NPL
  search, PPS, acknowledge, re-audit, filing-assist)
* **`ids_review_queue.json`** — human IDS candidates from prior-art hits
  (`auto_file_blocked`; never auto-files under 37 C.F.R. § 1.56)

```bash
# IDS candidates only (from an existing prior-art run)
python3 scripts/ops/uspto/portfolio_cli.py prior-art ids-queue \
  --application-number 18654466 --run-id run-…

# Human IDS review (natural person records judgment — never auto-files)
python3 scripts/ops/uspto/portfolio_cli.py prior-art ids-list \
  --application-number 18654466
python3 scripts/ops/uspto/portfolio_cli.py prior-art ids-review \
  --application-number 18654466 \
  --candidate-id ids-cand:… \
  --relevance relevant --materiality material --promote \
  --acknowledger "operator:you"
python3 scripts/ops/uspto/portfolio_cli.py prior-art ids-export \
  --application-number 18654466

# List / show audits + markdown report
python3 scripts/ops/uspto/portfolio_cli.py audit-submission --list \
  --application-number 18654466
python3 scripts/ops/uspto/portfolio_cli.py audit-submission --show \
  --application-number 18654466

# prepare auto-runs audit + IDS queue (skip with --no-audit / --no-ids-queue)
python3 scripts/ops/uspto/portfolio_cli.py revise prepare --revision-id rev-…
```

Libraries:

* `ipfs_datasets_py/processors/domains/uspto/submission_compliance_audit.py`
* `ipfs_datasets_py/processors/domains/uspto/ids_review_operator.py`

## Prior-art search (claim distinguishability)

Use **prior-art** to build a reproducible search plan from claim text, run
public U.S. search (local snapshot and/or ODP Patent File Wrapper), and emit a
content-addressed journal, coverage declaration, and source-linked claim chart
for **human distinguishability drafting**.

### Public patent search sources (what works)

| Source | Automated? | How |
| --- | --- | --- |
| **USPTO Open Data Portal (ODP)** Patent File Wrapper search | **Yes** | `prior-art search --odp` with `USPTO_ODP_API_KEY` (uses nested `pagination`; free-text `q` with keyword AND) |
| **EPO OPS** (foreign EP/WO/…) | **Yes** | `prior-art search --live-foreign` with `EPO_OPS_KEY`/`EPO_OPS_SECRET` |
| **OpenAlex / Crossref** (NPL metadata) | **Yes** | `prior-art search --live-npl` |
| **Local snapshot** of patents you supply | **Yes** | `--local-snapshot` / `--foreign-hits` |
| **Patent Public Search (PPS)** | **Human only** | `prior-art pps-assist` opens the site; you run queries |
| **Google Patents** | **Human only** | No official search API. Hit summaries include `human_review_urls.google_patents` deep links for browser review — we do **not** scrape Google |
| **Legacy PatentsView** `api.patentsview.org` | **No (retired)** | Migrated into USPTO ODP (2026); use `--odp` instead |

USPTO public search for prior art in this tooling is **ODP**, not Google Patents
and not interactive PPS automation.

Hard rules:

* Never asserts novelty, obviousness, or patentability.
* Foreign-patent and NPL corpora stay **visible unsearched gaps** unless a
  licensed named adapter is registered and actually runs (none ship by default).
* Does not scrape Patent Center, sign, pay, or file.
* Interactive Patent Public Search verification remains a human step.

```bash
# Claims file (JSON)
# { "claims": [ {"claim_number": 1, "claim_text": "A method comprising…"} ] }
# Filing/priority dates default from export application_data when present.

# Plan only (limitation candidates + queries + foreign/NPL gaps)
python3 scripts/ops/uspto/portfolio_cli.py prior-art plan \
  --application-number 18654466 \
  --claims-file ~/drafts/claims.json \
  --classifications G06F16/00

# Search via local public-patent snapshot (offline / deterministic)
python3 scripts/ops/uspto/portfolio_cli.py prior-art search \
  --application-number 18654466 \
  --claims-file ~/drafts/claims.json \
  --local-snapshot ~/snapshots/us_public_patents.json \
  --max-queries 8

# Search via live ODP (needs USPTO_ODP_API_KEY)
python3 scripts/ops/uspto/portfolio_cli.py prior-art search \
  --application-number 18654466 \
  --claims-file ~/drafts/claims.json \
  --odp --max-queries 6 --rank-cutoff 10

# Full coverage: US + foreign hits file + licensed NPL catalog + graphs
python3 scripts/ops/uspto/portfolio_cli.py prior-art search \
  --application-number 18654466 \
  --claims-file ~/drafts/claims.json \
  --local-snapshot ~/snapshots/us_public_patents.json \
  --foreign-hits ~/snapshots/foreign_hits.json \
  --npl-catalog ~/snapshots/npl_catalog.json --npl-licensed \
  --citation-graph ~/snapshots/citations.json \
  --family-graph ~/snapshots/family.json \
  --citation-seeds US10123456B2 \
  --max-queries 20

# Live foreign (EPO OPS) + live public NPL metadata (OpenAlex/Crossref)
# Register EPO app at https://developers.epo.org/ → EPO_OPS_KEY + EPO_OPS_SECRET
# Optional: OPENALEX_API_KEY, CROSSREF_MAILTO
python3 scripts/ops/uspto/portfolio_cli.py prior-art search \
  --application-number 18654466 \
  --claims-file ~/drafts/claims.json \
  --odp --live-foreign --live-npl \
  --max-queries 8 --max-live-results 10

# List / show runs
python3 scripts/ops/uspto/portfolio_cli.py prior-art list \
  --application-number 18654466
python3 scripts/ops/uspto/portfolio_cli.py prior-art show \
  --application-number 18654466 --run-id run-…

# Patent Public Search human verification (never scraped/automated)
python3 scripts/ops/uspto/portfolio_cli.py prior-art pps-checklist \
  --application-number 18654466 --run-id run-…
# Attended assist: open PPS landing page + print pending queries (YOU search)
python3 scripts/ops/uspto/portfolio_cli.py prior-art pps-assist \
  --application-number 18654466 --run-id run-… \
  --watch-seconds 300
# Or checklist only:
python3 scripts/ops/uspto/portfolio_cli.py prior-art pps-assist \
  --application-number 18654466 --run-id run-… --no-browser
# After interactive PPS, record counts:
python3 scripts/ops/uspto/portfolio_cli.py prior-art pps-record \
  --application-number 18654466 --run-id run-… \
  --query-id q-kw-1 --human-result-count 12 \
  --acknowledger "operator:you" --note "spot-checked top hits"
python3 scripts/ops/uspto/portfolio_cli.py prior-art pps-show \
  --application-number 18654466 --run-id run-…

# Lexical distinguishability matrix (overlap candidates — not patentability)
python3 scripts/ops/uspto/portfolio_cli.py prior-art distinguish-matrix \
  --application-number 18654466 --run-id run-…

# Human coverage acknowledgment + rule preflight checklist
python3 scripts/ops/uspto/portfolio_cli.py prior-art acknowledge \
  --application-number 18654466 --run-id run-… \
  --acknowledger "operator:you"
# Optional: request search-complete claim when report + ack prerequisites hold
python3 scripts/ops/uspto/portfolio_cli.py prior-art acknowledge \
  --application-number 18654466 --run-id run-… \
  --acknowledger "operator:you" --claim-search-complete

# Bind a run into a revision case (pointer under case_dir)
python3 scripts/ops/uspto/portfolio_cli.py prior-art attach-revision \
  --revision-id rev-18654466-… \
  --application-number 18654466 \
  --run-id run-…
```

### Foreign / NPL / expansion inputs

| Flag | Format |
| --- | --- |
| `--foreign-hits` | JSON/JSONL list of `{document_id, title?, country?, source_cid?}` (EP/WO/…) |
| `--foreign-snapshot` | Patent snapshot JSON converted to foreign hits |
| `--live-foreign` | EPO OPS live search (`EPO_OPS_KEY` + `EPO_OPS_SECRET`) |
| `--npl-catalog` | `{document_id, title?, identifier?, rights_status, body_text?, rights_approval_id?}` |
| `--npl-licensed` | Operator asserts catalog is licensed for this use (body text still rights-gated) |
| `--live-npl` | OpenAlex + Crossref public **metadata** search (optional `OPENALEX_API_KEY`, `CROSSREF_MAILTO`) |
| `--citation-graph` | `{citing_id, cited_id, direction}` edges |
| `--family-graph` | `{document_id, relation, related_to}` members |

Without a real foreign/NPL backend, those corpora stay **visible named gaps** (or explicit adapter failure). Unlicensed NPL body text is never retained. Live NPL clients return **titles/DOIs only** (no full-text bodies).

Patent Public Search is **human-only**: `pps-assist` may open the PPS landing page and print queries; it never auto-fills search, never scrapes results, and never claims PPS is an API.

**Still out of scope (by design):** automated patentability / novelty / obviousness determinations. Use `distinguish-matrix` for lexical drafting aids only.

Artifacts land under:

`~/.local/state/ipfs_datasets_py/patent_portfolio/operator-default/prior_art/<app>/<run_id>/`

| File | Purpose |
| --- | --- |
| `prior_art_plan.json` | PATLAW-094 plan (claims, limitations, queries, gaps) |
| `search_journal.json` | PATLAW-148 dated query journal (adapters, outcomes, hits) |
| `coverage_declaration.json` | Searched vs unsearched corpora + named gaps |
| `claim_chart.json` | Source-linked limitation ↔ hit map (candidates only) |
| `distinguishability_summary.json` | Review tips + top candidate hits (no conclusions) |
| `prior_art_report.json` | Combined plan + logs + chart for preflight |
| `distinguishability_matrix.json` | Limitation × doc lexical overlap (drafting aid only) |
| `pps_verification_checklist.json` | Human PPS interactive verification items |
| `human_coverage_acknowledgment.json` | Operator coverage-scope acknowledgment |
| `prior_art_rule_checklist.json` | Preflight readiness (still not patentability) |
| `adapter_status.json` | Which foreign/NPL/citation/family backends ran |

Libraries:

* `ipfs_datasets_py/processors/domains/uspto/prior_art_search_client.py`
* `ipfs_datasets_py/processors/domains/uspto/prior_art_operator_extensions.py`
* `ipfs_datasets_py/processors/domains/uspto/providers/epo_ops_client.py`
* `ipfs_datasets_py/processors/domains/uspto/providers/npl_public_clients.py`
* `scripts/ops/uspto/attended_pps_assist.py`

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
#    If --local-path points at the letter PDF (or export-ui already downloaded it),
#    open will OCR (local Tesseract) + parse rejections / reply period automatically.
python3 scripts/ops/uspto/portfolio_cli.py revise open \
  --application-number 18654466 \
  --document-code CTNF \
  --document-id OA123 \
  --document-description "Non-Final Rejection" \
  --official-date 2024-05-03 \
  --local-path /path/to/CTNF.pdf

# Re-run / force OCR analysis later:
python3 scripts/ops/uspto/portfolio_cli.py revise analyze \
  --revision-id rev-18654466-… \
  --force-ocr --save-text

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
#    Also builds a law guide from filing-obligation rules + local authority corpus
python3 scripts/ops/uspto/portfolio_cli.py revise prepare \
  --revision-id rev-18654466-…

# Law guide only (filing rules + citations + HF hybrid index + local excerpts)
python3 scripts/ops/uspto/portfolio_cli.py revise seed-corpus
# Drop text under ~/.local/state/.../authority_corpus/ (see README + index.json)
python3 scripts/ops/uspto/portfolio_cli.py revise guide \
  --revision-id rev-18654466-… \
  --application-type utility

# Direct hybrid search over JusticeDAO Hub indexes (BM25 + vector + knowledge graph)
# Repos: justicedao/patent-legal-{corpus,bm25,vectors,knowledge-graph}
python3 scripts/ops/uspto/portfolio_cli.py revise search-law \
  --query "37 CFR 1.121 claim amendments status identifiers"

# Prior art for claim distinguishability (see Prior-art search section)
python3 scripts/ops/uspto/portfolio_cli.py prior-art search \
  --application-number 18654466 \
  --claims-file ~/drafts/amended_claims.json \
  --odp --max-queries 6
python3 scripts/ops/uspto/portfolio_cli.py prior-art attach-revision \
  --revision-id rev-18654466-… \
  --application-number 18654466 \
  --run-id run-…

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
view-only Patent Center navigation; post-submit receipt watch/import;
public prior-art plan/search journals for human review; foreign/NPL named
adapters with operator-supplied catalogs; human PPS verification recording.

**Forbidden:** unattended Patent Center scrape; **Patent Public Search
automation/scrape**; storing passwords/MFA; typing credentials from env;
**sign / pay / final submission automation**; committing exports or browser
profiles; redistributing unlicensed NPL body text; treating prior-art journals
as patentability determinations.

## Policy

See `data/agent_supervisor/patent_legal_intelligence/bundles/private_boundary_policy.json`.

# Agentic Legal Scraper Daemon

The canonical legal-scraper daemon runs a persistent loop:

1. Scrape with one tactic profile.
2. Review coverage, fetch, and ETL diagnostics.
3. Criticize the result and update the preferred tactic.
4. Optionally run a router-assisted review using `llm_router`, `embeddings_router`, and `ipfs_backend_router` when weak cycles need extra guidance.
5. Optionally warm weak URLs in the archive stack.
6. Optionally run canonical merge, parquet, embeddings, and publish stages.

When post-cycle release is enabled, the merge stage is scoped to the daemon's active state list rather than rebuilding every state by default.

It currently supports these corpora:

- `state_laws`
- `state_admin_rules`
- `state_court_rules`

Built-in tactics now include `router_assisted`, which lets the daemon bias toward router-backed recovery on mixed or weak cycles while still using the existing `web_archiving` strategy stack in parallel.

The daemon now also carries forward recent cycle failures when picking the next tactic. Repeated document-heavy or coverage-gap cycles increase pressure toward `document_first`, `discovery_first`, and `router_assisted`, and bounded runs front-load the current priority states first so weak states are processed earlier in the next cycle.

Cycle artifacts and `daemon_state.json` now also record a `tactic_selection` block so you can inspect whether the daemon picked a tactic because it was untried, because it was exploring, or because exploit-mode ranking favored it due to recommendation bonuses, priority-state pressure, recurring issue pressure, or stagnation penalties.

For `state_admin_rules`, the daemon now also carries richer per-state document recovery telemetry into `diagnostics.documents.per_state_recovery` and `document_gap_report.states[STATE]`. Those blocks surface the lower-level admin agentic report details that matter during PDF and RTF recovery work, including `source_breakdown`, `domains_seen`, `parallel_prefetch`, `candidate_urls`, `inspected_urls`, `expanded_urls`, and any processed document method counts the daemon can infer from recovered rows.

The workspace wrapper now mirrors that at the shell level: successful runs emit a concise stderr summary with the selected tactic, selection mode, priority states, and cycle state order, while the pending-retry reporter includes the latest `tactic_selection` and `cycle_state_order` fields when `latest_summary.json` is present.

## Basic Usage

If you are working from the workspace root, you can also use the wrapper script:

```bash
cd /home/barberb/municipal_scrape_workspace
bash scripts/ops/legal_data/run_agentic_legal_daemon.sh
```

The wrapper reads optional environment variables from `/home/barberb/municipal_scrape_workspace/.env` and then runs the daemon from the `ipfs_datasets_py` package root.

Run a single diagnostic cycle for a small state subset:

```bash
cd /home/barberb/municipal_scrape_workspace/ipfs_datasets_py
PYTHONPATH=src .venv/bin/python -m ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon \
  --corpus state_laws \
  --states OR,WA \
  --max-cycles 1 \
  --archive-warmup-urls 10
```

Run the daemon continuously until it reaches the target score:

```bash
cd /home/barberb/municipal_scrape_workspace/ipfs_datasets_py
PYTHONPATH=src .venv/bin/python -m ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon \
  --corpus state_admin_rules \
  --states all \
  --target-score 0.94 \
  --stop-on-target-score
```

Run a bounded live admin-rules probe that fails closed and still writes cycle artifacts:

```bash
cd /home/barberb/municipal_scrape_workspace/ipfs_datasets_py
PYTHONPATH=src .venv/bin/python -m ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon \
  --corpus state_admin_rules \
  --states AZ,UT,IN \
  --output-dir /tmp/state_admin_rules_agentic_daemon_live_probe \
  --max-cycles 1 \
  --max-statutes 4 \
  --archive-warmup-urls 6 \
  --per-state-timeout-seconds 90 \
  --scrape-timeout-seconds 180 \
  --router-llm-timeout-seconds 5 \
  --router-embeddings-timeout-seconds 5 \
  --router-ipfs-timeout-seconds 5
```

Use `--scrape-timeout-seconds` for bounded recovery runs when you want a cycle to serialize an error result and checkpoints instead of hanging indefinitely in scrape.

## Post-Cycle Release Automation

Print a release plan without running a scrape cycle:

```bash
cd /home/barberb/municipal_scrape_workspace/ipfs_datasets_py
PYTHONPATH=src .venv/bin/python -m ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon \
  --corpus state_admin_rules \
  --print-post-cycle-release-plan \
  --post-cycle-release-workspace-root /home/barberb/municipal_scrape_workspace \
  --post-cycle-release-python-bin /home/barberb/municipal_scrape_workspace/.venv/bin/python \
  --post-cycle-release-publish-command 'LEGAL_PUBLISH_CORPUS={corpus_key} LEGAL_PUBLISH_LOCAL_DIR="{parquet_dir}" bash /home/barberb/municipal_scrape_workspace/scripts/ops/legal_data/run_publish_canonical_legal_corpus.sh'
```

Enable a dry-run release plan after a qualifying cycle:

```bash
cd /home/barberb/municipal_scrape_workspace/ipfs_datasets_py
PYTHONPATH=src .venv/bin/python -m ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon \
  --corpus state_laws \
  --states NY \
  --max-cycles 1 \
  --post-cycle-release \
  --post-cycle-release-dry-run \
  --post-cycle-release-min-score 0.93 \
  --post-cycle-release-workspace-root /home/barberb/municipal_scrape_workspace \
  --post-cycle-release-python-bin /home/barberb/municipal_scrape_workspace/.venv/bin/python
```

Append a publish hook after merge, parquet, and embeddings:

```bash
cd /home/barberb/municipal_scrape_workspace/ipfs_datasets_py
PYTHONPATH=src .venv/bin/python -m ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon \
  --corpus state_court_rules \
  --states CA \
  --max-cycles 1 \
  --post-cycle-release \
  --post-cycle-release-dry-run \
  --post-cycle-release-publish-command 'LEGAL_PUBLISH_CORPUS={corpus_key} LEGAL_PUBLISH_LOCAL_DIR="{parquet_dir}" bash /home/barberb/municipal_scrape_workspace/scripts/ops/legal_data/run_publish_canonical_legal_corpus.sh'
```

Available release controls:

- `--post-cycle-release`: enable merge/parquet/embeddings automation.
- `--print-post-cycle-release-plan`: emit the release command plan without scraping.
- `--post-cycle-release-dry-run`: emit the command plan without executing it.
- `--post-cycle-release-min-score`: require a minimum critic score before release.
- `--post-cycle-release-ignore-pass`: allow release planning or execution even if the cycle did not pass the normal success gates.
- `--post-cycle-release-timeout-seconds`: set the timeout for each live release stage.
- `--post-cycle-release-workspace-root`: point command resolution at a specific workspace root.
- `--post-cycle-release-python-bin`: select the interpreter for the release scripts.
- `--post-cycle-release-publish-command`: append a templated publish command.
- `--post-cycle-release-preview-score`: override the score stamp used in scrape-free preview mode.
- `--post-cycle-release-preview-cycle`: override the cycle number used in scrape-free preview mode.

## Workspace Environment Variables

The wrapper script recognizes these variables:

- `LEGAL_DAEMON_CORPUS`
- `LEGAL_DAEMON_STATES`
- `LEGAL_DAEMON_MAX_CYCLES`
- `LEGAL_DAEMON_MAX_STATUTES`
- `LEGAL_DAEMON_CYCLE_INTERVAL_SECONDS`
- `LEGAL_DAEMON_ARCHIVE_WARMUP_URLS`
- `LEGAL_DAEMON_PER_STATE_TIMEOUT_SECONDS`
- `LEGAL_DAEMON_SCRAPE_TIMEOUT_SECONDS`
- `LEGAL_DAEMON_ADMIN_AGENTIC_MAX_CANDIDATES_PER_STATE`
- `LEGAL_DAEMON_ADMIN_AGENTIC_MAX_FETCH_PER_STATE`
- `LEGAL_DAEMON_ADMIN_AGENTIC_MAX_RESULTS_PER_DOMAIN`
- `LEGAL_DAEMON_ADMIN_AGENTIC_MAX_HOPS`
- `LEGAL_DAEMON_ADMIN_AGENTIC_MAX_PAGES`
- `LEGAL_DAEMON_ADMIN_AGENTIC_FETCH_CONCURRENCY`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID`
- `IPFS_DATASETS_CLOUDFLARE_API_TOKEN`
- `LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID`
- `LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN`
- `IPFS_DATASETS_CLOUDFLARE_CRAWL_TIMEOUT_SECONDS`
- `IPFS_DATASETS_CLOUDFLARE_CRAWL_POLL_INTERVAL_SECONDS`
- `IPFS_DATASETS_CLOUDFLARE_CRAWL_MAX_RATE_LIMIT_WAIT_SECONDS`
- `IPFS_DATASETS_CLOUDFLARE_CRAWL_LIMIT`
- `IPFS_DATASETS_CLOUDFLARE_CRAWL_DEPTH`
- `IPFS_DATASETS_CLOUDFLARE_CRAWL_RENDER`
- `IPFS_DATASETS_CLOUDFLARE_CRAWL_SOURCE`
- `IPFS_DATASETS_CLOUDFLARE_CRAWL_FORMATS`
- `LEGAL_SCRAPER_CLOUDFLARE_CRAWL_TIMEOUT_SECONDS`
- `LEGAL_SCRAPER_CLOUDFLARE_CRAWL_POLL_INTERVAL_SECONDS`
- `LEGAL_SCRAPER_CLOUDFLARE_CRAWL_MAX_RATE_LIMIT_WAIT_SECONDS`
- `LEGAL_SCRAPER_CLOUDFLARE_CRAWL_LIMIT`
- `LEGAL_SCRAPER_CLOUDFLARE_CRAWL_DEPTH`
- `LEGAL_SCRAPER_CLOUDFLARE_CRAWL_RENDER`
- `LEGAL_SCRAPER_CLOUDFLARE_CRAWL_SOURCE`
- `LEGAL_SCRAPER_CLOUDFLARE_CRAWL_FORMATS`
- `LEGAL_DAEMON_ROUTER_LLM_TIMEOUT_SECONDS`
- `LEGAL_DAEMON_ROUTER_EMBEDDINGS_TIMEOUT_SECONDS`
- `LEGAL_DAEMON_ROUTER_IPFS_TIMEOUT_SECONDS`
- `LEGAL_DAEMON_TARGET_SCORE`
- `LEGAL_DAEMON_RANDOM_SEED`
- `LEGAL_DAEMON_OUTPUT_DIR`
- `LEGAL_DAEMON_STOP_ON_TARGET_SCORE`
- `LEGAL_DAEMON_PRINT_RELEASE_PLAN`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE_DRY_RUN`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE_MIN_SCORE`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE_IGNORE_PASS`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE_TIMEOUT_SECONDS`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE_WORKSPACE_ROOT`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE_PYTHON_BIN`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE_PUBLISH_COMMAND`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE_PREVIEW_SCORE`
- `LEGAL_DAEMON_POST_CYCLE_RELEASE_PREVIEW_CYCLE`
- `LEGAL_PUBLISH_CORPUS`
- `LEGAL_PUBLISH_LOCAL_DIR`
- `LEGAL_PUBLISH_REPO_ID`
- `LEGAL_PUBLISH_PATH_IN_REPO`
- `LEGAL_PUBLISH_TOKEN`
- `LEGAL_PUBLISH_COMMIT_MESSAGE`
- `LEGAL_PUBLISH_CID_COLUMN`
- `LEGAL_PUBLISH_CREATE_REPO`
- `LEGAL_PUBLISH_VERIFY`
- `LEGAL_PUBLISH_DRY_RUN`
- `LEGAL_PUBLISH_PYTHON_BIN`

Example `.env` block:

```dotenv
LEGAL_DAEMON_CORPUS=state_laws
LEGAL_DAEMON_STATES=NY,CA
LEGAL_DAEMON_MAX_CYCLES=1
LEGAL_DAEMON_MAX_STATUTES=25
LEGAL_DAEMON_PER_STATE_TIMEOUT_SECONDS=45
LEGAL_DAEMON_SCRAPE_TIMEOUT_SECONDS=180
CLOUDFLARE_ACCOUNT_ID=your_account_id
CLOUDFLARE_API_TOKEN=your_browser_rendering_token
LEGAL_SCRAPER_CLOUDFLARE_CRAWL_TIMEOUT_SECONDS=120
LEGAL_SCRAPER_CLOUDFLARE_CRAWL_MAX_RATE_LIMIT_WAIT_SECONDS=300
LEGAL_SCRAPER_CLOUDFLARE_CRAWL_RENDER=0
LEGAL_SCRAPER_CLOUDFLARE_CRAWL_FORMATS=markdown,html
LEGAL_DAEMON_ADMIN_AGENTIC_MAX_CANDIDATES_PER_STATE=12
LEGAL_DAEMON_ADMIN_AGENTIC_MAX_FETCH_PER_STATE=8
LEGAL_DAEMON_ROUTER_LLM_TIMEOUT_SECONDS=20
LEGAL_DAEMON_ROUTER_EMBEDDINGS_TIMEOUT_SECONDS=10
LEGAL_DAEMON_ROUTER_IPFS_TIMEOUT_SECONDS=10
LEGAL_DAEMON_POST_CYCLE_RELEASE=1
LEGAL_DAEMON_POST_CYCLE_RELEASE_DRY_RUN=1
LEGAL_DAEMON_POST_CYCLE_RELEASE_WORKSPACE_ROOT=/home/barberb/municipal_scrape_workspace
LEGAL_DAEMON_POST_CYCLE_RELEASE_PYTHON_BIN=/home/barberb/municipal_scrape_workspace/.venv/bin/python
LEGAL_DAEMON_POST_CYCLE_RELEASE_PUBLISH_COMMAND='LEGAL_PUBLISH_CORPUS={corpus_key} LEGAL_PUBLISH_LOCAL_DIR="{parquet_dir}" bash /home/barberb/municipal_scrape_workspace/scripts/ops/legal_data/run_publish_canonical_legal_corpus.sh'
LEGAL_PUBLISH_DRY_RUN=1
LEGAL_PUBLISH_VERIFY=0
```

Set `LEGAL_DAEMON_MAX_STATUTES=0` for an uncapped run.
Set `LEGAL_DAEMON_SCRAPE_TIMEOUT_SECONDS` for bounded live probes so the daemon records a completed error cycle instead of depending on an outer shell timeout.
Use the router timeout variables to bound unattended LLM, embeddings, and IPFS review stages.
Cloudflare Browser Rendering requires a custom API token with `Browser Rendering - Edit` permission; a token can verify as active but still fail crawl calls without that scope.
Cloudflare `/crawl` can also return transient `2001: Rate limit exceeded` responses during bursts of job creation or polling. The Cloudflare fallback now retries those responses automatically, but repeated smoke tests may still need a cooldown before the next live run succeeds.
If Cloudflare asks for a cooldown longer than the configured local wait budget, the client now returns a structured `rate_limited` result with `retry_after_seconds` and `retry_at_utc` so daemon orchestration can defer and requeue the crawl instead of spinning.
Use `*_CLOUDFLARE_CRAWL_MAX_RATE_LIMIT_WAIT_SECONDS` to control how long the client should wait locally before returning that structured `rate_limited` defer result.
The same `rate_limited` result now includes `rate_limit_diagnostics` with Cloudflare support identifiers such as `cf_ray`, `cf_auditlog_id`, `api_version`, `retry_after_header`, and the endpoint/operation that triggered the throttle.
When the daemon sees that defer result, it now records `pending_retry` in both `daemon_state.json` and `latest_summary.json`, skips review/archive/release follow-up work for that cycle, and waits until `retry_after_seconds` or `retry_at_utc` before the next cycle.
The daemon also writes a dedicated `latest_pending_retry.json` artifact, plus a per-cycle `cycle_XXXX_pending_retry.json` snapshot, so external monitors can poll the active cooldown without parsing the full summary.

## VS Code Tasks

The workspace root now exposes these tasks:

- `Legal daemon: release plan preview`
- `Legal daemon: one cycle dry run`
- `Legal daemon: continuous`
- `Legal daemon: pending retry watch`
- `Legal publish: dry run`
- `Legal publish: live`

## Publish Wrapper

You can run the canonical publisher directly from the workspace root:

```bash
cd /home/barberb/municipal_scrape_workspace
bash scripts/ops/legal_data/run_publish_canonical_legal_corpus.sh
```

The wrapper reads `LEGAL_PUBLISH_*` values from `.env` and executes `publish_canonical_legal_corpus_to_hf.py` with those defaults.

To inspect the active retry window without parsing the full daemon summary, you can also run:

```bash
cd /home/barberb/municipal_scrape_workspace
bash scripts/ops/legal_data/run_agentic_daemon_pending_retry_watch.sh \
  --daemon-output-dir /home/barberb/.ipfs_datasets/state_admin_rules/agentic_daemon
```

The helper prints `status: idle` when no cooldown is active, or `status: pending_retry` with `seconds_remaining` when `latest_pending_retry.json` is present.
Use `--watch` to poll until the cooldown reaches zero or the artifact disappears:

```bash
cd /home/barberb/municipal_scrape_workspace
LEGAL_DAEMON_PENDING_RETRY_CORPUS=state_admin_rules \
LEGAL_DAEMON_PENDING_RETRY_INTERVAL_SECONDS=10 \
bash scripts/ops/legal_data/run_agentic_daemon_pending_retry_watch.sh
```

The watch wrapper reads `.env` and supports these overrides:

- `LEGAL_DAEMON_PENDING_RETRY_CORPUS`
- `LEGAL_DAEMON_PENDING_RETRY_OUTPUT_DIR`
- `LEGAL_DAEMON_PENDING_RETRY_WATCH`
- `LEGAL_DAEMON_PENDING_RETRY_INTERVAL_SECONDS`
- `LEGAL_DAEMON_PENDING_RETRY_MAX_REPORTS`

Template variables available to the publish command:

- `{workspace_root}`
- `{python_bin}`
- `{merge_output_dir}`
- `{jsonld_dir}`
- `{parquet_dir}`
- `{combined_parquet}`
- `{combined_embeddings}`
- `{corpus_key}`
- `{critic_score}`

## Output Artifacts

The daemon writes:

- `daemon_state.json`: persistent tactic history, best-known tactic, and any scheduled `pending_retry` cooldown.
- `latest_summary.json`: latest cycle summary or daemon run summary, including `pending_retry` when the next cycle has been deferred.
- `latest_pending_retry.json`: the currently active deferred-retry cooldown, removed automatically once a later cycle is no longer deferred.
- `cycles/cycle_XXXX.json`: one JSON summary per cycle.
- `cycles/cycle_XXXX_pending_retry.json`: per-cycle deferred-retry snapshot when a provider-directed cooldown was scheduled.
- `latest_document_gaps.json`: latest compact PDF/RTF gap summary when document candidates were detected but not processed.
- `cycles/cycle_XXXX_document_gaps.json`: per-cycle compact document-gap artifact for operator review.
- `latest_router_assist.json`: latest router-assisted review artifact, including LLM guidance, embeddings-based tactic ranking, and optional IPFS persistence metadata.
- `cycles/cycle_XXXX_router_assist.json`: per-cycle router-assisted review artifact.

For `state_admin_rules`, the compact document-gap artifacts surface the states that still have candidate PDF or RTF URLs, the top candidate document URLs, per-format processed counts, and host-level gap hints from the agentic report.

When router backends are available, the router-assisted review artifacts also capture:

- best-effort LLM recommendations for next tactics and query hints
- embeddings-based ranking of tactic profiles against the current critic summary
- best-effort IPFS persistence metadata for the review artifact itself

For `state_admin_rules`, state-scoped query hints from the router-assisted review are now persisted in daemon state and injected back into the next cycle's agentic discovery query and target-term list. That means the daemon can automatically carry forward hints like agency names, title numbers, and PDF/RTF-specific recovery phrases instead of only changing tactic order.

By default, daemon output lives under:

- `~/.ipfs_datasets/state_laws/agentic_daemon`
- `~/.ipfs_datasets/state_admin_rules/agentic_daemon`
- `~/.ipfs_datasets/state_court_rules/agentic_daemon`
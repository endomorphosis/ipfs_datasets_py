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
LEGAL_DAEMON_POST_CYCLE_RELEASE=1
LEGAL_DAEMON_POST_CYCLE_RELEASE_DRY_RUN=1
LEGAL_DAEMON_POST_CYCLE_RELEASE_WORKSPACE_ROOT=/home/barberb/municipal_scrape_workspace
LEGAL_DAEMON_POST_CYCLE_RELEASE_PYTHON_BIN=/home/barberb/municipal_scrape_workspace/.venv/bin/python
LEGAL_DAEMON_POST_CYCLE_RELEASE_PUBLISH_COMMAND='LEGAL_PUBLISH_CORPUS={corpus_key} LEGAL_PUBLISH_LOCAL_DIR="{parquet_dir}" bash /home/barberb/municipal_scrape_workspace/scripts/ops/legal_data/run_publish_canonical_legal_corpus.sh'
LEGAL_PUBLISH_DRY_RUN=1
LEGAL_PUBLISH_VERIFY=0
```

Set `LEGAL_DAEMON_MAX_STATUTES=0` for an uncapped run.

## VS Code Tasks

The workspace root now exposes these tasks:

- `Legal daemon: release plan preview`
- `Legal daemon: one cycle dry run`
- `Legal daemon: continuous`
- `Legal publish: dry run`
- `Legal publish: live`

## Publish Wrapper

You can run the canonical publisher directly from the workspace root:

```bash
cd /home/barberb/municipal_scrape_workspace
bash scripts/ops/legal_data/run_publish_canonical_legal_corpus.sh
```

The wrapper reads `LEGAL_PUBLISH_*` values from `.env` and executes `publish_canonical_legal_corpus_to_hf.py` with those defaults.

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

- `daemon_state.json`: persistent tactic history and best-known tactic.
- `latest_summary.json`: latest cycle summary or daemon run summary.
- `cycles/cycle_XXXX.json`: one JSON summary per cycle.
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
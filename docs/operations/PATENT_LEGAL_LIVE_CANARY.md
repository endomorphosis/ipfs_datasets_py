# Patent Legal Intelligence — Live Official-Source Canary

**Task:** `PATLAW-167`  
**Goal:** `PATLAW-G202`  
**Track:** post-completion-ops  
**Depends on:** `PATLAW-165` (offline completion-gate validation)

This runbook is the operator surface for an **optional live official-source
canary with offline fixture fallback**. It probes public eCFR, GovInfo, Federal
Register, and USPTO ODP endpoints in a **bounded, read-only, receipt-bound**
way. It does **not** publish to Hub main, open Patent Center sessions, process
payments, capture signatures, auto-push remotes, or mutate private matter state.

## Standing rules (fail-closed)

1. **Offline is the default.** Automated validation and CI use compact offline
   fixtures. No network I/O occurs unless the operator explicitly opts into
   live mode.
2. **Live is opt-in.** Enable with `--live` or one of:
   - `PATLAW_LIVE_CANARY=1`
   - `PATLAW_167_LIVE_CANARY=1`
   - `PATENT_LEGAL_LIVE_CANARY=1`
3. **Content-free receipts only.** Digests, status codes, host labels, counts,
   and short reason strings. Never document bodies, extracted text, API keys,
   bearer tokens, cookies, portfolio content, or raw provider payloads.
4. **Never mutates private matter state.** The canary refuses to write receipts
   under private-matter paths and can snapshot an optional `--matter-root` to
   prove immutability.
5. **Read-only probes.** GET/HEAD only. Forbidden mutations include sign, pay,
   file, submit, scrape Patent Center, store credentials, and write private
   matter/portfolio state.
6. **HTTP success ≠ authenticity.** Live connectivity receipts are health
   signals, not official-source verification or legal authority proof.
7. **Bounded budgets.** Default four probes (one per source family), hard cap
   eight, 256 KiB max response bytes hashed then discarded, 15s timeout.

## What the canary answers

> Are the official discovery surfaces for eCFR, GovInfo, Federal Register, and
> ODP reachable (or replayable offline) without touching private portfolio
> state, and is that observation sealed in a content-free receipt?

| Mode | Role |
| --- | --- |
| `offline` (default) | Replay embedded fixtures for all four sources; network-free |
| `live` (opt-in) | Bounded HTTPS GET probes; record status + body digest only |

## Operator commands

### Offline (default — required for CI / daemon validation)

```bash
python scripts/ops/patent_legal_intelligence/live_canary.py --json
python scripts/ops/patent_legal_intelligence/live_canary.py --offline --json
python -m pytest tests/integration/ops/patent_legal_intelligence/test_live_canary.py -q
```

Offline always reports `mode=offline`, `network_invoked=false`, fixture probe
status for eCFR / GovInfo / Federal Register / ODP, and
`disposition=offline_ok` when fixtures materialize cleanly.

### Optional live probes

```bash
# Explicit CLI opt-in
python scripts/ops/patent_legal_intelligence/live_canary.py --live --json

# Or via environment
PATLAW_167_LIVE_CANARY=1 \
  python scripts/ops/patent_legal_intelligence/live_canary.py --json

# Write receipts to an operator path (never a private matter root)
python scripts/ops/patent_legal_intelligence/live_canary.py --live \
  --receipt-dir "$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/live_canary" \
  --json
```

### Assert private matter immutability

```bash
python scripts/ops/patent_legal_intelligence/live_canary.py --offline \
  --matter-root /path/to/private_matter/tenant \
  --json
```

If anything under `--matter-root` changes during the run, the canary fails
closed with a non-zero exit and does not claim success.

### Dry report without writing a receipt

```bash
python scripts/ops/patent_legal_intelligence/live_canary.py --offline --no-write --json
```

## Probe inventory

| Source | Default target (read-only) | Authority label |
| --- | --- | --- |
| `ecfr` | `https://www.ecfr.gov/api/versioner/v1/titles.json` | Unofficial editorial presentation |
| `govinfo` | `https://api.govinfo.gov/collections?pageSize=1&offsetMark=*` | Official source discovery |
| `federal_register` | `https://www.federalregister.gov/api/v1/agencies` | Unofficial editorial presentation |
| `odp` | `https://api.uspto.gov/swagger/openapi.json` | Public provider metadata (no credentials) |

Hosts are allowlisted. Non-HTTPS, non-443, userinfo, and off-list hosts are
rejected as `policy_violation` before any network I/O.

## Receipt layout

Default directory:

`$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/live_canary/`

(or `~/.local/state/...` when `XDG_STATE_HOME` is unset)

| File | Role |
| --- | --- |
| `canary-{mode}-{timestamp}.json` | Immutable run receipt |
| `canary-latest.json` | Stable pointer for handoff tools (`PATLAW-169`) |

Receipt fields (content-free):

* `schema_version`, `interface`, `task_id` (`PATLAW-167`), `goal_id` (`PATLAW-G202`)
* `mode` ∈ `{offline, live}`, `opt_in`, `read_only`, `bounded`, `secret_redacted`
* `network_invoked`, `probe_count`, `sources_probed`, `disposition`, `ok`
* `private_matter_mutated` (must be `false` for acceptance)
* per-probe: `source`, `status`, `status_code`, `host`, `endpoint_fingerprint`,
  `body_sha256`, `body_bytes`, `fixture`, `read_only` (no body text)
* `forbidden_mutations` list
* `receipt_sha256` binding digest

### Disposition taxonomy

| Disposition | Meaning |
| --- | --- |
| `offline_ok` | Offline fixtures materialised for required sources |
| `pass` | Live probes succeeded |
| `pass_with_gaps` | Live mixed success with transport/HTTP gaps (receipt-bound) |
| `fail` | Hard failure or private-matter mutation |
| `skipped_live` | Reserved for future waived-live handoff cases |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | `ok` true (`offline_ok`, `pass`, or `pass_with_gaps`) |
| `1` | `ok` false (failed probes / private-matter mutation) |
| `2` | Configuration / flag error |

## Integration with post-completion ops

| Task | Relationship |
| --- | --- |
| `PATLAW-165` | Offline gate/status must exist before trusting canary disposition in handoff |
| `PATLAW-166` | PR package may reference canary disposition; no auto-push |
| `PATLAW-167` | This canary tool and tests |
| `PATLAW-168` | Hub dry-run is independent; no main publish |
| `PATLAW-169` | Handoff receipt binds canary disposition + latest receipt path |

Catalog entry:
`data/agent_supervisor/patent_legal_intelligence/bundles/post_completion_ops_catalog.json`

## Failure triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Offline `ok: false` | Fixture recipe incomplete | Re-run; ensure module fixtures build four sources |
| Live all `transport_error` | Network egress blocked | Record gaps; offline disposition still valid for CI |
| Live `policy_violation` | Host/URL not allowlisted | Use default probe specs; do not widen allowlist casually |
| `private_matter_mutated` | Side-effect write under matter root | Stop; treat as incident — canary must not write matter state |
| Content-free error | Secret/document marker in payload | Strip private fields; re-run |
| Receipt refused under private path | `--receipt-dir` looks like matter store | Choose operator state dir under `XDG_STATE_HOME` |

## Related surfaces

| Surface | Role |
| --- | --- |
| `scripts/ops/patent_legal_intelligence/live_canary.py` | Canary CLI / library |
| `tests/integration/ops/patent_legal_intelligence/test_live_canary.py` | Offline + scripted-live contract |
| `docs/operations/PATENT_LEGAL_POST_COMPLETION_OPS.md` | Parent post-completion runbook |
| `docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md` | Production gate (PATLAW-164) |
| `ipfs_datasets_py/.../patent_source_transport.py` | Shared legal-source transport (PATLAW-127) |
| `ipfs_datasets_py/.../odp_contract_monitor.py` | ODP auth/profile canary (PATLAW-124/142) |

## What this is not

* Not a legal opinion or patentability determination
* Not official-source authentication or annual-edition verification
* Not a Patent Center filing acknowledgement
* Not a Hub main publication approval
* Not a license to store private portfolio content in public receipts
* Not satisfied by taskboard status alone
* Not an unattended live-network requirement for CI or daemon validation

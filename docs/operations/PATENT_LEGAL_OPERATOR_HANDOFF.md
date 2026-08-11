# Patent Legal Operator Handoff (PATLAW-169)

This runbook seals the **post-completion ops** phase with a single content-free
handoff receipt. It does **not** authorize filing, payment, signature, Patent
Center submission, or Hub main publication.

## What the receipt binds

| Component | Source |
| --- | --- |
| Exact tree | `git rev-parse HEAD` and `HEAD^{tree}` |
| Offline gate / production status | `production_status.py --offline --json` |
| PR package | `prepare_pr_package.py` artifact under XDG state `pr_package/` |
| Canary | `live_canary.py` receipt under XDG state `canary/` |
| Hub dry-run | dry-run receipt under XDG state `hub_dry_run/` or explicit path |
| Remaining human actions | Always includes natural-person push/PR and no auto legal sign-off |

## Generate the handoff

```bash
python3 scripts/ops/patent_legal_intelligence/handoff_receipt.py \
  --repo-root . \
  --json
```

Default write path:

`$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/handoff/operator_handoff_receipt.json`

Optional explicit bindings:

```bash
python3 scripts/ops/patent_legal_intelligence/handoff_receipt.py \
  --pr-package /path/to/pr_package.json \
  --canary-receipt /path/to/canary_receipt.json \
  --hub-dry-run-receipt /path/to/hub_dry_run_receipt.json \
  --output /tmp/operator_handoff_receipt.json \
  --json
```

## Human-required steps (never automated)

1. Review the PR package commits, paths, and receipts.
2. Confirm offline production_status / completion-gate disposition.
3. A natural person runs `git push` if appropriate.
4. A natural person opens or updates the GitHub PR.
5. Human review of the PR and digests.
6. Explicit human approval before any Hub promote (dry-run is not publish).
7. No unattended legal sign-off, filing, payment, or Patent Center automation.

## Validation

```bash
python -m pytest tests/release/test_patent_legal_handoff_receipt.py -q
```

## Policy

* Content-free only (IDs, digests, counts, timestamps, gaps).
* `auto_push`, `auto_file`, and `legal_signoff_complete` are always false.
* Missing artifacts are listed as gaps; they do not invent success.

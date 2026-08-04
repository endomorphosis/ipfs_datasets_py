# Patent Legal Intelligence — Feature-Branch PR Package

**Task:** `PATLAW-166`  
**Goal:** `PATLAW-G201`  
**Track:** post-completion-ops  
**Depends on:** `PATLAW-165` (offline completion-gate validation)  
**CLI:** `scripts/ops/patent_legal_intelligence/prepare_pr_package.py`  
**Tests:** `tests/unit/scripts/ops/patent_legal_intelligence/test_prepare_pr_package.py`  
**Feature branch:** `feature/patent-legal-intelligence`

This runbook is the operator surface for assembling a **local** PR package after
offline completion-gate validation. The package summarizes commits, changed
paths, completion receipts, and **human-required** push / PR steps so a natural
person can open or update a GitHub pull request.

The tool does **not** push remotes, force-push, open authenticated PRs, publish
to Hub main, open Patent Center sessions, process payments, or capture
signatures.

## Standing rules (fail-closed)

1. **Package only.** `prepare_pr_package.py` never runs `git push`, never opens
   authenticated remote PRs, and never publishes.
2. **Content-free.** Package JSON and markdown never include document bodies,
   extracted text, embeddings, API keys, bearer tokens, cookies, or raw
   provider payloads. Commit subjects and path names only.
3. **Evidence over status.** Task status, backlog completion, goal status, or a
   drained supervisor board **cannot** alone authorize merge or production
   claims.
4. **Gaps must be explicit.** Missing live receipts appear under
   `evidence_gaps`; silent omission is forbidden.
5. **Human push / PR.** A natural person performs `git push` and opens or
   updates the GitHub PR using the package summary as the body.
6. **Receipts outside source.** Fresh package artifacts default under
   `$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/pr_package/`
   (not under tracked `data/`).

## What the package answers

> Given the current tree, what commits and paths would a human include in a PR
> on `feature/patent-legal-intelligence`, which completion receipts are present
> or gap-listed, and which push/PR steps remain human-only?

| Field | Role |
| --- | --- |
| `git` | `head_sha`, `tree_sha`, branch, base ref, merge-base; `push_performed=false` |
| `commits` | Content-free commit inventory (`sha`, `short_sha`, `subject`) for `base..HEAD` |
| `changed_paths` | Name-status path inventory relative to base |
| `completion_receipts` | Tree-bound gate artifacts + live/offline evidence receipt inventory |
| `evidence_gaps` | Explicit missing paths (tree or live) |
| `human_required_steps` | Ordered human-only push / PR / review steps with suggested commands |
| `package_digest_sha256` | Canonical digest of the package body |
| `auto_push` / `push_performed` | Always `false` |

## Operator commands

### Assemble the local package (default)

```bash
python scripts/ops/patent_legal_intelligence/prepare_pr_package.py
```

Writes JSON + markdown under:

`$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/pr_package/`

(or `~/.local/state/...` when `XDG_STATE_HOME` is unset).

Stdout prints a compact summary including `package_id`, digests, commit/path
counts, gap count, and written paths. Exit `0` when tree completion artifacts
are present and the package is ready for human push; exit `1` when incomplete;
exit `2` on hard failure.

### Full JSON package on stdout

```bash
python scripts/ops/patent_legal_intelligence/prepare_pr_package.py --json --no-write
```

### Markdown PR body on stdout

```bash
python scripts/ops/patent_legal_intelligence/prepare_pr_package.py --markdown --no-write
```

### Explicit base ref and output paths

```bash
python scripts/ops/patent_legal_intelligence/prepare_pr_package.py \
  --base-ref origin/main \
  --branch feature/patent-legal-intelligence \
  --output /tmp/patlaw-pr-package.json \
  --output-markdown /tmp/patlaw-pr-package.md
```

### Point at a live evidence root

```bash
python scripts/ops/patent_legal_intelligence/prepare_pr_package.py \
  --evidence-root "$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence"
```

## Human-required push / PR steps

After the package is written, a **natural person** must:

1. **Review the package** — inspect commits, changed paths, receipts, and gaps.
2. **Confirm offline gate** — offline completion-gate / production-status
   projection is coherent (`drained` or `completed`) with gaps explicit
   (see `docs/operations/PATENT_LEGAL_POST_COMPLETION_OPS.md`).
3. **Push the feature branch** (tool never does this):

   ```bash
   git push -u origin feature/patent-legal-intelligence
   ```

4. **Open or update a GitHub PR** (tool never invokes `gh` / the API):

   ```bash
   gh pr create --base main --head feature/patent-legal-intelligence \
     --title 'Patent legal intelligence: post-completion package' \
     --body-file /path/to/prpkg-….md
   ```

5. **Obtain human code review** — do not merge from drained-board status alone.
6. **Withhold unattended publish** — no Hub main publish, Patent Center login,
   payment, or signature from this package.

## Tree-bound completion artifacts inventoried

| Path | Task |
| --- | --- |
| `scripts/ops/uspto/validate_production_release.py` | PATLAW-164 |
| `scripts/ops/patent_legal_intelligence/production_status.py` | PATLAW-163 |
| `tests/release/test_patent_legal_production_release.py` | PATLAW-164 |
| `data/release/patent_legal_intelligence/production_receipt.schema.json` | PATLAW-164 |
| `docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md` | PATLAW-164 |
| `docs/operations/PATENT_LEGAL_POST_COMPLETION_OPS.md` | PATLAW-165 |
| `docs/operations/PATENT_LEGAL_PR_PACKAGE.md` | PATLAW-166 |
| `scripts/ops/patent_legal_intelligence/prepare_pr_package.py` | PATLAW-166 |
| `tests/unit/scripts/ops/patent_legal_intelligence/test_prepare_pr_package.py` | PATLAW-166 |

Missing tree artifacts make `status=incomplete` and
`ready_for_human_push=false`. Live evidence gaps are listed under
`evidence_gaps` and do not alone block packaging when tree artifacts are
present.

## Interpreting the package

| Field | Meaning |
| --- | --- |
| `status` | `ready` when git binding + all tree completion artifacts present |
| `ready_for_human_push` | `true` only when packaging is coherent for human push/PR |
| `auto_push` | Always `false` |
| `push_performed` | Always `false` (this tool never pushes) |
| `remote_publish_performed` | Always `false` |
| `authenticated_pr_opened` | Always `false` |
| `evidence_gaps` | Explicit missing tree or live receipt paths |
| `package_digest_sha256` | Immutable digest of the package body |

## Validation

```bash
python -m pytest tests/unit/scripts/ops/patent_legal_intelligence/test_prepare_pr_package.py -q
```

## Related surfaces

| Surface | Role |
| --- | --- |
| `docs/operations/PATENT_LEGAL_POST_COMPLETION_OPS.md` | PATLAW-165 offline gate + evidence inventory |
| `docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md` | PATLAW-164 production completion gate |
| `scripts/ops/uspto/validate_production_release.py` | Offline / live gate CLI |
| `scripts/ops/patent_legal_intelligence/production_status.py` | Production status / projection CLI |
| `data/agent_supervisor/patent_legal_intelligence/bundles/post_completion_ops_catalog.json` | Bounded post-completion catalog |

## What this is not

* Not a `git push` or force-push
* Not an authenticated GitHub PR open/update
* Not a Hub main publication approval
* Not a Patent Center filing acknowledgement
* Not a legal opinion or patentability determination
* Not satisfied by taskboard drained status alone
* Not a license to skip human review for push, PR, filing, or payment

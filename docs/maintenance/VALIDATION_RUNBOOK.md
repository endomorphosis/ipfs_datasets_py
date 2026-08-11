# Documentation validation runbook

| Field | Value |
| --- | --- |
| Interface | `DocumentationValidator@1` (runbook) |
| Task | `IPFSDOC-006` |
| Status | `canonical` |
| Owner | documentation-governance |
| Source of truth | `docs/maintenance/check_docs.py`, `docs/maintenance/INFORMATION_ARCHITECTURE.md` §4–§6, program plan validation model |
| Last verified | 2026-08-03 |
| Audience | maintainer, developer, agent |

## Purpose

This runbook explains how to run the **deterministic offline** documentation
validator for the IPFS Datasets Python corpus, how to interpret results, when
to use allowlists, and what the tool deliberately does **not** do.

The validator implements the quality gate needed by later release tasks (for
example producing the maintenance quality report via `--report`) without
depending on legacy audit scripts that required network or impure environment
state.

## Tool location

| Artifact | Path |
| --- | --- |
| Checker | [`docs/maintenance/check_docs.py`](check_docs.py) |
| This runbook | [`docs/maintenance/VALIDATION_RUNBOOK.md`](VALIDATION_RUNBOOK.md) |
| Page contract | [`docs/maintenance/INFORMATION_ARCHITECTURE.md`](INFORMATION_ARCHITECTURE.md) |
| Contributor workflow | [`docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md`](../developer_guides/DOCUMENTATION_CONTRIBUTING.md) |

Interface id: `DocumentationValidator@1`.

## Non-negotiable policies

These constraints are part of the acceptance contract. Do not “fix” failures
by violating them.

| Policy | Rule |
| --- | --- |
| **No network** | The checker never fetches `http(s)`, APIs, or package indexes. External links are classified and skipped. |
| **No mtime freshness** | Filesystem mtime/ctime are **not** proof that a page is current. Freshness is the in-document `Last verified` field (content), re-checked by a human/agent against sources. |
| **No destructive cleanup** | The checker never deletes `site/`, build outputs, or other generated artifacts. Optional `--report` / `--json-report` only create or overwrite the named report path(s). |
| **Allowlists are explicit** | Archive trees and before-migration examples are allowlisted by **prefix/substring/fence token**, not by silently ignoring all failures. Do not expand allowlists to hide P0/P1 issues on maintained pages. |
| **Offline stdlib** | Runtime dependency is Python 3 stdlib only (`ast`, `argparse`, `pathlib`, …). |

## What the checker validates

| Check id | What it does |
| --- | --- |
| `markdown_paths` | Inventories Markdown under `--root`; flags empty files. |
| `links` | Relative Markdown links resolve to an existing repository path. External URLs are not fetched. |
| `anchors` | Fragment identifiers (`#section`) resolve to heading slugs or explicit ids on the target page. |
| `repo_paths` | Backtick-cited repository paths (e.g. `` `ipfs_datasets_py/foo.py` ``, `` `docs/a.md` ``, `` `pyproject.toml` ``) exist on the tree. |
| `python_modules` | Dotted `ipfs_datasets_py…` / `tests…` module names and fence imports resolve to files or packages on the tree (path mapping, not live import). |
| `metadata` | Pages with `Status` = `canonical` require Owner, Source/Source of truth, Last verified (`YYYY-MM-DD`), and Audience. `evidence` requires Owner, Source, Last verified. `plan` requires Owner. |
| `duplicates` | Duplicate `Interface` values among `Status=canonical` pages are errors; shared H1 without Interface among multiple canonical pages is a warning. |
| `python_syntax` | Fenced `python` / `py` / `pycon` blocks parse with `ast.parse`. Incomplete snippets are warnings; fence tokens can allowlist intentional examples. |

Default is `--checks all` (every row above).

## Quick start

From the repository root:

```bash
# Help / smoke
python docs/maintenance/check_docs.py --help
python -m py_compile docs/maintenance/check_docs.py

# Full docs tree (typical local gate)
python docs/maintenance/check_docs.py --root docs

# Subtree while editing a lane
python docs/maintenance/check_docs.py --root docs/maintenance
python docs/maintenance/check_docs.py --root docs/architecture --checks links,anchors,metadata

# Release-style report (later quality task owns the report path)
python docs/maintenance/check_docs.py --root docs --report docs/maintenance/QUALITY_REPORT.md
# (QUALITY_REPORT.md is created by that command / later task; not a pre-existing citation)

# Machine-readable findings
python docs/maintenance/check_docs.py --root docs --json-report /tmp/docs_check.json --fail-on never
```

Exit codes:

| Code | Meaning |
| --- | ---: |
| `0` | No findings at or above `--fail-on` threshold |
| `1` | One or more failing findings |
| `2` | Usage / scan-root configuration error |

Default `--fail-on error` (warnings do not fail the process). Use
`--fail-on warning` for stricter PR gates. Use `--fail-on never` when you only
want a report.

## CLI reference (summary)

| Flag | Purpose |
| --- | --- |
| `--root PATH` | Scan root (default `docs`) |
| `--repo-root PATH` | Override auto-detected repository root |
| `--report PATH` | Write Markdown report (overwrite that path only) |
| `--json-report PATH` | Write JSON report (overwrite that path only) |
| `--checks LIST` | `all` or comma-separated check ids |
| `--allowlist-prefix P` | Extra archive/historical prefix (repeatable) |
| `--migration-substring S` | Extra before-migration path substring (repeatable) |
| `--strict-allowlist` | Promote allowlisted findings to errors |
| `--fail-on error\|warning\|never` | Exit threshold |
| `--max-print N` | Limit stdout finding lines |
| `--quiet` / `--verbose` | Stdout verbosity |
| `--version` | Print tool version and interface id |

Run `python docs/maintenance/check_docs.py --help` for the authoritative list.

## Allowlists

### Archive / historical paths (default prefixes)

Findings under these **repo-relative prefixes** are severity `allowlisted`
(reported, non-failing unless `--strict-allowlist`):

- `docs/archive/`
- `docs/archived_stubs/`
- `archive/`
- `docs/knowledge_graphs/archive/`
- `docs/logic/archive/`
- `docs/tdfol/`

Also, any path with a directory segment in
`{archive, archived_stubs, ARCHIVE, completion_reports, PHASE_REPORTS, refactoring_history}`
is treated as archive allowlisted.

### Before-migration examples (default path substrings)

Paths whose repo-relative path contains (case-insensitive):

- `migration`
- `before-migration` / `before_migration`
- `deprecat`
- `legacy`

…are allowlisted for the same soft-failure behavior. This preserves intentional
old/new pairs in migration guides without treating them as current API
authority.

### Fence-level tokens

On a fenced block info string, any of these tokens skip hard Python checks for
that fence (recorded as allowlisted):

`before-migration`, `before_migration`, `historical`, `legacy`, `incomplete`,
`pseudo`, `not-executable`, `allow-broken`, `allow_broken`, `no-check`,
`nocheck`

Example:

````markdown
```python before-migration
from old_package.removed_module import Thing  # intentional historical example
```
````

### Expanding allowlists

1. Prefer fixing the maintained page or marking lifecycle `historical` /
   `deprecated` with a pointer to the canonical home.
2. Prefer a fence token for a single intentional broken snippet.
3. Only add `--allowlist-prefix` / `--migration-substring` (or a code change to
   the defaults) with review — **do not hide P0/P1 failures on canonical
   surfaces** by broadening allowlists (release acceptance forbids this).

## Metadata expectations (canonical pages)

Aligned with INFORMATION_ARCHITECTURE §4. Minimum table for a new/refreshed
canonical page:

```markdown
# Title matching the concern

| Field | Value |
| --- | --- |
| Status | canonical |
| Owner | <team-or-role> |
| Source of truth | `<path>`, `<module>`, … |
| Last verified | YYYY-MM-DD |
| Audience | <primary audience id> |
```

Optional but recommended for program deliverables: `Interface` (stable contract
id). Duplicate `Interface` values on two `Status=canonical` pages fail
`duplicates`.

YAML front matter with the same field names is also accepted.

**Last verified** must be an ISO date string in the document. The checker will
not set or “refresh” it from disk timestamps.

## Severity model

| Severity | Meaning | Default exit impact |
| --- | --- | --- |
| `error` | Broken link/path/module, missing required metadata, bad Python fence, duplicate Interface | Fails (`--fail-on error`) |
| `warning` | Incomplete snippet parse, ambiguous metadata, duplicate H1 without Interface | No fail unless `--fail-on warning` |
| `allowlisted` | Same classes of issues under archive/migration policy | No fail unless `--strict-allowlist` |
| `info` | Inventory notes, skipped external links | Never fails |

## When to run

| Trigger | Suggested command |
| --- | --- |
| Editing one page / subtree | `python docs/maintenance/check_docs.py --root <dir> --checks links,anchors,metadata,python_syntax` |
| Lane complete (architecture, guides, …) | `python docs/maintenance/check_docs.py --root docs/<lane>` |
| Pre-merge docs PR | `python docs/maintenance/check_docs.py --root docs --fail-on error` |
| Release quality evidence | `python docs/maintenance/check_docs.py --root docs --report docs/maintenance/QUALITY_REPORT.md` |
| Investigating only syntax | `python docs/maintenance/check_docs.py --root docs --checks python_syntax` |

Per-page author checklist (also in the contributing guide):

1. Page nonempty; metadata complete for its `Status`.
2. Relative links and anchors resolve.
3. Cited repo paths and local modules exist on this tree.
4. Python fences parse (or carry an allow token / incompleteness markers).
5. No second page claims the same `Interface` as canonical.
6. Update `Last verified` only after re-checking sources (not after typo-only
   edits without source review).

## Interpreting a quality report

A Markdown report from `--report` includes:

- UTC start/finish timestamps and scan/repo roots
- Git HEAD when readable from `.git` **without** network
- File and finding counts by check and severity
- Explicit policy notes (no network, no mtime freshness, no deletes)
- Active allowlist prefixes
- Tables of findings

Treat `error` rows on non-allowlisted maintained paths as merge blockers for
documentation PRs that claim those paths. Treat `allowlisted` rows as audit
trail for historical material — still review periodically, do not ignore if a
“canonical” page was mis-filed under an archive prefix.

## Optional / deferred gates (not this tool)

These remain separate, environment-dependent, and must not be faked by
`check_docs.py`:

| Gate | Notes |
| --- | --- |
| MkDocs site build | `mkdocs build --strict` when MkDocs and deps are provisioned |
| Live example execution | Bounded offline commands claimed on individual pages |
| Full pytest / GPU / prover suites | Product test evidence, not doc link checking |
| External link liveness | Requires network; out of scope for this checker |
| Claim / authority inflation audit | Human + drift matrix (`DRIFT_AND_CLAIM_MATRIX.md`); later release tasks may add structured claim checks |

A missing optional MkDocs binary is **unavailable**, not a silent pass of the
deterministic checks. Record it in release evidence when relevant.

## Relationship to legacy scripts

Older helpers under `scripts/audit_docs_drift.py` and similar may perform
import-time or environment-coupled scans. They are **not** the
`DocumentationValidator@1` contract. Prefer `docs/maintenance/check_docs.py`
for reproducible documentation gates in this program.

## Failure triage playbook

1. **Re-run focused** — limit `--root` and `--checks` to the failing class.
2. **Confirm path** — is the page under an archive/migration allowlist by
   mistake? If it is maintained authority, move or re-label rather than
   allowlisting.
3. **Fix sources of truth first** — if a module path moved, update the doc to
   the current tree; do not change product code only to satisfy prose.
4. **Metadata** — add the IA §4 table; set `Status` honestly (`historical` /
   `deprecated` instead of false `canonical`).
5. **Python fences** — fix syntax, mark incomplete snippets, or add a fence
   allow token for intentional historical samples.
6. **Duplicates** — pick one canonical home; demote or pointer the rest;
   ensure `Interface` ids are unique among canonical pages.
7. **Never** delete `site/` or other generated trees to “clean” the gate; never
   use mtime scripts to stamp `Last verified`.

## Validation of this runbook and checker

```bash
python docs/maintenance/check_docs.py --help
python -m py_compile docs/maintenance/check_docs.py
test -s docs/maintenance/VALIDATION_RUNBOOK.md
test -s docs/maintenance/check_docs.py
```

## Related pages

- [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) — lifecycle,
  metadata, citation rules
- [DOCUMENTATION_CONTRIBUTING.md](../developer_guides/DOCUMENTATION_CONTRIBUTING.md)
  — author workflow
- [CURRENT_STATE_BASELINE.md](CURRENT_STATE_BASELINE.md) — inventory evidence
- [DRIFT_AND_CLAIM_MATRIX.md](DRIFT_AND_CLAIM_MATRIX.md) — claim-level drift
- Future: `QUALITY_REPORT.md`, `RELEASE_EVIDENCE.md`, maintenance README
  (owned by later tasks)

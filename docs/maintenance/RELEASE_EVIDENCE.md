# Documentation release evidence (program wave)

| Field | Value |
| --- | --- |
| Interface | `DocumentationReleaseEvidence@1` |
| Task | `IPFSDOC-098` |
| Status | `evidence` |
| Owner | release-docs / documentation-governance |
| Source of truth | This file; bound artifacts under `docs/maintenance/`; root `mkdocs.yml`; git identity below |
| Last verified | 2026-08-04 |
| Audience | release reviewer, maintainer, agent, program owner |
| Depends on | `IPFSDOC-096`, `IPFSDOC-097` (and child goals they close over) |
| Companion | [SITE_BUILD_AND_NAVIGATION.md](SITE_BUILD_AND_NAVIGATION.md), [README.md](README.md), [QUALITY_REPORT.md](QUALITY_REPORT.md), [EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md) |
| Measured at (UTC) | `2026-08-04T00:03:11Z` |
| Worktree commit (`HEAD`) | `e2790eb5fa2208d409866559bb9fb24bda62b321` |
| Worktree tree (`HEAD^{tree}`) | `ed2e0c8b267dac24cf72a91cddacefda55c517cc` |
| Supervisor tree_id (packet) | `e2790eb5fa2208d409866559bb9fb24bda62b321` |
| Branch | `implementation/ipfsdoc-098-f567e338a4d8-attempt-1-1785801616` |
| Package | `ipfs_datasets_py` **0.2.0** (`requires-python >=3.12`) |
| Measurement Python | `Python 3.12.3` (`Linux 6.17.0-1014-nvidia`) |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-098-f567e338a4d8` |

## Purpose

Bind **root release evidence** for the IPFS Datasets documentation refresh wave
to the **current commit/tree**, every available child goal/task receipt, quality
and example reports, claim-level P0/P1 disposition, known limitations, and
reviewer disposition.

This file is the terminal evidence artifact for **IPFSDOC-098**. It does **not**
by itself claim that the program root goal (`IPFSDOC-G000` / `IPFSDOC-G112`) is
complete.

---

## 1. Tree identity (authoritative binding)

```bash
git rev-parse HEAD
# e2790eb5fa2208d409866559bb9fb24bda62b321

git rev-parse 'HEAD^{tree}'
# ed2e0c8b267dac24cf72a91cddacefda55c517cc

git log -1 --format='%H %ci %s'
# e2790eb5fa2208d409866559bb9fb24bda62b321 2026-08-04 … Merge branch 'implementation/ipfsdoc-097-…'
```

| Field | Value |
| --- | --- |
| **Commit** | `e2790eb5fa2208d409866559bb9fb24bda62b321` |
| **Tree** | `ed2e0c8b267dac24cf72a91cddacefda55c517cc` |
| **Subject** | Merge branch `implementation/ipfsdoc-097-7a157599ef1d-attempt-1-1785801440` into `agent/ipfs-datasets-documentation-refresh-20260803` |
| **Immediate parents (wave tip)** | Includes merges for IPFSDOC-097 and IPFSDOC-096 (see §3) |

All **commands and results** in §4–§5 of this file and in
[SITE_BUILD_AND_NAVIGATION.md](SITE_BUILD_AND_NAVIGATION.md) were measured on
this commit/tree unless a child artifact states an earlier measurement commit
(historical receipts retain their original HEAD; they are **bound by inclusion**
on this tree as tracked files).

---

## 2. Reviewer disposition (program root)

| Question | Disposition |
| --- | --- |
| Is **IPFSDOC-098** evidence published? | **Yes** — this file + [SITE_BUILD_AND_NAVIGATION.md](SITE_BUILD_AND_NAVIGATION.md) |
| Did provisioned **`mkdocs build --strict`** succeed? | **No** — aborted with **567** warnings (see §5) |
| May the documentation **program root** be marked complete? | **No** |
| Zero **unresolved** claim-level P0 drift on nav-spine install/first-run paths after guide refresh tasks? | **Yes (re-checked on this tree for install/getting_started)** — see §6.1 |
| Zero unresolved corpus **validator** P0/P1 findings (`QUALITY_REPORT`)? | **No** — report still discloses large non-allowlisted error volume; see §6.2 |
| Example ledger unresolved P0/P1 fail rows on core offline tutorials? | **No fails** — core rows `pass` / `pass-labeled`; deferred gates labeled; see §6.3 |

### 2.1 Official program-root status

```text
PROGRAM_ROOT_STATUS = INCOMPLETE
REASON_PRIMARY      = provisioned_mkdocs_strict_build_failed
REASON_SECONDARY    = quality_report_still_discloses_P0_P1_validator_findings
BLOCKERS            = FU-001..FU-007 in SITE_BUILD_AND_NAVIGATION.md §5;
                      maintained-page metadata/link debt tracked in QUALITY_REPORT.md
```

**Reviewer instruction:** Reject any claim that “documentation refresh is done”
or that `IPFSDOC-G000` / `IPFSDOC-G112` is closed until:

1. `mkdocs build --strict` exits **0** on a recorded commit/tree, and
2. Release checklist in [README.md](README.md) §7.1 is re-run with explicit
   resolution or time-bounded exceptions for remaining P0/P1 on **maintained**
   surfaces.

IPFSDOC-098 itself is **satisfied as an evidence-publishing task** by recording
the above honestly without editing production code.

---

## 3. Child goals, tasks, and receipts bound on this tree

### 3.1 Goal tree (program map)

From `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH.objectives.md`
(read-only; not modified):

| Goal ID | Title | Closure role for release |
| --- | --- | --- |
| `IPFSDOC-G000` | Truthful, navigable, decision-rich documentation system | **Root — not complete** (this evidence) |
| `IPFSDOC-G010`–`G012` | Baseline, IA, governance | Baseline/maintenance peers present |
| `IPFSDOC-G020`–`G022` | Product entry / journeys | Install, getting started, user guide receipts |
| `IPFSDOC-G030`–`G072` | Architecture domains | Architecture hub + domain leaves (via wave commits) |
| `IPFSDOC-G080`–`G082` | Developer / agent enablement | Developer guide + guides receipts |
| `IPFSDOC-G090`–`G092` | API, examples, tutorials | API index, tutorials, example ledger |
| `IPFSDOC-G100`–`G102` | Operations / security | Routed from hubs; domain guides in tree |
| `IPFSDOC-G110`–`G111` | Navigation, glossary, legacy | Nav rebuild, glossary, disposition map |
| `IPFSDOC-G112` | Cross-guide validation and freshness closure | Quality report + this release evidence; **site strict still open** |

### 3.2 Completion receipts present under `docs/maintenance/completion_receipts/`

| Task | Title (short) | Receipt path | Receipt size (bytes) | Receipt HEAD (as recorded) |
| --- | --- | --- | ---: | --- |
| `IPFSDOC-064` | Capability matrix + changelog policy | [completion_receipts/IPFSDOC-064.md](completion_receipts/IPFSDOC-064.md) | 6653 | `37f99e8a2c6dff4ba58ebc9ac26507bb8b9ee60f` |
| `IPFSDOC-074` | Root developer guide | [completion_receipts/IPFSDOC-074.md](completion_receipts/IPFSDOC-074.md) | 10970 | `17f790ba0ee33e303fd58af81be6c4d4edf7c51e` |
| `IPFSDOC-090` | Architecture hub | [completion_receipts/IPFSDOC-090.md](completion_receipts/IPFSDOC-090.md) | 10048 | `2903f921968eb74af1894dd642a849a6d7dcfe4f` |
| `IPFSDOC-091` | Installation + configuration | [completion_receipts/IPFSDOC-091.md](completion_receipts/IPFSDOC-091.md) | 8817 | `3d90d03af4acd71c29d337c0fffcf3864639f7f2` |
| `IPFSDOC-092` | Getting started + user guide | [completion_receipts/IPFSDOC-092.md](completion_receipts/IPFSDOC-092.md) | 9971 | `f2337370a06831c9ebcff652afd0dcb98216f29e` |
| `IPFSDOC-093` | Glossary + authority vocabulary | [completion_receipts/IPFSDOC-093.md](completion_receipts/IPFSDOC-093.md) | 5824 | `37f99e8a2c6dff4ba58ebc9ac26507bb8b9ee60f` |
| `IPFSDOC-095` | Root documentation navigation | [completion_receipts/IPFSDOC-095.md](completion_receipts/IPFSDOC-095.md) | 10783 | `e06063ce27c0471a13e6656a3c7a14a450077e43` |

### 3.3 Wave tasks without separate receipt files (artifact is the evidence)

| Task | Evidence artifact on this tree | Notes |
| --- | --- | --- |
| `IPFSDOC-085` | [EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md) | Ledger; measured tree `5a155d8b3…` in artifact header |
| `IPFSDOC-094` | [LEGACY_DISPOSITION.md](LEGACY_DISPOSITION.md) | Disposition map |
| `IPFSDOC-096` | [QUALITY_REPORT.md](QUALITY_REPORT.md) | Full-tree validator report; Git HEAD `537b8db95…` at generation |
| `IPFSDOC-097` | [README.md](README.md) | Maintenance cadence and ownership |
| `IPFSDOC-098` | This file + [SITE_BUILD_AND_NAVIGATION.md](SITE_BUILD_AND_NAVIGATION.md) | Release evidence + site disposition |

### 3.4 Recent wave merge commits (git log on this worktree)

| Commit | Subject |
| --- | --- |
| `e2790eb5f` | Merge IPFSDOC-097 maintenance cadence |
| `66287d6a4` | IPFSDOC-097: Publish documentation maintenance cadence and ownership |
| `e54dafadd` | Merge IPFSDOC-096 quality report |
| `499843ba8` | IPFSDOC-096: Run cross-guide validation and publish the quality report |
| `a3da0284a` / `4ff47bdb2` | IPFSDOC-095 navigation rebuild |
| `e06063ce2` / `4e8b73137` | IPFSDOC-094 legacy disposition |
| `fbf49d558` / `3282ebbdc` | IPFSDOC-092 journeys |
| `f2337370a` / `10c28a412` | IPFSDOC-085 example verification ledger |

### 3.5 Maintenance peer inventory (bound by presence on tree)

| Artifact | Role | Size (bytes) |
| --- | --- | ---: |
| [CURRENT_STATE_BASELINE.md](CURRENT_STATE_BASELINE.md) | Inventory baseline | 28711 |
| [DRIFT_AND_CLAIM_MATRIX.md](DRIFT_AND_CLAIM_MATRIX.md) | Claim-level drift | 41892 |
| [SOURCE_AUTHORITY.md](SOURCE_AUTHORITY.md) | Authority order | 16488 |
| [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) | Page contract | 27242 |
| [COVERAGE_MATRIX.md](COVERAGE_MATRIX.md) | Coverage gaps | 26667 |
| [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | Package-local map | (present) |
| [VALIDATION_RUNBOOK.md](VALIDATION_RUNBOOK.md) | Offline validator runbook | 13265 |
| [check_docs.py](check_docs.py) | Validator implementation | (tool) |

Protected plan inputs under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*`
were **not** modified by this task.

---

## 4. Quality and example reports

### 4.1 Quality report (`IPFSDOC-096`)

| Field | Value |
| --- | --- |
| Path | [QUALITY_REPORT.md](QUALITY_REPORT.md) |
| Generator | `docs/maintenance/check_docs.py` v1.0.0 |
| **Command** (from report) | `python docs/maintenance/check_docs.py --root docs --report docs/maintenance/QUALITY_REPORT.md` |
| Report Git HEAD | `537b8db95fa5250d6a1fa1d52d7ba16cf9866311` |
| Files scanned | 1570 |
| Errors | **2768** |
| Warnings | 7 |
| Allowlisted | 1926 |
| P0 (authority/entry heuristic) | **17** |
| P1 (tree debt heuristic) | **2751** |
| Network | none |
| Side effects | Report write only; no `site/` deletion |

**Result interpretation:** The quality gate is **disclosed**, not green. Report
publishing uses fail-on-never policy so the artifact can ship with open
findings. This is **not** zero unresolved validator P0/P1.

P0 samples retained in the report include entry/spine metadata gaps (some may
have been improved on later commits — re-run `check_docs.py` before any future
“green” claim) and at least one anchor issue on `docs/faq.md`.

### 4.2 Example verification ledger (`IPFSDOC-085`)

| Field | Value |
| --- | --- |
| Path | [EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md) |
| Measured tree (ledger header) | `5a155d8b39ea12d505d4c313859dac150c6e6ebb` |
| Core offline rows | EV-CORE-001…004 → **pass-labeled** (exit 0) |
| Supporting hygiene | tutorial `python_syntax` → **pass** |
| Fail rows (core offline) | **none** |
| Deferred provisioned gates | IPFS daemon, live MCP HTTP, hub downloads, external provers — **labeled**, not claimed pass |

**Result:** No unresolved **fail** on maintained core offline tutorials. Labeled
mock/unavailable/fallback outcomes are **not** production success claims.

### 4.3 Offline release checklist status ([README.md](README.md) §7.1)

| # | Check | Status on this evidence set |
| --- | ---: | --- |
| 1 | Validator / quality report | **Disclosed** with open errors — not “green enough” without exceptions |
| 2 | Claim drift matrix | Spine install/Python/extras **repaired in guides** (§6.1); matrix file still historical snapshot |
| 3 | Example ledger | Core offline **pass-labeled**; deferred gates explicit |
| 4 | Install/entry vs packaging | **Aligned** on current `installation.md` / `getting_started.md` (spot-check) |
| 5 | API freshness | Domain maps present; generated dumps still in MkDocs nav (GAP-MK-004) |
| 6 | Architecture/ADR index | Architecture hub + ADR README present |
| 7 | Legacy disposition honesty | [LEGACY_DISPOSITION.md](LEGACY_DISPOSITION.md) published |
| 8 | Coverage gaps | [COVERAGE_MATRIX.md](COVERAGE_MATRIX.md) retained; P0 gaps not silently closed |
| 9 | Exception register | No formal exception rows opened in this task for remaining validator P0/P1 |
| 10 | Tree binding | **This file** binds commit/tree |

---

## 5. Provisioned site build — command and result

Full procedure and gap analysis:
[SITE_BUILD_AND_NAVIGATION.md](SITE_BUILD_AND_NAVIGATION.md).

| Field | Value |
| --- | --- |
| **MkDocs version** | `1.6.1` (isolated venv under checkpoint) |
| **Strict command** | `mkdocs build --strict` |
| **Strict result** | **FAIL** — `Aborted with 567 warnings in strict mode!` |
| **Strict started (UTC)** | `2026-08-04T00:01:29Z` |
| **Strict commit/tree** | `e2790eb5f…` / `ed2e0c8b2…` |
| **Warning breakdown** | 5 README/index exclusions + 562 missing doc-link targets |
| **Non-strict command** | `mkdocs build` |
| **Non-strict result** | **PASS** (exit 0), built in 13.66s, 1952 files / ~149M `site/` (ephemeral) |
| **Sphinx product-wide** | N/A — TDFOL-only; not re-run |
| **Root complete?** | **No** (strict failure is a hard blocker) |

Checkpoint logs:

- `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR/build_logs/mkdocs_strict.log`
- `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR/build_logs/mkdocs_nonstrict.log`

---

## 6. P0 / P1 drift disposition

### 6.1 Claim-level matrix (`IPFSDOC-002`) vs current spine guides

[DRIFT_AND_CLAIM_MATRIX.md](DRIFT_AND_CLAIM_MATRIX.md) recorded **8 P0** and
**18 P1** claims at measurement time on an earlier tree. Downstream guide tasks
were expected to repair the spine.

**Re-check on release tree `e2790eb5f…` (read-only spot-check):**

| Historical P0 cluster | Current evidence | Disposition |
| --- | --- | --- |
| Python 3.7 / 3.9 floors on install | `docs/installation.md` states **Python 3.12+** only | **Resolved on page** |
| Wrong extras (`vector`, `graphrag`, `webarchive`, `theorem_proving`) | Install documents real keys (`vectors`, `knowledge_graphs`, `scraping`, `theorem-provers`) + invalid-name table | **Resolved on page** |
| Getting-started wrong extras / Python | Aligned with packaging; warns against nonexistent names | **Resolved on page** |

**Remaining claim-level work (not zero across whole matrix):** secondary P1
import/command rows in the matrix may still apply to pages not fully rewritten;
the matrix document itself is a **dated inventory** and should be refreshed in a
future governance pass. For **nav-spine install/first-run P0 claims**, current
guides match packaging.

### 6.2 Validator P0/P1 (`QUALITY_REPORT`)

| Priority | Count (report) | Unresolved? |
| --- | ---: | --- |
| P0 | 17 | **Yes** (as of report generation; treat as open until re-run is green or excepted) |
| P1 | 2751 | **Yes** (large tree debt, much of it non-spine) |

**Release rule:** Do **not** assert “zero unresolved P0/P1 drift” for the
**validator corpus** on this wave. Assert only: findings are **published**,
spine claim P0s for install/Python/extras are **rewritten**, and allowlists were
not expanded to hide maintained-page debt.

### 6.3 Example ledger P0/P1

| Class | Status |
| --- | --- |
| Core offline tutorial **fail** | **None** |
| Deferred external gates | Labeled `deferred` — not silent success |
| Marketing-shaped unverified rows | Explicitly non-authoritative |

---

## 7. Known limitations

| ID | Limitation | Impact |
| --- | --- | --- |
| L-001 | `mkdocs build --strict` **fails** (567 warnings) | Blocks program-root complete |
| L-002 | MkDocs nav is **7 leaves** over **1572** Markdown files | Site graph ≠ full corpus; hubs in git still primary for deep routes |
| L-003 | API nav promotes **generated dumps** over domain maps | Risk of authority inflation if readers stop at MkDocs nav |
| L-004 | Out-of-`docs_dir` links (repo root, package-local) break MkDocs resolution | Strict warnings on spine pages |
| L-005 | Quality report HEAD is **earlier** than this release commit | Counts may drift; re-run before claiming green |
| L-006 | Example ledger HEAD is **earlier** than this release commit | Re-validate spine tutorials on release cut if required by policy |
| L-007 | Drift matrix is a **snapshot**; not auto-updated after every guide PR | Use live guides + packaging as authority for install claims |
| L-008 | Sphinx/TDFOL not re-built this run | Domain-only; optional |
| L-009 | Live network / IPFS / MCP HTTP / external provers **not** exercised | Per example deferred gates |
| L-010 | `site/` not gitignored; generated HTML not retained in worktree after measurement | Hygiene follow-up FU-007 |
| L-011 | No CI job enforces MkDocs strict today | Regression risk until FU-006 |
| L-012 | Dual packaging story (pyproject vs setup.py extras) still requires careful wording | Install guide documents pyproject-first |

---

## 8. Separately owned follow-ups (no production edits here)

See [SITE_BUILD_AND_NAVIGATION.md](SITE_BUILD_AND_NAVIGATION.md) §5 for the full
table. Summary for reviewers:

1. Declare MkDocs install surface; add CI `mkdocs build --strict`.
2. Add `exclude_patterns` and/or retarget build set away from archive noise.
3. Fix or policy out-of-docs links from maintained hubs.
4. Retarget MkDocs API nav to maintained domain maps.
5. Re-run `check_docs.py` and close or exception remaining **maintained** P0/P1.
6. Gitignore `site/`.

---

## 9. Explicit non-claims

This release evidence does **not** claim:

- That `IPFSDOC-G000` or `IPFSDOC-G112` is complete.
- That the documentation corpus is free of validator errors.
- That non-strict MkDocs success equals release readiness.
- That deferred external example gates passed.
- That generated optimizer dumps are public API contracts.
- That production code, packaging, or CI were changed by IPFSDOC-098.

---

## 10. Acceptance mapping (IPFSDOC-098)

| Acceptance requirement | Satisfied by |
| --- | --- |
| MkDocs/Sphinx/navigation configuration gap | [SITE_BUILD_AND_NAVIGATION.md](SITE_BUILD_AND_NAVIGATION.md) §§1–2 |
| Exact provisioned strict-build procedure and result | SITE_BUILD §3–§4; this file §5 — **strict FAIL** |
| Separately owned root config/CI follow-up | SITE_BUILD §5; this file §8 |
| No production code edits | Allowed paths only; protected plans untouched |
| Bind commit/tree | §1 |
| Every child goal/task receipt | §3 |
| Quality / example reports | §4 |
| Zero unresolved P0/P1 drift | §6 — **claim-spine install P0 resolved; validator P0/P1 not zero; example fails zero** |
| Known limitations | §7 |
| Reviewer disposition | §2 — **program root INCOMPLETE** |
| Do not mark root complete without successful provisioned site build | §2.1 — root **not** complete |

---

## 11. Validation commands (task gate)

```bash
test -s docs/maintenance/SITE_BUILD_AND_NAVIGATION.md \
  && test -s docs/maintenance/RELEASE_EVIDENCE.md \
  && rg -n 'commit|tree|child|command|result|MkDocs|limitation|review' \
       docs/maintenance/RELEASE_EVIDENCE.md
```

Expected: both files non-empty; `rg` matches sections for commit/tree binding,
child receipts, commands/results, MkDocs gate, limitations, and reviewer
disposition.

---

## 12. Document control

| Item | Value |
| --- | --- |
| Produced by | `IPFSDOC-098` |
| Track | documentation-release |
| Attempt | 1 |
| Checkpoint | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` (empty valid prior; venv + build logs written) |
| Next action for program close | Land FU-* config/CI fixes → re-run strict MkDocs → re-run quality report → update this file with **PASS** and only then mark root complete |

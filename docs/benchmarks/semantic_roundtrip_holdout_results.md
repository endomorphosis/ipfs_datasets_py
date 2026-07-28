# Semantic round-trip holdout remeasure results

**Interface:** `EvalRepairMatrixReport@1`  
**Schema:** `ipfs-datasets.semantic-roundtrip-holdout-remeasure.v1`  
**Task:** PLAT2-060  
**Report CID:** `baguqeeraupu46elxeoebbowyzawfytlueifxzv7hywdxkg6nzas2b4pef2ja`  
**Promotion decision CID:** `baguqeeracs6gvtpumpn43ixtmi5eacit7gxuoiz5rrc4inxwd7ryjw46ks6q`  
**Access ledger CID:** `baguqeeraymcdbko5peokdyicgbunpycrawxgvrscvuzq6ndxfaixrsioselq`  
**Captured:** 2026-07-28T08:58:44.684+00:00

This receipt is the **one-shot** PLAT2-060 blind-holdout evaluation under
a single path-free append-only access grant. Frozen baseline and candidate
ran on identical blind cases under isolated namespaces with preregistered
per-case-first paired bootstrap.

## Operator recovery note

The supervisor discarded the worktree after validation (54 passed) before merge.
Public bodies were recovered as follows:

| Artifact | Recovery |
| --- | --- |
| `holdout_evaluation.py` + tests | Landed from session (commit on benchmark branch) |
| Access ledger | Regenerated with **matching** `ledger_cid` (no re-score) |
| Remeasure / decision / results | Session-attested summary envelope (full per-case tables not recoverable without forbidden re-run) |

Session: `019fa7e5-518f-7df1-8274-c56a759efb53`. Blind holdout was **not** re-run.

## Decision

| Field | Value |
| --- | --- |
| Outcome | **promotion_declined** |
| Production promotion authorized | **False** |
| Mean Δ e2e (candidate − baseline) | **0.0** |
| Baseline mean e2e | **0.043055555667** |
| Candidate mean e2e | **0.043055555667** |
| E2e CI high &lt; 0 | **False** (high = 0.0) |
| Noninferiority (UCB ≤ margin) | **True** |
| Full gates pass | **False** (`source_copy_exclusion` on `blind_t1_retention_window`) |
| Pilots non-regressed (mean e2e 0.0) | **True** |
| Blind case count | **12** |
| Named next residuals | **6** (seed a new board only with a fresh blind population) |
| Selected production arm | `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` |

Promotion rule (fail-closed): **true only if** e2e bootstrap CI high &lt; 0 **and**
full selection gates pass (and pilots remain non-regressed); otherwise **false**.

## Access ledger

- Interface: `HoldoutAccessAudit@1`
- Events: `access_granted`, `manifest_released`
- Single-use: **True**
- Tuning permitted: **False**
- Path-free: **True**
- Ledger CID: `baguqeeraymcdbko5peokdyicgbunpycrawxgvrscvuzq6ndxfaixrsioselq`

## Immutable prior reports

The immutable 2026-07-27 replacement promotion report is **not** rewritten:

- Replacement report CID: `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga`
- Path: `docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json`

Pre-oneshot snapshots (if present) are preserved as
`*.pre_oneshot_snapshot.json` and are **not** authoritative for PLAT2-060.

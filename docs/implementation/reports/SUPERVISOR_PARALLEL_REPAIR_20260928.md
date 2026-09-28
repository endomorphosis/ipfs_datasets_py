# Parallel supervisor repairs, 2026-09-28

Two strict-roundtrip goals were repaired in isolated worktrees and validated
before this tree was updated. The census and goal bundles used to feed later
machines are already described in `SPAN_CENSUS_DATASET_HANDOFF_20260928.md`.
This note records the repairs that landed and the supervisor behavior they
depend on.

## What completed

| Task | Sentence family | Validation |
|---|---|---|
| `AFTD-817b9bac3966fbc1e819` | "when compared with" stays on the duty | source replay passed |
| `AFTD-e3b018a00ef13c0c927c` | strict round-trip of its sealed packet | source replay passed, 133 regression tests |

Both receipts use gate `source_replay_not_legal_equivalence`. `admitted` is
false. `formalized` is false. The edits are in the parser, formula builder,
canonical compiler, canonical decompiler, and modal decompiler, plus one
regression test per task under `tests/unit/logic/autoformal_repairs/`.

The snapshot that first contained the commits is
`/tmp/span-joint-parallel-run/runtime/repair-repository` on
`autoformal-candidate` (`572935fb0`, then `a8dafc66e`). Those commits are not
the published history. The validated file bytes are what this branch contains.

## Why the first parallel attempt failed

Validation launched a sealed Python memfd at `/proc/self/fd/N`. The child did
not receive that descriptor, so it exited 75 with `FileNotFoundError` before
`validate_autoformal_repair.py` ran. The portal recorded
`portal_provider_failed`. Accelerate `7adfbfc54` passes the receipt-owned
descriptors into the launcher self-test, the validation command, and the
dependency probe.

A Docker Codex-fallback route can leave the provider command as
`docker create`. Create prints a container id and exits 0 without running
Grok. The provider now attaches that container. Operator repair notes are
sealed to the DuckDB task cid, not the attempt-specific portal cid. An empty
provider patch can still render untracked additions. The exact autoformal
validator command is dependency-neutral, so the `@3` project contract does not
block it.

## What this does not do

No statute was admitted. `lake build Legal` was not the completion gate. The
full United States Code corpus was not ingested. The pinned autoencoder
checkpoint was not replaced. Other worktrees and unrelated branches were not
merged.

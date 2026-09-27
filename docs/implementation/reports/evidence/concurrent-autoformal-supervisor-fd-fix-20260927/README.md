# Sealed launcher fix and planned fifth supervisor smoke

The published accelerator fix is commit [`7adfbfc548baaaf7ca86cf70b18ec7effb71ad82`](https://github.com/endomorphosis/ipfs_accelerate_py/commit/7adfbfc548baaaf7ca86cf70b18ec7effb71ad82), based on `07804e0c057c884c6d9cc4df8361ca4b3a4e8e5a`. It adds five lines across two production files. The published file bytes match the qualified candidate exactly; see [publication receipt](root-publication/receipt.json), [candidate patch](candidate.patch), and [candidate manifest](candidate-manifest.json).

Native attempt R4 stopped before either training or span conversion began: its dependency probe tried to execute the sealed `/proc/self/fd` launcher without inheriting its descriptors and returned `FileNotFoundError`. The empty interpreter field in the failure receipt did not establish that a system Python was missing. See the retained [R4 Portal events](../concurrent-autoformal-supervisor-r4-20260927/portal-events.jsonl).

The fix passes only `launcher_receipt.inherited_fds` into the dependency-probe subprocess and the daemon's launcher self-test and actual validation subprocess. The helper defaults to an empty tuple for ordinary callers. Both production launcher contexts and all three first-hop launches were reviewed. Default `close_fds=True`, sealed interpreter/Ruff identities, descriptor lifetime, output/time bounds, secret scrubbing, and validation policies remain intact. No installation or validation-profile change was used.

## Focused qualification

These are local subprocess and unit checks, not a successful native supervisor smoke. [qualification.json](qualification.json) records all outcomes, including failures. The focused-test attempt labels below are separate from native R1–R5.

| Focused attempt | Result | Wall time | Evidence |
| --- | --- | --- | --- |
| 1 | Collection failed; no test cases ran. The unchanged upstream preflight test module imports absent `MAX_DEPENDENCY_PREFLIGHT_PROJECTION_BYTES`. | 30.276 s outer | [Log](collection-failed-r1/focused-tests.log), [receipt](collection-failed-r1/bounded-tests-receipt.json) |
| 2 | 12 passed, 1 failed. Selected preflight test definitions were copied unchanged into a private module with only necessary imports and relocated `REPO_ROOT`. The failure was a stale ZIP-loader fixture. | 98.09 s pytest; 98.626 s outer | [Log](focused-r2/focused-tests.log), [receipt](focused-r2/bounded-tests-receipt.json), [extraction provenance](focused-r2/test-extraction.json) |
| 3 | The one failed ZIP case passed after binding `module.__spec__.loader` to the same real `zipimporter` already assigned to `module.__loader__`. Every assertion and all product bytes remained unchanged. | 1.28 s pytest; 15.765 s outer | [Log](focused-r3/focused-tests.log), [receipt](focused-r3/bounded-tests-receipt.json), [fixture correction](focused-r3/zip-fixture-correction.json) |

This qualifies 13 distinct cases. The actual non-dumpable-parent dependency-probe and daemon subprocess regressions passed, including secret scrubbing. The ordinary helper/output limit, sealed descriptor cleanup, five accepted Ruff spellings, rejection of forged/noncanonical Ruff execution, launcher exec-denial classification, and sealed-ZIP source delivery were also checked. These runs had a 240-second outer bound, 150 MB temporary-output bound, two CPUs, offline settings, and bytecode writes disabled. No temporary fixture file bytes remained afterward; the largest sampled fixture footprint was 743 bytes. No full-suite or non-Linux execution is claimed.

[Source provenance](source-provenance.json) compares 110 imported source/test files directly against exact upstream commit `07804`: 108 match unchanged and exactly two are the reviewed production candidates. There was no unexpected source drift. Both complete original test modules are retained under [original-tests](original-tests/). Archived runners retain their original execution paths; they record how these tests ran, rather than providing a relocated turnkey runner.

## Intended R5 retry

[retry-intent.json](retry-intent.json) records a pending fresh dependency export (`capture-r3`) of the published accelerator commit and the intended native `capture-r5` run. The canonical datasets compiler/parser tree remains `/home/barberb/lift_coding/external/ipfs_datasets`; accelerator source selection must be explicit and bound to the new export. The root process will add the final dependency manifest, frozen harness/binding evidence, and resource admission before execution.

The retry is intended to run the real deterministic supervisor lifecycle and, if its native gates pass, exercise bounded autoencoder training concurrently with span compiler/decompiler checks. Compiler/decompiler roundtrip checks are not compiler/decompiler training. No training execution, span-conversion success, overlap, bridge timing, accepted update, Hugging Face upload, or native completion is established by this preparation bundle. No Lean admission or federal-law formalization is claimed; the Constitution remains unformalized.

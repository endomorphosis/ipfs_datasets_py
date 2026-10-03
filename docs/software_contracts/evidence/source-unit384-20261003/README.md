# Source-unit384 development evidence (2026-10-03)

This package retains actual component controls for the additive shared-parent
Source384 function-unit adapter and the semantic scanner's dot-prefixed filename
namespace repair. The source repository is the isolated datasets worktree.

The corrected CPU run passed **48 tests in 10.57 seconds**, including the real
pinned checkpoint/GTE subprocess, historical replay, current-source refusal,
malformed-map controls and unchanged legacy formula extraction tests. A separate
scanner run passed **31 tests in 1.28 seconds**. There are 79 distinct passing
controls; earlier attempts are not added to that count.

The initial invocation omitted `CUDA_VISIBLE_DEVICES` and had 24 passing tests,
one deselection, and 23 legacy fixture CUDA OOM setup errors in 4.41 seconds.
`initial-omitted-cuda-tests.log` is the complete 42,101-byte command output
recovered from the retained execution event. `test-commands.json` records the
exact commands, statuses and event digests. No JUnit XML was requested for the
failed initial invocation; none has been synthesized.

`actual-native01/result.json` is the unchanged native owner result. Its original
73,909-byte Python module and other two declared fixture files are retained under
`actual-native01/fixture-repository`. Five functions were inventoried: four
received decoder candidates and one was explicitly deferred above 512 tokens.
Two candidates reported source-contract mismatch and two reported unsupported
source contracts. Every authority/training/promotion flag remains false, provider
calls are zero, and retention remains unknown. These controls do not establish
benchmark performance, successful formalization, a security proof, or peak-RSS
containment. The process-tree RSS guard is sampled and may overshoot.

`sources/` contains the three new owners, the scanner repair, all executed test
files, and the reused extraction helpers. The numerical result pins additional
shared runtime dependencies by hash; this is not an exhaustive runtime snapshot.
The numerical test preceded the scanner repair; its earlier scanner source is
retained separately under `sources-before-scanner-fix/`. The scanner suite tested
the repaired source. No checkpoint weights, local database, cache directory,
credentials, or unrelated session messages are included.

`qualification.json` records exact scope and test history. `manifest.json` is a
closed inventory of every other package file with its byte count and SHA-256.
The implementation API and limits are documented in
[the source-unit guide](../../CODEBASE_SOURCE_UNITS_384.md).

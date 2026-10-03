# Inference publication without training workspace imports

Source384 inference now stages its artifact through the existing shared Source384
owner. The former lazy import loaded model-generation training code, which loaded
the canonical proof-workspace guard and correctly refused the deployed checkout
without Git metadata. The helper keeps the same canonical JSON bytes, temporary
directory prefix, registry staging call and cleanup behavior. Model-generation
callers retain their compatibility wrapper. No training or proof guard is relaxed.

The shared helper is covered by the existing shared source producer hash. No new
runtime module or unpinned dependency is introduced. Current-source observations,
model/producer checks, operation attachment, replay validation, cancellation and
deadlines remain at the same boundaries.

Final datasets controls passed **43/43** in 33.12 seconds. They include five staging
and guard controls, actual pinned-checkpoint/GTE inference with training/proof
imports forbidden, source/report drift rejection, replay after closing and
reopening the native registry, and the existing training-generation/proof suite.
The actual inference fixture has five functions: four decode to unverified
candidates and one exceeds the GTE token limit. Two candidates fail open for
source-contract mismatch and two for unsupported source contracts. Model execution
and publication do not establish formalization correctness or proof authority.

The existing supervisor consumer suite passed **13/13** in 41.37 seconds on the
same datasets sources, including actual inference reaching planning/dispatch and
checkpoint drift rejection. Its raw controls are included; its source snapshots
and fresh Docker qualification belong to the separate consumer evidence package.
The final distinct count is 56, without counting repeated historical controls.

The initial five staging controls passed. A subsequent broader attempt passed 23
tests and failed 20 fixture setups because its explicit Lake path selected the
Elan launcher. The native owner returned `select_installed_native_lake_not_elan_shim`.
The final run uses the previously qualified installed Lake binary. No assertion
was removed or weakened. A test-owned reopened registry handle also gained correct
teardown. Exact earlier source snapshots, failed XML/logs and the failure receipt
summary are retained beside the final successful generation.

The originating Docker trace shows the worker had returned and output checks had
run before the import failure. It did not retain a committed inference artifact or
complete qualification receipt, so it cannot support independently verified output
counts or successful inference qualification. The diagnosis records that limit.
The host controls here are not a completed Docker run or a benchmark score.

`manifest.json` closes source/test snapshots, the implementation diff, executed
commands, raw logs/XML, producer and real asset hashes, reviews and small verdicts.
Weights, databases, benchmark corpus and full fixture outputs are excluded. Their
hashes and local references support binding, not reconstruction from absent bytes.
The training regression includes bounded fixture adaptation; inference itself
does not train. No checkpoint upload, model promotion or release occurs here.

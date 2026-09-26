# Invocation-local surface text reuse

The modal decompiler now reuses the fixed text-classification scan within one
target-reconstruction invocation. It preserves complete target content and
ordered phrase evidence. No bridge is removed, no vocabulary fallback is added,
and no training or admission criterion changes. Native training validation
remains deferred by the user. This working-tree change is not fully qualified:
the current typed-deontic pilot is below its unchanged historical threshold.

## Evidence and change

The [retained cold-target profile](autoencoder_cold_target_profile.md) identified
628 target surface-profile calls taking 1.6280 profiled seconds inside 58
reconstruction calls taking 6.5960 seconds. Both per-family renderers called the
same classifier again. These historical measurements identify duplicate work;
they are not a forecast of end-to-end savings for this change.
That instrumented subprofile also recorded adapter timeouts, so it is not a
complete five-bridge comparison baseline.

The [implementation](../../../ipfs_datasets_py/logic/modal/decompiler.py) extracts
only the long fixed-regex tail into `_typed_decompiler_text_surface_profiles`.
Its statements, patterns, order and labels are unchanged. Every profile call
still reads and cleans the document text, calls the dynamic heading helper,
checks the heading regex, calls the dynamic status helper, then classifies the
text captured before those helpers. Source-profile reads also remain dynamic.

One local `_SurfaceTextProfileMemo` lives inside each reconstruction call.
It retains one successful exact-string key of at most 65,536 characters and
an immutable tuple of at most 91 fixed labels. Changed text evicts the entry;
larger or custom inputs use the ordinary scan without rejecting the input.
Nothing is stored on a document, formula, shared target, checkpoint or database.
Reentrant calls receive separate memos and no cache survives normal return.

The private memo argument is passed only through the native helper functions.
Replaced helpers keep their previous arguments and call counts. Direct helper
calls remain uncached. Scanner, regex search and regex compiler identity/code
guards, plus the search default-flags guard, preserve fallback when those
callables are replaced after import. A search callable without a Python code
object is ineligible for reuse and does not prevent import. Dynamic metadata,
heading/status calls and their exception order
are not memoized. Failed scans do not populate the entry. Returned profile lists
are built independently, preserving ordered merging and deduplication.

The retained text bound is a cache bound, not a changed model context window.
Temperature, context settings, backend, prover flag, bridge names, sample-memory
policy and metric disk-cache settings are unchanged. This optimization does
not introduce cross-document semantic summaries or replace full shared targets.

## Qualification scope and remaining cost

The synthetic comparison uses directly constructed native IR fixtures and a
frozen complete pre-edit decompiler. It performs no parser-based sample
generation, autoencoder training, bridge evaluation or checkpoint substitution.
Complete ordered outputs must match, not merely counts, sets or loss values.

The [focused regression capture](../../../workspace/test-logs/federal-corpus-audits/surface-profile-text-reuse-20260925/focused-r2/focused-r2-receipt.json)
has 78 passes and one failure, with all 7,744 package sources unchanged during
the capture. All 48 new reuse cases pass, including full ordered output
comparisons against the frozen original function, nested invocations, dynamic
helper replacement, exception order and regex default-flag changes. The
remaining failure is the existing exact temporal-atom assertion: the parser
now emits `value="within 10 days"` instead of `value="10 days"`. That assertion
has not been weakened. The only edit to that gate test fixes temporary module
registration when loading JevOps' dataclass-bearing statement-lock module.
After review added two regex-hook compatibility cases and guards, the
[reuse-only capture](../../../workspace/test-logs/federal-corpus-audits/surface-profile-text-reuse-20260925/reuse-r3/reuse-r3-receipt.json)
passes **50/50**, with no skips, errors or failures, in 18.302 seconds including
the pytest wrapper. Its full package source, test-input and protected-artifact
guards pass. It does not rerun or supersede the failed semantic pilot.

The separate [semantic diagnostic](../../../workspace/test-logs/federal-corpus-audits/surface-profile-text-reuse-20260925/semantic-diagnostic-r1.json)
passes all three requested gates with parser-supplied string atoms, including
empty-vocabulary abstention, `within_duration` remaining non-renderable, and
the integer minimum-duration threshold. It also executes the actual five-case
typed-deontic pilot: forward and end-to-end scores are **0.9116666666**, below
the historical **0.915**, while cycle remains **1.000**. Its source guard
passes. These are semantic checks, not admissions or training measurements.

The typed-deontic pilot does not call the modified modal decompiler. The
[read-only attribution](../../../workspace/test-logs/federal-corpus-audits/surface-profile-text-reuse-20260925/pilot-attribution.json)
compares the historical per-case report and attributes the score changes to
three lost typed exception atoms, partly offset by an improved incident
deadline. The concurrently edited parser's `_keep_without_phrase` removes
`without` and `except` entries from exception slots and appends their phrases
to action/object text. Preserving the words in object text does not preserve
the pilot's typed exception slots. This change does not edit that parser,
change the gold cases or lower the required score. The historical fixture is
byte-identical, but the historical benchmark harness has a different recorded
content identity; this read-only attribution is not a fresh same-harness
baseline/candidate comparison. Full semantic qualification remains outstanding.

The earlier [combined capture](../../../workspace/test-logs/federal-corpus-audits/surface-profile-text-reuse-20260925/combined-r1-receipt.json)
is retained as failed: 174 passed, 13 pre-existing skips and seven fixture
setup errors; the parser also changed during execution. It is not combined
qualification. The fixture setup error was repaired before the focused run.
The [first synthetic profile](../../../workspace/test-logs/federal-corpus-audits/surface-profile-text-reuse-20260925/surface-profile-receipt.json)
is also retained as failed: its measured calls matched complete ordered
outputs, but the profile and untimed call-count audit took 65.928 seconds,
exceeding its 60-second budget. Its reservation is retained under the existing
resource policy. It is not a qualified speed result.

The [second synthetic profile](../../../workspace/test-logs/federal-corpus-audits/surface-profile-text-reuse-20260925/profile-r2/surface-profile-receipt.json)
passes within the same 60-second budget (28.804 seconds including output and
call-count audits). It retains the same four synthetic native IR documents,
warmups, complete output comparisons and three alternating AB/BA/AB pairs.
It reduces timed reconstruction repetitions from four to one per fixture per
arm and audits reconstruction helper counts only; decoded output parity is
still checked on every call. It preserves the failed first run separately.

| Synthetic operation | Baseline median wall time/call | Candidate | Reduction |
|---|---:|---:|---:|
| Target reconstruction | 200.167 ms | 167.341 ms | 16.40% |
| Full modal decode | 534.057 ms | 498.724 ms | 6.62% |

Each phase has 12 measured calls per arm across four fixtures. These are
constructed inputs, not US Code or Constitution spans. The retained dynamic
source/target profile, heading and status helper counts are identical. The
fixed text tail runs four times for four reconstruction invocations instead
of being repeated inside 58 target-profile calls. All 7,744 package sources
and protected anchors remain unchanged during this profile; its own resource
reservation is released after durable evidence is written.

No bridge names are invoked, no bridge evaluation runs, and no
`legal_ir_target_count` is claimed. Provers are disabled, metric disk cache is
set to `0`, worker settings are `1`, and the diagnostic reserves one CPU and
1,024 MiB. Regex/module caches are explicitly warmed; OS caches are uncontrolled.
This is not a cold parser or legal-IR evaluation measurement. No new wall time
per corpus span or bridge-on evaluate is established while native validation
is deferred. Whole-process peak RSS is 888,811,520 bytes, which cannot be
attributed to either arm or used as a memory-saving claim.

The parser changed again after the passing reuse/profile captures. Their
captured source identities remain evidence for those runs; they do not qualify
the subsequently edited package. The before and candidate modal decompiler
bytes are retained separately for review. No repeated native attempt is
started to chase concurrent changes.

This removes repeat classification, while dynamic heading/status handling,
source-profile checks and all slot emission still run at their original
positions. The memo adds a short-lived text comparison and small dispatch
checks; it is therefore useful only where repeated scans outweigh that cost.
Fresh native complete-target preparation and bridge-on evaluation remain
necessary before claiming corpus-scale or training latency improvements.

Producer source identities change with the decompiler. Historical target
bundles are not silently reused under a different producer identity; existing
provenance guards remain in force. No HACC or `hallucinate_app` copy is edited.

The Constitution remains unformalized and no span becomes `roundtrip_ok`.
Compiled/decompiled text, targets, optimizer metrics, NCA cells and database
rows remain separate from admission. Only `lake build <Lib>` supplies a Lean
admit; this change runs no Lake admission.

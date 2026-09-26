# Full-report hydration: bounded historical profile

Diagnostic, 2026-09-25. The [receipt](evidence/autoencoder_control_plane_plan/report-hydration-profile-20260925.json)
passes exact decoding checks for one historical report. It does not qualify a
native daemon, measure bridge generation, establish a speedup, or admit law.

The [script](../../../scripts/ops/legal_ir/profile_report_hydration.py) selects
only `us-code-22-4021a-fce42ca5c6a35f9d` from the sealed r3 full-report bundle.
It pins the failed historical receipt, input artifacts, bundle SHA/size and
critical decoder/native-class sources. The ordinary current daemon session
first rejects the stale artifact with exactly
`report configuration/provenance mismatch`. Only the low-level forensic reader
then receives the recorded historical configuration; no production guard is
changed. Network access is denied and no model, checkpoint, target producer,
evaluator or training method runs.

The historical producer differs in `logic/autoformal/repair_intake.py`; current
source stayed unchanged during this diagnostic. The protected restart12 hash
was rechecked unchanged. The 180-second child limit was retained, with one
attempt and no retry. Complete parent time was 36.707 seconds including
instrumentation and independent audits.

| Scope | cProfile wall seconds | Interpretation |
|---|---:|---|
| Select, decode and verify one report/target | 13.7543 | Includes the complete existing bound and target checks |
| Reencode decoded report | 10.9223 | Separate exact wire roundtrip audit |
| Recompute old target-codec identity | 3.4304 | Separate target-integrity audit |
| Independent native graph fingerprint | 5.8706 | Separate field/type/order/alias audit |

Selection decompressed exactly one 63,159,922-byte encoded report. Its derived
old-codec target is 64,868,307 bytes. Wire bytes/SHA, target bytes/SHA, all native
fields/types/order/compound aliases and the shared report/target document
identity matched the historical evidence exactly. Neither size is an RSS
estimate. The existing 64 MiB shard and 256 MiB graph/selection limits remain
unchanged.

Within selection, `report_from_bytes` accounted for 10.9130 cumulative seconds.
Its 318,053 `_node_limits` calls accounted for 5.7088 seconds, including
2,674,971 `_json` calls across the selection at 4.5165 seconds. Derived-target
validation took 2.6728 seconds. Positional shape expansion took 0.7533 seconds,
JSON parsing about 0.3070 seconds, and reading/decompression about 0.1231 seconds.
These nested cumulative figures must not be added together. cProfile changes
runtime cost; the numbers identify candidates for investigation, not native
wall-speed savings.

The same size-arithmetic work appears during encoding: `_node_limits` took
6.4927 cumulative seconds and `_json` ran 2,717,158 times. I/O and positional
decoding are therefore weaker first targets on this report than repeated
scalar/framing serialization used only to compute exact expanded sizes.

## Next bounded optimization experiment

Implementation update: the [exact size-accounting change](autoencoder_report_size_accounting.md)
now implements this experiment. It passes 396 focused checks and a source-stable
four-process same-artifact comparison. A subsequent native preparation was
invalidated by a separate source edit, so end-to-end daemon qualification
remains pending. The design below records the constraints used for the change.

Precompute the exact fixed framing sizes and consider an operation-local,
bounded cache of exact JSON byte lengths for repeated strings. Keep the existing
encoder as the source of each first-computed length. Do not approximate Unicode
escaping, change float/int/bool handling, pool arbitrary objects, or retain
source strings in a global cache. Unique strings and cache overflow must retain
the ordinary exact path.

Preserve every reference, native-field, depth, expanded-byte and target check.
In particular, a shared graph reference still contributes its expanded size
for each occurrence; caching a scalar length must not count an occurrence only
once. Test sizes against the original arithmetic for escaped/control/Unicode
strings, empty containers, repeated references, boundary-sized graphs and
existing rejected inputs. Preserve wire bytes and native object sharing.

If those checks pass, compare the same sealed bytes under original and changed
arithmetic in a forensic codec experiment with explicit source identities.
Only a fresh compatible bundle and complete cold/shared daemon comparison can
then establish a native benefit. Preparation and verification costs still
belong in the end-to-end result. This profile does not justify enabling report
reuse by default, reducing bridge names, using a stale training artifact or
moving the projection backend to CUDA.

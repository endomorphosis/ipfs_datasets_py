# Decoder conditioning and field-head rates

This evidence records 940 decoder-side optimizer updates over frozen source representations: three matched 4096D fits (200 each) and two matched 8D fits (170 each). No encoder or historical linguistic teacher is finetuned.

The native4096 source-scaled arm reaches exact reconstruction of both authored TRAIN clauses and has 18.6% lower final token CE than the matched unscaled arm. These two permission clauses differ only in object; they supply no held-out or full-family validation. Actual emitted rule IR is included in results.json under native4096.decoded_examples. Initial prior freezing performs worse, and the plateau scheduler never reduces its rate.

The 8D lower field-head rate reduces development CE but loses object fidelity and does not improve exact reconstruction. The unchanged selector retains the original parent. Larger 384D/768D checkpoints are preserved; an independent audit localizes their remaining errors in the already exposed style cohort.

Full predictions, trained head states, controls, exact source/recipe inventories, tests, independent saved-output reviews, native protocol evidence and resource receipts are in the split archive. No pretrained model weights are included. The manifest links the preceding published evidence for unchanged runtime dependencies and encoders. Concatenate archive_parts in listed order; verify every part and archive hash before extracting regular members into a fresh directory. Absolute original paths are provenance aliases, not extraction destinations.

Tests: 60 native conditioning/runner/regression controls and 30 8D controls pass. Independent saved-output checks do not reexecute the models. Timing scopes, worker counts, cache/prover flags and sample counts are explicit in results.json and the training guide.

No checkpoint is promoted. No Lake build or bridge-on evaluate is claimed. Context/output limits remain 512 and temperature 0. A compile, a decoder output, a lower loss or a database row is not an admit. Only lake build <Lib> can provide Lean admission. The Constitution remains unformalized.

# Semantic round-trip composition pilot

Status: **complete** — all 670 frozen coordinates have terminal evidence.

The run covers four deterministic cells once and 26 model-backed cells in five uncached repeats on each of the unchanged five pilot cases. Repeats are averaged within case before cases receive equal weight. Terminal failures remain in the denominator at loss 1.0.

## Decision

- Outcome: `no_eligible_composition`.
- Eligible arms: 0/30.
- Winner: none.
- Production promotion: not authorized by this pilot.

## Complete arm results

| Arm | Repeats/case | Success | Failure | Forward | Cycle | End-to-end | 95% CI | Gate eligible | Model calls | Wall seconds |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|---:|---:|
| `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` | 1 | 5 | 0 | 0.085000 | 0.003333 | 0.088333 | [0.038333, 0.136667] | no | 0 | 57.077588 |
| `typed_deontic__guided__no_repair__not_applicable__deterministic` | 1 | 0 | 5 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 22.477800 |
| `modal_spacy__no_guidance__no_repair__not_applicable__deterministic` | 1 | 5 | 0 | 0.167500 | 0.042500 | 0.203333 | [0.169167, 0.253333] | no | 0 | 90.352733 |
| `modal_spacy__guided__no_repair__not_applicable__deterministic` | 1 | 0 | 5 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 33.754888 |
| `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_direct` | 5 | 20 | 5 | 0.265000 | 0.255227 | 0.313333 | [0.069167, 0.669167] | no | 25 | 373.275894 |
| `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_symai` | 5 | 25 | 0 | 0.085000 | 0.147879 | 0.214167 | [0.090000, 0.329167] | no | 25 | 343.272788 |
| `typed_deontic__no_guidance__selective__not_applicable__deterministic` | 5 | 25 | 0 | 0.085000 | 0.003333 | 0.088333 | [0.038333, 0.136667] | no | 0 | 267.671567 |
| `typed_deontic__no_guidance__selective__not_applicable__leanstral_direct` | 5 | 20 | 5 | 0.265000 | 0.255227 | 0.313333 | [0.088333, 0.666667] | no | 25 | 373.418328 |
| `typed_deontic__no_guidance__selective__not_applicable__leanstral_symai` | 5 | 25 | 0 | 0.085000 | 0.147879 | 0.214167 | [0.097500, 0.329167] | no | 25 | 338.189988 |
| `typed_deontic__guided__no_repair__not_applicable__leanstral_direct` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 114.563227 |
| `typed_deontic__guided__no_repair__not_applicable__leanstral_symai` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 115.238631 |
| `typed_deontic__guided__selective__not_applicable__deterministic` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 116.998293 |
| `typed_deontic__guided__selective__not_applicable__leanstral_direct` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 125.738059 |
| `typed_deontic__guided__selective__not_applicable__leanstral_symai` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 118.018461 |
| `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_direct` | 5 | 25 | 0 | 0.167500 | 0.155833 | 0.310000 | [0.195833, 0.465833] | no | 25 | 422.302250 |
| `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_symai` | 5 | 20 | 5 | 0.347500 | 0.262500 | 0.399167 | [0.186667, 0.710000] | no | 25 | 437.588395 |
| `modal_spacy__no_guidance__selective__not_applicable__deterministic` | 5 | 25 | 0 | 0.167500 | 0.042500 | 0.203333 | [0.169167, 0.253333] | no | 0 | 454.727668 |
| `modal_spacy__no_guidance__selective__not_applicable__leanstral_direct` | 5 | 25 | 0 | 0.167500 | 0.155833 | 0.310000 | [0.195833, 0.465833] | no | 25 | 434.313562 |
| `modal_spacy__no_guidance__selective__not_applicable__leanstral_symai` | 5 | 20 | 5 | 0.347500 | 0.262500 | 0.399167 | [0.186667, 0.710000] | no | 25 | 442.063321 |
| `modal_spacy__guided__no_repair__not_applicable__leanstral_direct` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 171.727837 |
| `modal_spacy__guided__no_repair__not_applicable__leanstral_symai` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 168.425601 |
| `modal_spacy__guided__selective__not_applicable__deterministic` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 169.754168 |
| `modal_spacy__guided__selective__not_applicable__leanstral_direct` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 170.379988 |
| `modal_spacy__guided__selective__not_applicable__leanstral_symai` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 171.220453 |
| `model__not_applicable__always_on__direct__deterministic` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 50 | 749.925155 |
| `model__not_applicable__always_on__direct__leanstral_direct` | 5 | 15 | 10 | 0.692500 | 0.696667 | 0.699583 | [0.375833, 0.958750] | no | 70 | 1692.248699 |
| `model__not_applicable__always_on__direct__leanstral_symai` | 5 | 10 | 15 | 0.775000 | 0.728333 | 0.732500 | [0.392500, 1.000000] | no | 75 | 1193.292969 |
| `model__not_applicable__always_on__symai__deterministic` | 5 | 10 | 15 | 0.711333 | 0.674375 | 0.766875 | [0.506875, 1.000000] | no | 50 | 1147.300515 |
| `model__not_applicable__always_on__symai__leanstral_direct` | 5 | 20 | 5 | 0.595333 | 0.274375 | 0.634625 | [0.415625, 0.852500] | no | 75 | 2153.212159 |
| `model__not_applicable__always_on__symai__leanstral_symai` | 5 | 25 | 0 | 0.580788 | 0.590568 | 0.583667 | [0.359833, 0.807500] | no | 75 | 1926.580469 |

## Evidence and interpretation

- Scheduled: 670; terminal: 670; missing: 0.
- The source-copy, polarity, and full-coverage gates are selection constraints, not loss modifiers.
- Hammer/cvc5 and Lean receipts are post-hoc annotations of already-bound candidates; they do not alter scores or gates.
- Missing token counts remain explicitly missing. Local estimated monetary cost is retained separately from semantic quality.
- Frozen schedule CID: `baguqeerapukwubateif7weljbfoql6vnslpeki5awefxn4njl5a2ywbbebba`.
- Report CID: `baguqeerakqgerwv6npdlqpgrc3bjzuxqog3hiouey3c4giw5vkdgk2jhfbpq`.

The machine-readable report retains every terminal record, per-case and aggregate statistics, case-cluster uncertainty, cost missingness, gates, selection evidence, and provenance.

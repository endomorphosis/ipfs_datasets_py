# Semantic round-trip replacement composition results

Status: **complete** — all 670 frozen replacement coordinates have terminal, CID-addressed evidence.

The replacement run keeps the unchanged five pilot cases, failure loss 1.0, per-case-first aggregation, three semantic gates, one physical model slot, and the preregistered balanced uncached order.

## Decision

- Outcome: `exact_tie`.
- Eligible arms: 2/30.
- Winner: none.
- Production promotion: not authorized by this replacement pilot.

## Complete arm results

| Arm | Repeats/case | Success | Failure | Forward | Cycle | End-to-end | 95% CI | Gate eligible | Model calls | Wall seconds |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|---:|---:|
| `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` | 1 | 5 | 0 | 0.085000 | 0.003333 | 0.088333 | [0.038333, 0.136667] | yes | 0 | 50.462169 |
| `typed_deontic__guided__no_repair__not_applicable__deterministic` | 1 | 0 | 5 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.031330 |
| `modal_spacy__no_guidance__no_repair__not_applicable__deterministic` | 1 | 5 | 0 | 0.167500 | 0.053718 | 0.212308 | [0.177500, 0.257500] | no | 0 | 83.669173 |
| `modal_spacy__guided__no_repair__not_applicable__deterministic` | 1 | 0 | 5 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.046179 |
| `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_direct` | 5 | 5 | 20 | 0.800000 | 0.820000 | 0.820000 | [0.460000, 1.000000] | no | 45 | 429.292920 |
| `typed_deontic__no_guidance__no_repair__not_applicable__leanstral_symai` | 5 | 10 | 15 | 0.628333 | 0.629091 | 0.656667 | [0.296667, 1.000000] | no | 40 | 439.273673 |
| `typed_deontic__no_guidance__selective__not_applicable__deterministic` | 5 | 25 | 0 | 0.085000 | 0.003333 | 0.088333 | [0.038333, 0.136667] | yes | 0 | 267.408548 |
| `typed_deontic__no_guidance__selective__not_applicable__leanstral_direct` | 5 | 5 | 20 | 0.800000 | 0.820000 | 0.820000 | [0.460000, 1.000000] | no | 45 | 430.657702 |
| `typed_deontic__no_guidance__selective__not_applicable__leanstral_symai` | 5 | 10 | 15 | 0.628333 | 0.629091 | 0.656667 | [0.296667, 1.000000] | no | 40 | 440.125639 |
| `typed_deontic__guided__no_repair__not_applicable__leanstral_direct` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.164247 |
| `typed_deontic__guided__no_repair__not_applicable__leanstral_symai` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.163251 |
| `typed_deontic__guided__selective__not_applicable__deterministic` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.163572 |
| `typed_deontic__guided__selective__not_applicable__leanstral_direct` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.162260 |
| `typed_deontic__guided__selective__not_applicable__leanstral_symai` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.163916 |
| `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_direct` | 5 | 15 | 10 | 0.505833 | 0.463333 | 0.542500 | [0.215000, 0.870000] | no | 35 | 523.443398 |
| `modal_spacy__no_guidance__no_repair__not_applicable__leanstral_symai` | 5 | 10 | 15 | 0.652500 | 0.620000 | 0.672500 | [0.337500, 1.000000] | no | 40 | 535.419362 |
| `modal_spacy__no_guidance__selective__not_applicable__deterministic` | 5 | 25 | 0 | 0.167500 | 0.053718 | 0.212308 | [0.179808, 0.259808] | no | 0 | 412.164682 |
| `modal_spacy__no_guidance__selective__not_applicable__leanstral_direct` | 5 | 15 | 10 | 0.505833 | 0.463333 | 0.542500 | [0.215000, 0.870000] | no | 35 | 521.534243 |
| `modal_spacy__no_guidance__selective__not_applicable__leanstral_symai` | 5 | 10 | 15 | 0.652500 | 0.620000 | 0.672500 | [0.337500, 1.000000] | no | 40 | 537.625685 |
| `modal_spacy__guided__no_repair__not_applicable__leanstral_direct` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.170296 |
| `modal_spacy__guided__no_repair__not_applicable__leanstral_symai` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.169827 |
| `modal_spacy__guided__selective__not_applicable__deterministic` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.169632 |
| `modal_spacy__guided__selective__not_applicable__leanstral_direct` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.170832 |
| `modal_spacy__guided__selective__not_applicable__leanstral_symai` | 5 | 0 | 25 | 1.000000 | 1.000000 | 1.000000 | [1.000000, 1.000000] | no | 0 | 0.169439 |
| `model__not_applicable__always_on__direct__deterministic` | 5 | 15 | 10 | 0.689375 | 0.445000 | 0.659375 | [0.335000, 0.934375] | no | 75 | 1356.299692 |
| `model__not_applicable__always_on__direct__leanstral_direct` | 5 | 10 | 15 | 0.730000 | 0.680000 | 0.785000 | [0.495000, 1.000000] | no | 90 | 1090.557002 |
| `model__not_applicable__always_on__direct__leanstral_symai` | 5 | 5 | 20 | 0.830000 | 0.840000 | 0.850000 | [0.550000, 1.000000] | no | 75 | 906.666137 |
| `model__not_applicable__always_on__symai__deterministic` | 5 | 20 | 5 | 0.615875 | 0.257750 | 0.602375 | [0.320000, 0.870375] | no | 65 | 1557.847704 |
| `model__not_applicable__always_on__symai__leanstral_direct` | 5 | 5 | 20 | 0.840000 | 0.850000 | 0.890000 | [0.670000, 1.000000] | no | 80 | 1710.445869 |
| `model__not_applicable__always_on__symai__leanstral_symai` | 5 | 5 | 20 | 0.840000 | 0.850000 | 0.890000 | [0.670000, 1.000000] | no | 75 | 1348.568669 |

## Evidence

- Scheduled: 670; terminal: 670; missing: 0.
- The source-copy, polarity, and full-coverage gates are selection constraints and never modify semantic loss.
- Guided arms that remained unavailable are retained as typed terminal failures with loss 1.0 and zero model calls.
- Every report record retains candidate, semantic-record, replacement-coordinate, extended-record, artifact, arm, qualification, plan, and schedule CIDs.
- The external durable JSONL and metadata are bound by raw CIDs in the report and manifest; they are not copied into task outputs.
- Frozen schedule CID: `baguqeera7oabvqeuazsocfyzcthnuvia22rag6jcsjn7u4o7ibr5xig4r5ya`.
- Raw checkpoint CID: `bafkreifvag6edvwpgaon354vpq6m7ued6yiialxeuhpt7k2ob4fiysac34`.
- Report CID: `baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga`.

# Semantic logic round-trip pilot

Corpus: `5` cases, `24` adjudicated rules, CID `baguqeerahcfd4gby6nzstcnybokfnd4oeou6lcevjdvc5ry22xzvvtmjhrqq`.

Scores distinguish source→logic fidelity, logic→text→logic cycle consistency, and end-to-end fidelity. These are all-case means: failed or missing cases score zero. Higher is better.

| Arm | Executed | L1 coverage | L1+L2 coverage | Forward | Cycle | End-to-end | Arm-reported s |
|---|---:|---:|---:|---:|---:|---:|---:|
| cnl_v2 | 4/5 | 1/5 | 1/5 | 0.200 | 0.200 | 0.200 | 0.001 |
| dcec | 5/5 | 0/5 | 0/5 | 0.000 | 0.000 | 0.000 | 0.001 |
| leanstral_direct | 5/5 | 5/5 | 5/5 | 0.745 | 0.732 | 0.607 | 19.070 |
| leanstral_oracle_reverse | 5/5 | 5/5 | 5/5 | 1.000 | 0.573 | 0.573 | 14.004 |
| modal_regex | 5/5 | 0/5 | 0/5 | 0.000 | 0.000 | 0.000 | 6.600 |
| modal_spacy | 5/5 | 5/5 | 5/5 | 0.833 | 0.921 | 0.783 | 16.303 |
| spacy_leanstral | 5/5 | 5/5 | 5/5 | 0.650 | 0.642 | 0.485 | 28.873 |
| symai_forward | 5/5 | forward evidence | unsupported | 0.602 lexical recall | n/a | n/a | 15.239 |
| typed_deontic | 5/5 | 5/5 | 5/5 | 0.915 | 1.000 | 0.915 | 8.972 |

Interpretation constraints:

- SyMAI and direct Leanstral share the same one-slot model.
- Hammer/cvc5 and Lean validate exact canonical rule identities; they do not judge whether natural language was formalized correctly.
- Empty-IR identity is reported as a raw kernel result but never counts as benchmark-accepted equivalence.
- The pilot uses a closed atom vocabulary with distractors. It tests structure and scope, not open-world ontology induction.
- Realizers never receive the source. Source-overlap is a separate diagnostic and does not enter the semantic score.
- Timing is each arm's reported wall time and is not a uniform end-to-end resource measurement.

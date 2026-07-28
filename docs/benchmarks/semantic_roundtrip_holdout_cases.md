# Semantic Round-Trip Holdout Case Fixture (PLAT2-020)

**Interface:** `HoldoutCaseFixture@1`  
**Status:** frozen (preregistered before outcome inspection)  
**Fixture path:** `tests/fixtures/semantic_roundtrip/holdout_cases.json`  
**Population kind:** **hybrid** (selective-repair activation + additional legal corpus)

## Purpose

PLAT-000…091 sealed deterministic improvements on the five pilot cases.  
PLAT2 generalizes residual → teacher → prover → supervisor → remeasure onto a
**preregistered holdout** so later edit waves do not overfit the pilot
population.

This document freezes the holdout inventory, scoring bindings, and content
digests. Downstream residual catalogs, packets, and remeasure jobs must load
this fixture (or an explicit superseding revision) rather than inventing cases
after inspecting losses.

## Freeze digests

| Field | Value |
| --- | --- |
| Fixture path | `tests/fixtures/semantic_roundtrip/holdout_cases.json` |
| Fixture SHA-256 | `4a00c6f18345a58fa7fbfda9bd5b692f5a11739e270373ac2bfa3e20272fb92d` |
| Fixture CID (`cid_for_bytes`) | `bafkreickaddpda2fuwh2p675vg6vw2jpliixhhrhanz2yk72hyqcol5zfu` |
| Case count | 8 |
| Disjoint from pilots | yes |
| Gold binding | every case has nonempty `gold_ir` with `score_bindings.binding_kind = gold_ir` |

Recompute:

```bash
python - <<'PY'
import hashlib
from pathlib import Path
from benchmarks.logic_pipeline.content_addressing import cid_for_bytes
raw = Path("tests/fixtures/semantic_roundtrip/holdout_cases.json").read_bytes()
print(hashlib.sha256(raw).hexdigest())
print(cid_for_bytes(raw))
PY
```

Any edit to the JSON that changes bytes must update this digest table and the
constants in `tests/unit/benchmarks/semantic_roundtrip/test_holdout_cases.py`.

## Relation to sealed pilots

Sealed pilots (historical; **not** members of this holdout file):

| Pilot case ID |
| --- |
| `exception_with_window` |
| `legal_doc_1` |
| `exec_order_1` |
| `corp_policy_1` |
| `construction_contract` |

Holdout IDs are **disjoint** from the pilot set. Remeasure (PLAT2-060) still
re-scores pilots for non-regression; that is separate from this freeze.

## Hybrid population inventory

### Selective-repair activation cases

Sourced from `activation_fixture_pack()` in
`benchmarks/semantic_roundtrip/selective_repair.py`
(`selective-repair-activation-fixture-pack@1`).  
Gold IR is the pack's **repaired** IR. Score bindings also record baseline IR,
preregistered triggers, and expected trigger kinds/fields so selective-repair
arms can activate without inventing defect fixtures at eval time.

| Case ID | Family | Complexity | Gold rules | Activation focus |
| --- | --- | ---: | ---: | --- |
| `missing_temporal` | selective_repair_activation | 1 | 1 | empty temporal despite cue |
| `low_confidence_object` | selective_repair_activation | 1 | 1 | low-confidence object |
| `contradictory_modality` | selective_repair_activation | 1 | 1 | O/F contradiction + missing exception |

### Additional legal corpus cases

Drawn from non-pilot documents in
`tests/integration/test_deontological_reasoning.py`, with closed
`allowed_atoms` vocabularies and adjudicated `gold_ir` (same contract surface
as `pilot_cases.json` / `MatrixCase`).

| Case ID | Family | Complexity | Gold rules | Source ref anchor |
| --- | --- | ---: | ---: | --- |
| `legal_doc_2` | legal_corpus | 2 | 4 | `#legal_doc_2` |
| `privacy_act_amendment` | legal_corpus | 2 | 2 | `#conflicting_doc` |
| `fed_reg_1` | legal_corpus | 2 | 5 | `#fed_reg_1` |
| `dept_memo_1` | legal_corpus | 2 | 4 | `#dept_memo_1` |
| `hr_handbook` | legal_corpus | 2 | 5 | `#hr_handbook` |

## Stable case content addresses

Per-case CIDs are derived from `MatrixCase` (`case_id`, `source_text_cid`,
vocabulary, `gold_ir_cid`) via `cid_for_dag_json`.

| Case ID | case_cid | gold_ir_cid |
| --- | --- | --- |
| `missing_temporal` | `baguqeerammwsvjiat7ak6f4affngc4fa4xu7u3uhuzczi27hrw7bqslqfdza` | `baguqeerarzjnbz4cilrcimevj2zuv6vmznsqtkq6eita2nlocnfdce7k67da` |
| `low_confidence_object` | `baguqeera63mvsjj6zprb7rw7xtxan6iwdnuf7yodjqkxy5jrolqpsda3msmq` | `baguqeeravksx4cz6lvmq5ye6cudb5623up4sdgxmwzoceglkurgr33u7u6ma` |
| `contradictory_modality` | `baguqeeralsetrr6dgmk325hsjrz5ihcap2zqsiwbrojpw6karzntvj3kjftq` | `baguqeerawnmliribikhekysmwppx7idkdwyddvtj2nwti6sj32vocm2cl5fa` |
| `legal_doc_2` | `baguqeerafzhepffelzoxidjwy3ps2cvincjwrlw4xlsjhootyxkrywivwcza` | `baguqeeravkmv3rr5tcd73nnzm7vlgxjdjmx2s27pfqarfcrdkpthe4jqseiq` |
| `privacy_act_amendment` | `baguqeeram2xzjr6smksszeit6ipel5bqa6kyivya3pkgniosuozxjrimybcq` | `baguqeeraoeqjcapcjzvoiqkvxsxldvvuiehkdw3wu7lgllpbhd7lwrh5ibfa` |
| `fed_reg_1` | `baguqeeraoist6assmpg2k5zl4anhs5jble5rmtofvcnjuc36dxndlnsdfl4a` | `baguqeeraxadtk2qw6ut5dvsxjymzjcurwnlt3r2z5qbiqpehtzbysblhrn4a` |
| `dept_memo_1` | `baguqeerajkylucikrti6kxannxneqkex5vpzzdatu3mnbu3jzjbieiwqzdma` | `baguqeeraamv2jpv5hmdrqbugtgaxnjr4n5f6vy3tsiw7bxsaoh7ssszuy7pa` |
| `hr_handbook` | `baguqeera7qnnv7hd7tkej2cy2z2q4qyogf3cphlpdcf3hosvxfuqukrd5dja` | `baguqeeravum42fp4mbvlh7tcliwjqlcob6t2dbcaw7y55zyfvjw6v4vjkl2q` |

## Case record schema

Each element of the JSON array is a matrix-compatible case plus freeze metadata:

| Field | Required | Notes |
| --- | :---: | --- |
| `id` | yes | Stable case ID (`MatrixCase.case_id`) |
| `source_text` | yes | Nonblank natural-language source |
| `allowed_atoms` | yes | Closed `{actors,actions,objects,qualifiers}` vocabulary |
| `gold_ir` | yes | Nonempty `{"rules":[...]}` adjudicated IR |
| `score_bindings` | yes | At least `binding_kind: gold_ir`; activation cases add baseline/triggers |
| `case_family` | yes | `selective_repair_activation` or `legal_corpus` |
| `complexity_tier` | yes | Integer tier (1 activation, 2 legal multi-rule) |
| `source_ref` | yes | Provenance path/anchor |

Loading:

```python
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases

cases = load_matrix_cases("tests/fixtures/semantic_roundtrip/holdout_cases.json")
```

Unknown keys are ignored by `MatrixCase.from_dict`; vocabulary and gold IR are
strictly validated.

## Acceptance (PLAT2-020)

| Criterion | Status |
| --- | --- |
| Hybrid set includes `missing_temporal`, `low_confidence_object`, `contradictory_modality` | met |
| Additional legal cases beyond pilots | met (`legal_doc_2`, `privacy_act_amendment`, `fed_reg_1`, `dept_memo_1`, `hr_handbook`) |
| ≥3 cases beyond the five pilots | met (8 disjoint cases) |
| Stable IDs | met (ordered freeze list) |
| Gold IR or explicit score bindings | met (both on every case) |
| Digest recorded in docs | met (SHA-256 + CID above) |

## Validation

```bash
PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_holdout_cases.py -q
```

## Downstream consumers

| Consumer | Use |
| --- | --- |
| PLAT2-010 residual catalog | Holdout population path |
| PLAT2-030 packets / materializer | Holdout residual packets |
| PLAT2-040 teachers | Activation + legal residual proposals |
| PLAT2-050 det. edit waves | Case-scoped compiler fixes |
| PLAT2-060 remeasure | Holdout loss tables + pilot non-regression |

Doctrine unchanged: production remains typed_deontic → IR → deterministic
realizer; Hammer/cvc5/Lean never have semantic authority.

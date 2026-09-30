# Actual emitted formula text — inspected failures included

These are verbatim strings extracted from four already-published legacy reports.
They are **source compiler/bridge outputs**, not formulas independently decoded
by the legacy autoencoder. The autoencoder supplies diagnostic vectors and
compiler guidance. Its guided output is a modal AST, with no independent
learned textual formula decoder.

The reviewed sample contains 56 spans. The typed compiler reported 3 compiled
and 53 abstained; none of those counts proves a correct translation. Of 45
captured TDFOL records, 41 use the `tdfol:text:` fallback path. Eleven source
bridge documents were unavailable at export. A “logic document” is a container
of evidence; it is not a successfully autoformalized legal provision.

No new inference or formula rendering occurred for this view. No Lake build
was performed. Every item remains unadmitted and unqualified as a correct/gold semantic target.
Diagnostic failures can still support later repair training.

## Example 1: usc:us:10:4325

Source span: `uscode-span-00884ef681cbb16df4d9e77ef0c3649dc3883b7613b68867675565f8ddee80f1`

> L.

Emitted by `fol_tdfol.tdfol_formula` (record 0):

```text
O(l(actor))
```

Emitted by `cec_dcec.dcec_formula` (record 0):

```text
O[actor()](happens(actor(), l(), t0()))
```

This is a failure: a citation fragment became an obligation. `parse_ok=true` checks syntax, not whether the source states an obligation.

## Example 2: usc:us:10:4251

Source span: `uscode-span-0819f0c9e252ecefe47fd8e0c5bf9ac66c083a395ec206c60ed760cbae45eab4`

> 116–283, §1847(d)(1)(D)(i), redesignated pars.

Emitted by `deontic_norms.deontic_formula_records` (record 0):

```text
Lifecycle(N1847, RedesignatedPars)
```

Emitted by `fol_tdfol.tdfol_formula` (record 0):

```text
O(redesignated_pars(n_1847))
```

Emitted by `cec_dcec.dcec_formula` (record 0):

```text
LifecycleState(sym_1847(), redesignated_pars())
```

This is amendment-history text. The lifecycle record and obligation formula disagree about its meaning. The TDFOL obligation is not justified by this fragment.

## Example 3: usc:us:10:4873

Source span: `uscode-span-12e27cca693c89b19e111ce06593fe144ed4d6c2f1f74f4b112ac6f0b57db926`

> (3) In carrying out this section, the Secretary shall, to the maximum extent practicable, avoid imposing contractual certification requirements with respect to the acquisition of commercial products, commercial services, or commercially available off-the-shelf items.

Emitted by `deontic_norms.deontic_formula_records` (record 0):

```text
O(∀x (Secretary(x) → MaximumExtentPracticableAvoidImposingContractualCertificationRequirementsRespectAcquisitionCommercialProductsCommercialServicesOrCommerciallyAvailableOffShelfItems(x)))
```

Emitted by `fol_tdfol.tdfol_formula` (record 0):

```text
O(to_the_maximum_extent_practicable_avoid_imposing_contractual_certification_requirements_with_respect_to_the_acquisition_of_commercial_products_commercial_services_or_commercially_available_off_the_shelf_items(secretary))
```

Emitted by `cec_dcec.dcec_formula` (record 0):

```text
O[secretary()](happens(secretary(), to_the_maximum_extent_practicable_avoid_imposing_contractual_certification_requirements_with_res(), t0()))
```

The canonical rule has `action="to"`. The deontic bridge reports `proof_ready=false`, `requires_validation=true`, and omitted condition `in carrying out this section`. The long predicate name is not evidence that the legal scope was preserved.

## Where to inspect everything

The adjacent `formulas.jsonl` and `formulas.parquet` expose `source_text` and
`formula_text` as the first columns. Each occurrence retains its source report,
immutable revision, JSON pointer, record source ID, fallback marker and reported
validation flags. Duplicate occurrences are preserved: `formula` and
`proof_input` often repeat the same string. Row counts are not counts of
independent formulas or correctly formalized spans.

Flags such as `parse_ok`, `valid`, or a role-matrix entry saying “passed” are
reported producer evidence, not semantic qualification or Lake admission.
FOL/deontic-FOL/temporal/frame target names in metadata are not counted as
serialized formulas when the corresponding text was not actually emitted.
Original reports and structured ASTs remain available; this view supplements
them without relabeling bridge targets as learned model outputs.

## Published view and repeatable export

The [readable examples](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/bf95253007ce123fb44a551806f4e29e9a30834b/autoformal/uscode/formula-text/v1/1c3c60623f70fc1466fbe65bd57d0b5fca95670ea0c67c3e33c7c93784d8005c/EXAMPLES.md) and
[Parquet table](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/resolve/bf95253007ce123fb44a551806f4e29e9a30834b/autoformal/uscode/formula-text/v1/1c3c60623f70fc1466fbe65bd57d0b5fca95670ea0c67c3e33c7c93784d8005c/formulas.parquet)
are immutable archived-sample artifacts. The dataset card exposes configuration
`formal_logic_text`; future campaign batches do not automatically extend this
fixed audit. The live paired schema continues to retain their complete evidence.

Run the exporter with one or more completed full-report publication receipts:

```sh
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/export_report_formula_text.py \
  --publication /path/to/report.publication.json \
  --output-dir /path/to/formula-text
```

This command performs no inference or upload. It checks repository identity,
compressed and original report hashes, byte bounds, source-text identity and
captured document identity. It emits JSONL, Parquet and a manifest, preserving
exact strings and repeated occurrences. It does not synthesize missing formulas
or promote reported syntax flags into admission.

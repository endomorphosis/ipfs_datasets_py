# Saved LegalIR predictions to declared native formulas

The new `logic.legal_ir.saved_span_family_adapter` joins an existing saved decoder
report to exact source bytes, preserves its complete canonical IR and report,
and requires explicit caller declarations before generating a native formula.
The existing family bridge regenerates the native AST and Lean representation;
the existing bounded Lake gate then compiles those regenerated sources.

## Observed result

The engineering pilot used 12 predeclared, previously exposed authored TUNE
cases from the actual full 96-row `source_only-1729-ce0` inference report. Nine
cases cover O/P/F with no qualifier, a condition, or an exception. All nine
passed native parsing, AST regeneration and authoritative replay. The three
temporal cases were refused by the current ground profile. The nine-case
project actually passed `lake build legal` with Lean 4.34.1, return code zero,
and all 11 expected modules: Prelude, nine candidates and the root module.

These are explicit development interpretations, including the manually supplied
`registrationAccepted` and `preservationNoticeEffective` predicates. Compilation
does not establish that those predicates or scopes are legally correct. O/P/F
remain independent interpretation parameters; the project adds no legal axioms
or placeholder proofs. No semantic accuracy, proof authority or evaluation
admission is asserted. The pilot performed no new inference or optimizer update.

This run used the trained 384D source-only lane with `latent_enabled=False`.
It is not a 0D checkpoint or a new 8D/768D evaluation. The adapter accepts the
explicit `objective-resumed-source-span-inference/v1` continuation lineage and
bounded progress/objective metadata; it is not a generic importer for every
historical decoder artifact.

The eight previously exposed US Code sources retain both raw and joint saved
proposals, for 16 dispositions. One raw and four joint proposals can produce an
unfilled declaration packet; the other 11 proposals are refused. These counts
are proposal/profile dispositions, not legal accuracy or an independent sample
of 16 statutes. All five blank declarations refuse native preparation. The
actual eight-item statutory review remains empty: zero human submissions,
semantic labels, new targets or admission masks.

## API and hash scopes

1. Authenticate the original source/report/checkpoint artifact identities outside
   this adapter. `parse_json_bytes` rejects duplicate keys, nonfinite values and
   invalid UTF-8. `digest` hashes sorted compact finite JSON with
   `ensure_ascii=False`; it is a canonical-content hash, not a file-byte hash.
   The saved checkpoint producer uses its own canonical digest convention.
2. Call `prepare_pending(source, full_report, expected_report_sha256=...,
   expected_checkpoint_sha256=..., row_id=...)`. An optional joint report must
   be bound separately. Complete reports stay in the packet, with original row
   position, source, control, checkpoint and selected facets. Scored raw/joint
   rows are replayed; unscored authored reports retain an explicit no-head-replay
   distinction. Caller-provided hashes and saved score consistency do not
   authenticate model execution or a checkpoint's training origin.
3. `declaration_skeleton(packet)` leaves the occurrence, modality cue coordinates,
   qualifier expressions and scopes unfilled. Supply exact source intervals and
   an explicit interpretation. The adapter checks cue literals and values,
   nonoverlapping geometry, complete facet coverage and occurrence binding.
   It does not infer legal predicates, binder roles or scopes.
4. Call `prepare_family(packet, declaration, expected_packet_sha256=...,
   family="deontic")`, then `validate_family` with the same authoritative inputs.
   Validation regenerates the entire result. A mutated result cannot gain
   authority by changing a checksum. The result itself has no resealable content
   checksum contract.
5. For the existing Lake gate, use the result's `request` plus
   `family=result["native_parser_profile"]`. The native parser profile is
   `deontic_fol`; the adapter's sealed family selector is `deontic`.
   `build_source_family_legal` requires an explicit installed native Lake ELF
   and version-pinned toolchain. Unsupported entries block the whole batch.

Only the sealed `deontic` route to `deontic_fol / ground-null-context/v1` is
supported by this transport. TDFOL, DCEC, FOL and parser-name aliases are
explicitly refused by this adapter. Registry names alone do not qualify family
support. Temporal, modal-context, composition and binder-role support require
separate declared profiles and tests before adding routes. The existing wider
logic registry and native bridge remain unchanged.

## Statutory declaration preflight

`statutory_declaration_preflight.preflight_declarations` replays the original
review recording before and after diagnostics. The archival recorder remains
unchanged and retains partial or disputed declarations. The preflight identifies
explicit declaration contradictions, unresolved dependencies, unknown answers,
and interval problems without choosing a legal interpretation. Operative versus
editorial span overlap is a geometry warning, not a general legal prohibition.
It preserves all declaration order, anchors and attachments; every training,
evaluation and semantic authority flag remains false, with zero admission masks.
`validate_preflight` regenerates the result from the original inputs.

## Validation and execution limits

The selected seven-file inert suite finished with **417 passed, two skipped**.
The skipped tests require a native compiler opt-in; the dedicated actual build
above supplies separate native evidence. Earlier attempts are retained: two
collection failures from sparse dependencies/package namespace setup, two
controlled subprocess tests initially blocked by the harness, and one later
missing sparse utility in a fresh child. No production owner was changed to fix
those environment failures.

The harness uses finite named numerical import denials and two exact controlled
fresh-Python import checks. Namespace bootstrapping bypasses package initialization;
file pins for namespace placeholders do not mean that their initializer code ran.
This is scoped verification, not a full package initialization or process sandbox.

The unchanged native gate uses a 60-second wall deadline, a per-process CPU limit,
`LEAN_NUM_THREADS=2`, a sampled 2 GiB process-tree RSS guard, 128 MiB workspace
guard, 8 MiB input bound and 262,144-byte output bound. Thread settings are not an
aggregate process/thread quota; sampled RSS/disk guards can overshoot and are not
kernel aggregate quotas. Version probes have separate existing five-second limits.
Native Lake/Lean/prlimit binaries are pinned, not the entire dynamic toolchain.
The generated project has no package dependencies and uses native executables
instead of elan shims. Python network calls are denied; native child network
calls are not audited by Python and no kernel network namespace is claimed.
Old numerical guardian claims and caps are unchanged.

## Contribution and next gaps

The intake audit found all 22 selected source heads and ten workspace heads
represented in main. Older divergent recovery histories were preserved for
review, not merged wholesale. This contribution adds two modules, their tests,
this guide, and closed evidence under
`workspace/test-logs/legal-formal-output-20261011-01/evidence`.

The evidence retains original failed attempts, helper correction drafts, full
target-free saved reports inside packets, strict source joins, explicit caller
interpretations, independent reviews and the actual native build receipt.
Model bodies, full foreign ledgers and old checkpoints are excluded. Previously
published weights remain at the pinned Hugging Face structured-span release;
this change creates no new weights or default promotion.

Remaining semantic work is independent review of the supplied statutory context,
explicit cue/qualifier/binder declarations, and a leakage-controlled reference
set. Subsequent temporal or other-family routes must prove their own AST/source
round trips and native behavior. Training gains should then be assessed against
those reviewed labels, rather than these exposed engineering fixtures.

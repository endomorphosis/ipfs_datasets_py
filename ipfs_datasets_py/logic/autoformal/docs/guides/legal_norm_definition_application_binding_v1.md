# Bind applicability custody to a conditional definition instance

`legal_norm_definition_application_binding_v1` records the association between
an authenticated exact-use applicability declaration and one conditional
bound-variable definition instance. It reuses the
[applicability owner](legal_norm_definition_applicability_v1.md) and the
[conditional instance owner](legal_bound_variable_definition_v1.md), replaying
their complete original evidence. The original norm and definition ASTs remain
unchanged.

The three public entry points are
`prepare_norm_definition_application_binding_v1`,
`validate_norm_definition_application_binding_v1` and
`norm_definition_application_binding_sha256`.

## Supply complete replay inputs

Preparation accepts the original applicability assessment and exact conditional
request bytes, with independently retained complete-assessment and raw-request
SHA256 pins. `applicability_inputs` is a closed dictionary containing every
original argument to `assess_norm_definition_applicability_v1`, including its
six positional arguments by name. Its `companion_inputs` contains all six
original norm-definition companion preparation arguments. Missing fields and
extra fields are refused.

The owner validates the entire applicability assessment against those original
inputs. Rehashing a changed report cannot replace regeneration. Common-body
content must be valid, and common-body authentication and partial declaration
custody must both have passed under the selected trust snapshots. These checks
retain the upstream scope: definition-endpoint authentication and association
custody. The complete norm-review cohort and closed normative context remain
unavailable.

An independently pinned request is parsed by the fixed installed conditional
owner. The bridge finds one use by the complete original typed target record,
then requires its original ordered decision to name the same complete nominated
link. An unresolved decision cannot create a binding. Alternative identity,
term and AST references, ordered source paths, binder, predicate argument and
role must agree. The conditional owner separately validates full typed/native
occurrence geometry, carrier/context declarations and the supported definition
grammar.

The conditional instance is generated from the replayed applicability report's
same original companion and the same companion inputs. Callers cannot splice
in a conditional report from another preparation. The output retains the entire
applicability assessment, every original use, choice and alternative, the full
generated conditional report and its complete canonical hash. The selected
binding identifies one association; no rival is declared inapplicable.

## Keep the premises explicit

At the supplied shared interpretation, carrier and fixed formal time,
`hDefinition : ∀ x, D x ↔ Body x` supports the instance `D r ↔ Body r`.
Producing `Body r` additionally requires the conditional request's explicit
`hMembership : D r` for that same variable. Both are unverified parameters.
Applicability authentication supplies neither premise and does not verify
membership, carrier identification, binder valuation or the shared context.

The applicability signatures cover their original common declaration. They do
not sign this binding, the conditional request or generated Lean text. This
bridge introduces no signing action or union dependency manifest.

`time_context` retains the declared civil legal-as-of date and scope statement,
the original supplied applicability evaluation clock, and the conditional
request's formal context separately. Replay uses that original supplied clock;
it does not establish a fresh current observation. No calendar-to-`Nat`
conversion or legal-date/formal-time alignment is inferred.

The report's governing use and selected/accepted interpretation remain null.
All semantic, consumer, training and evaluation-gold masks remain zero.
Application, membership, proof and Lean-build authority remain false. No norm
AST is rewritten, witness extracted or semantic definition-use edge admitted.

## Validate and retain evidence

Validation takes the offered binding, its independent complete-report pin and
all original preparation arguments. It regenerates both owners' results and
requires complete equality. Retain those original inputs separately; the
binding report alone cannot reproduce their trust snapshots, evidence bytes or
dependency observations.

The inherited aggregate snapshot profile remains four million nodes and
128 MiB, with an eight-MiB final report and 128-KiB request. Aggregate intake
counts the complete supplied envelope, so separately admissible upstream
records can still exceed this combined profile. Oversized populations are
refused without truncation. Original-input, detached-input, direct/inherited
producer and final-serialization fences remain in force. No limit is raised.

The enclosing workspace's [qualification record](../../../../../../../artifacts/legal-norm-definition-application-binding-20261017-02/README.md)
retains installation, focused test outcomes and independent saved-result
readback for this custody bridge. Actual statutory applicability packets,
reviewer/trust/clock populations, training and source-bound Lean builds require
separate evidence and remain outside this operation.

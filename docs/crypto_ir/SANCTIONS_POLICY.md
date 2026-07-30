# Crypto IR sanctions policy boundary

Status: normative engineering contract for CRYPTOIR-G400
Machine schema: `ipfs-datasets.crypto-ir.sanctions-policy@1.0.0`

This document defines how Crypto IR represents sanctions-list authority,
screening evidence, ownership evidence, licenses, and reviewed risk policy. It
is not legal advice. A screening result is not a legal certification, a report
to an authority, or transaction authorization.

The implementation is deliberately offline: do not fetch live lists from this
policy layer. Tests and normal imports do not resolve names, call chain
providers, submit reports, sign, or broadcast. Production code must inject a
separately acquired and validated
`SanctionsSnapshot`; the ingestion and freshness controls for any real source
are separate responsibilities.

## 1. Non-interchangeable authority

The system preserves three different kinds of authority:

| Record | Authority represented | What it cannot do |
| --- | --- | --- |
| `SanctionsAuthority`, `SanctionsSnapshot`, `DesignationRecord` | Evidence of what a named publisher stated in an exact list revision | Approve an organization's legal/risk policy or authorize a transaction |
| `OwnershipEvidence`, `AssociationEvidence`, `LicenseRecord` | Time- and source-scoped evidence | Manufacture a designation or a universal legal conclusion |
| `LegalPolicyApproval` | A legal-owner-approved binding to one policy id, revision, rules digest, and effective window | Change source-list facts or turn screening into transaction authorization |
| `SanctionsDecision` | Result of applying the bound policy to supplied evidence | Certify legality, report externally, sign, or broadcast |

List publisher, evidence producer, legal-policy owner, policy evaluator, and
transaction authorizer are therefore not aliases. Conversion between records
does not elevate authority.

## 2. Typed source data

A snapshot binds all of the following:

- a typed `SanctionsAuthority` and its jurisdiction;
- a typed `SanctionsList`;
- an exact list revision, publication time, effective time, retrieval time,
  content digest, completeness flag, and optional predecessor;
- typed `DesignationRecord` entries with party identity, programs,
  jurisdictions, and effective windows; and
- chain-qualified `DigitalCurrencyIdentifier` entries with namespace, network,
  address, and optional asset reference.

List ids, programs, jurisdictions, revisions, and times remain separate typed
fields. The implementation does not treat a name string, an address on another
network, a program code, or a stale revision as interchangeable.

## 3. Evidence classes

The following outcomes answer different factual questions and must remain
distinct:

1. **Exact listed identifier** — a supplied chain-qualified identifier exactly
   equals an identifier in an effective designation.
2. **Named designated party** — an exact asserted party id equals the party id
   in an effective designation. Fuzzy name similarity is not this class.
3. **Evidence-backed ownership** — complete, effective `OwnershipEvidence`
   cites designated owners and satisfies the threshold in the selected
   versioned policy.
4. **Direct association** — evidence states a direct relationship to a
   designated party. It is not automatically a designation or ownership.
5. **Bounded indirect exposure** — evidence states a path of bounded depth to a
   designated party. The path and its coverage frontier remain explicit.
6. **Heuristic association** — clustering, similarity, shared infrastructure,
   or another prioritization signal. It cannot become a designation merely by
   relabeling.

`NO_MATCH`, `UNKNOWN`, and `ERROR` are also not positive evidence classes. A
negative result is bounded to the supplied snapshot, identifiers, parties,
ownership sources, association sources, time, program, jurisdiction, and
activity.

Entity and aggregate ownership are typed separately. Percentages use integer
basis points. The library does not hard-code a universal fifty-percent rule:
`ownership_threshold_basis_points` is a reviewed policy input. Complete
evidence totaling 4,000 basis points can therefore fall below one approved
policy's threshold and meet another approved policy's threshold without the
engine claiming either threshold is universally correct.

## 4. Versioned legal and risk policy inputs

`SanctionsPolicy` contains:

- policy id and revision;
- jurisdiction, accepted authority ids, list ids, and program ids;
- one `PolicyRule` for every positive evidence class and for `NO_MATCH`;
- the ownership threshold;
- the maximum accepted snapshot age;
- license disposition and license outcome;
- a complete ordering of screening outcomes used to combine applicable rules;
  and
- the policy effective window.

No match outcome, indirect-exposure outcome, license treatment, ownership
threshold, or precedence is supplied by an unversioned engine default. These
are versioned inputs.

The policy computes a canonical SHA-256 **rules digest** over exactly those
inputs, excluding approval metadata. `LegalPolicyApproval` must bind:

- the same policy id and revision;
- that exact rules digest;
- a named legal-owner id;
- approval and effective times;
- an approval-artifact digest; and
- whether production enforcement is approved.

Changing any rule, threshold, scope, precedence, license treatment, time
window, policy id, or revision changes the rules digest. Reusing the old
approval then fails record construction. Approval artifacts and source-list
artifacts remain separate.

## 5. Licenses and exceptions

A `LicenseRecord` is not a free-form allow-list entry. It is scoped by issuing
authority, license type, subject party ids, program ids, jurisdiction codes,
activity ids, an effective window, and an approval-artifact digest.

The evaluator recognizes a license only when every scope dimension matches.
Its treatment still comes from the selected policy's `license_disposition`,
`license_outcome`, and outcome precedence. An applicable license therefore
does not silently erase an exact match, imply legality outside its scope, or
create a universal exemption.

## 6. Evaluation and fail-closed behavior

`evaluate_sanctions_policy(policy, request)` is deterministic and side-effect
free. It binds its result to the policy id, policy revision, rules digest,
snapshot id, and snapshot revision.

Production enforcement is refused with `INCONCLUSIVE` and
`missing_legal_policy_authority` unless an effective `LegalPolicyApproval`
authorizes production use of the exact rules digest. Evaluation also fails
closed for:

- incomplete or out-of-scope snapshots;
- a snapshot that is not yet effective;
- a snapshot older than the policy's explicit maximum age;
- an ineffective policy; and
- incomplete applicable ownership or association evidence.

Rules determine the screening outcome for each evidence class. Policy-provided
precedence combines multiple applicable outcomes. Engine code does not assume
that a particular evidence class must universally be `ALLOW`, `REVIEW`, or
`DENY`.

An `ALLOW` has one narrow meaning:

> The supplied subject was screened under the decision's named policy
> revision and exact snapshot revision, with the supplied bounded evidence.

It does not mean “not sanctioned everywhere,” “lawful,” “safe,” “approved to
transact,” or “no undiscovered association exists.” `SanctionsDecision`
explicitly reports that it is not a legal certification and cannot authorize a
transaction. A separate current transaction-authorization boundary must
consume any screening result under its own fail-closed rules.

## 7. Review and change procedure

Before production use:

1. Legal and compliance owners review the jurisdictions, authorities, lists,
   programs, thresholds, evidence outcomes, precedence, license behavior,
   freshness limit, and effective window.
2. Serialize the reviewed `SanctionsPolicy` without approval and record its
   canonical rules digest.
3. Store a signed or otherwise controlled approval artifact outside this
   package and record its digest.
4. Create `LegalPolicyApproval` binding the legal-owner identity, policy id,
   revision, rules digest, approval artifact, effective window, and production
   permission.
5. Reconstruct and validate the approved policy. Any mismatch fails closed.
6. Inject validated snapshots and evidence; retain the resulting decision's
   policy/snapshot bindings for audit.
7. On any policy change, issue a new revision and approval. Do not reuse an old
   approval after the rules digest changes.

Operational owners must also define snapshot acquisition, validation,
retraction, retention, and incident procedures. This module intentionally
supplies no live authority endpoint and no claim that its fixture policy is
appropriate for a real organization.

# Xaman Testnet Leanstral Policy

Task: `PORTAL-CXTP-137`

This policy configures Leanstral as an untrusted proof-assistant lane for the
Xaman XRPL Testnet verification packet. Leanstral may help draft proof terms,
model edits, or counterexample hypotheses, but it is never a proof authority
and never changes a security decision by itself.

The locked artifacts are:

- `security_ir_artifacts/corpora/xaman-app/testnet/leanstral-assistant-lock.json`
- `security_ir_artifacts/corpora/xaman-app/testnet/leanstral-candidate-audit.json`

They are bound to the frozen Testnet model CID:

`sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43`

## Allowed Use

Leanstral output is limited to three proposal classes:

- `lean_proof_term`: suggested Lean 4 terms or proof refactors for
  `security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.lean`
- `security_model_edit`: proposed model or semantic edits for existing Testnet
  `NOT_MODELED` or blocking-boundary claims
- `counterexample_hypothesis`: redacted hypotheses that may later be materialized
  as SMT, model-checker, protocol, fuzz, or reviewed-trace counterexamples

Prompts and candidates must preserve the Testnet redaction boundary. Raw wallet
material, production credentials, account secrets, raw payloads, signatures, and
transaction blobs are not allowed in prompts, model outputs, candidate files, or
audit notes.

## Promotion Gate

Every Leanstral candidate starts as `untrusted_pending_independent_check`.

No candidate may set `PROVED`, clear an assumption, mark Testnet assurance as
complete, update a release gate, or otherwise change a security decision until
one of the approved independent checkers accepts the candidate and records a
committed checker report.

Approved acceptance authorities are:

- Lean or Coq for proof-term candidates
- Z3, CVC5, Apalache, Tamarin, ProVerif, Lean, or Coq for model-edit candidates
- Z3, CVC5, Apalache, Tamarin, ProVerif, a reviewed runtime trace, or the
  registered fuzz harness for counterexample-hypothesis candidates

Single-model output is never sufficient evidence. The acceptance report must
identify the checker, command or harness, model CID, candidate artifact, result,
and artifact CID.

## Current Audit Decision

The current candidate audit records zero submitted Leanstral candidates, zero
independent-checker acceptances, and zero promoted security decisions.

The existing Testnet decisions remain unchanged:

- Lean checked only the formalized invariants in `XamanTestnet.lean`.
- SMT differential evidence reports 12 non-secure Testnet counterexamples; the
  witnesses are the unresolved blocking assumptions in the locked query.
- Coq independent-kernel coverage is required but missing.

Therefore the lane status is advisory only:

`UNCHANGED_BY_LEANSTRAL_UNTRUSTED_LANE`

## Regeneration

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/generate_xaman_testnet_leanstral.py
```

Validate:

```bash
test -f security_ir_artifacts/corpora/xaman-app/testnet/leanstral-assistant-lock.json
test -f security_ir_artifacts/corpora/xaman-app/testnet/leanstral-candidate-audit.json
test -f docs/security_verification/xaman_testnet_leanstral_policy.md
```

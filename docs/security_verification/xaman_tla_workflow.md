# Xaman TLA+/Apalache Signing Workflow

Date: 2026-07-08

Scope: PORTAL-CXTP-071 workflow checks for the Xaman payload signing path.

This artifact adds a finite TLA+ model for the client-side Xaman signing
workflow and a checked Apalache report envelope. The model covers payload fetch,
review, user approval, pre-sign revalidation, signing, rejection, expiration,
replay blocking, network binding, signed-payload patching, optional broadcast,
and dispatch-result patching.

The current report is intentionally fail-closed: Apalache is not available in
the local verification environment, so every temporal property is marked
`BLOCKED` rather than `PROVED`.

## Artifacts

- TLA+ module: `security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla`
- Apalache report: `security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json`
- Generator: `scripts/ops/security_verification/generate_xaman_tla_workflow.py`
- Report builder: `ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_tla_workflow`

The report is generated from:

- `security_ir_artifacts/corpora/xaman-app/security-model-ir.json`
- `security_ir_artifacts/corpora/xaman-app/security-model-ir.cid`
- `security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json`

## Modeled Transitions

`XamanSigning.tla` defines these workflow actions:

- `Fetch` and `FetchWrongNetwork`
- `Review`
- `Approve`
- `Revalidate`
- `Sign`
- `Reject`
- `Expire`
- `ReplayAttempt`
- `NetworkMismatchBlock`
- `PatchSigned` and `PatchSignedNoSubmit`
- `Broadcast`
- `DispatchPatch`
- `ResultDisplay`

The model keeps fetch, review, approval, revalidation, signing, rejection,
expiration, replay, network binding, and broadcast as separate transition
classes so each acceptance category has a direct TLA operator and report entry.

## Temporal Properties

The report records ten required properties:

- `FetchSafety`
- `ReviewRequiresVerifiedFetch`
- `ApprovalRequiresReview`
- `RevalidationPrecedesSigning`
- `SigningRequiresFreshNetworkBoundPayload`
- `RejectionIsTerminalAndUnsigned`
- `ExpirationBlocksSigningAndBroadcast`
- `ReplayIsBlocked`
- `NetworkBindingSafety`
- `BroadcastAfterSignedPatch`

Each property links back to reviewed payload-lifecycle facts and the related
Xaman security claims or assumptions in the security model IR.

## Solver Blocker

`apalache-report.json` records:

- `apalache.available: false`
- `apalache.status: BLOCKED`
- `summary.checked_property_count: 0`
- `summary.blocked_property_count: 10`
- every property `classification: BLOCKED`

This is a solver blocker, not a modeling success. A proof consumer must not
promote any Xaman signing workflow property to `PROVED` until Apalache is
installed and the checks are rerun; absent Apalache results must not be
accepted as proved.

## Regeneration

Run:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python \
  scripts/ops/security_verification/generate_xaman_tla_workflow.py
```

Validate:

```bash
PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest \
  tests/logic/security_models/crypto_exchange/test_xaman_tla_workflow.py -q
```

## Promotion Rule

The workflow can be promoted only when a regenerated report records an available
Apalache executable and every required property has an accepted solver result.
Until then, the report remains a blocking artifact for the Xaman release
decision.

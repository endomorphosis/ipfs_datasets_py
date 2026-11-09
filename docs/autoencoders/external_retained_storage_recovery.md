# Recover one retained claim with an external output tree

`reconcile_retained_external_reservation` is an administrative storage-closeout API in
`ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_external_artifact_recovery`.
It does not admit training, provider calls, legal conversions or Lean results.
Only an actual `lake build <Lib>` supplies Lean admission.

Use this API for one dead owner's retained disk claim containing exactly one recorded
external charge. The older `autoencoder_resource_recovery` API remains unchanged and
continues to refuse external charges. Do not delete outputs, erase external charges,
edit the ledger manually, expire claims by age or impersonate the original owner.

The caller must hold actual source and native administrative custody. Bind the original
execution request, exact retained-row hash, named storage roots, attempt identity and
external device/inode identity. Require the original owner PID to be absent and every
recorded child group to be dead. Complete inventories must contain sorted relative
pathnames, byte sizes and SHA256 hashes of unaliased regular files. The API verifies and
fsyncs both trees; supplied flags do not substitute for those checks.

Required keyword arguments are `roots`, `reservation_id`, `expected_record_sha256`,
`attempt_directory`, `expected_artifacts`, `external_evidence` and
`artifacts_durable=True`. `external_evidence` has exactly these fields:

- `charge_key` and `charged_bytes`: the entire original single charge.
- `root_identity`: exact `path`, `device` and `inode`.
- `execution_request_pin`: exact original request `path`, `bytes` and `sha256`.
- `expected_artifacts`: complete external-tree inventory.
- `artifacts_durable=True`.

`capacity_policy="require_capacity"` is the default. Explicit
`"administrative_closeout"` records an existing overage while closing this one claim;
it does not increase capacity or admit work. The entire original claim stays charged
until verified release. Actual output bytes remain in the named-root census and all
external-charge history and other reservation rows remain unchanged.

A write can become visible before its durability check fails. On an exception,
`ExternalRecoveryWriteIncomplete` or `ExternalRecoveryPostwritePending` exposes actual
locked readback disposition: retained preimage, released/pending, released/receipt or
unknown. `claim_released` is true only for an exact matching visible released row;
unknown is null. Observed ledger markers, completed writes, durability and unresolved
caller verification are separate fields. No exception authorizes automatic retry or
claims rollback. Retain the exception evidence and reconcile the actual state.

Success includes a final nonpersisted capacity census and row readback after receipt
persistence. Save the returned report independently; its final census is deliberately
not written recursively into the ledger. An earlier receipt marker alone is insufficient.

The initial source candidate passed 36 private-fixture cases, including real scoped
filesystem failure injection before/after replacement, unknown readback, final receipt
capacity growth, changed files/roots, live or reused PIDs, aliases and preserved other
rows. Canonical deployment needs its own normal-import check. Source tests create no
native or semantic qualification and do not release a real reservation. The owned
probe03 claim remains retained until an explicitly verified administrative operation.

Full global censuses hold the ledger lock. Defer a long recovery while another live
native disk owner is active; do not starve its heartbeat or bypass its reservation.

The existing `autoencoder_external_resource_recovery` module and its batch API
remain unchanged. That API preserves legacy receipt associations and absent
external leaves; it reports prewrite projected accounting and requires a
separate postwrite census. This artifact API requires one bound retained
external directory and its complete durable inventory, classifies actual
write-error readbacks, and verifies final accounting after receipt persistence.
Choose the API that matches the available evidence; neither grants native
authority or a Lean admission.

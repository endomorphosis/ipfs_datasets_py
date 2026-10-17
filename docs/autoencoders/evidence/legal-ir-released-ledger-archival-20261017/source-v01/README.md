# Released reconciliation ledger archival

This is an additive, source-only SDK proposal. No module, tests, ledger operation, scheduler grant, or Docker command was executed by the author. It addresses the real8MiB disk-ledger JSON bound by folding only explicitly selected, already-released `explicit_reconciliation` fields. It does not raise the8MiB metadata bound,4096-row bound,160GB storage cap, scheduler capacity, or any task/model acceptance gate.

`archive_released_reconciliations` requires genuine same-process native ORCHESTRATION root and direct child phase `ResourceLease` objects, actual scheduler/policy identity, expected request IDs, an exact current raw ledger SHA256, and at most8 explicit selections. Both leases must actually renew and match the public active native envelopes, with at leastCPU1,256MiB and one cooperative process slot. The API internally uses the existing SDK ledger lock, reader, ordinary capacity census and atomic durable writer. Callers never invoke private ledger writers or manufacture a disk-owner object.

Each selection is exactly `reservation_id`, `expected_record_sha256`, `expected_reconciliation_sha256`, `expected_owner_pid`, `expected_attempt_path`. Record/field SHA256 uses the existing recovery convention: sorted compact JSON without a trailing LF. The full raw ledger snapshot SHA256 hashes the exact original bytes. Every selected row must be released, durable, and contain an unarchived reconciliation object. Other selected fields and every unselected row remain unchanged; in particular no active or retained status/accounting/identity is changed.

The operation is a dedicated administrative recovery admission. Under the real ledger lock it prechecks a finite32MiB peak allowance using the normal named-root accounting. The allowance covers the full original snapshot (at most8MiB), the projected atomic replacement (at most8MiB), up to2MiB of bounded journal allowance, and a64KiB directory margin. The actual code writes one intent journal and one snapshot. It acquires no fabricated `ParentedPhaseResourceReservation` or fresh native disk child; the real root/phase owns this bounded administrative operation. Competing ordinary ledger admissions remain locked until all operation writes have finished. Other owners’ physical writes remain cooperatively accounted through their full outstanding reservations and fresh censuses; this is not a hard filesystem quota.

The fresh archive directory must be private0700 beneath a declared named root, outside every outstanding attempt. The normal capacity check occurs before any new file bytes. The exact raw ledger snapshot and admission intent are private0600 files; file, archive-directory, and parent-directory fsyncs precede the first folded ledger commit. The snapshot must never be added to Git, Hugging Face, logs, or public evidence. It contains the full private ledger history. The supported SDK writer atomically commits the folded ledger and a truthful completed administrative record; its workload explicitly distinguishes this operation from ordinary parented disk admission.

After that commit, the API performs only read-only verification: it re-reads the actual ledger and private snapshot, restores each entire original selected record, checks real native custody and named-root accounting, then returns bounded summary metadata. There are no file writes after the administrative record becomes released. Its `released_at_semantics` explicitly labels the planned transaction metadata timestamp; `observed_atomic_commit_at` in the returned summary is the actual post-commit observation. The native root/phase stays held by the caller until the call and any separately authorized read-only verification finish.

A crash before atomic commit preserves the original ledger and any durable private snapshot/intent. Those physical bytes remain covered by the named-root census, and no productive child or continuing storage promise is launched. A failure after commit preserves the committed ledger, archive, and intent; it must not blindly repeat the operation or claim success from file presence. The intent records the planned ledger SHA, exact pointers, original snapshot SHA, selections and administrative identity for actual recovery. Replaying a folded selection is refused. Root must pin the actual current ledger/selection immediately before execution because other authorized owners may update the ledger.

`plan_reconciliation_archival`, `restore_archived_record`, `required_peak_bytes`, and `check_capacity_precharge` are pure in-memory protocol helpers. They grant no authority. The unittest script uses only stdlib, in-memory data and stdout; it has no pytest, temporary files, JUnit, caches or artifact writes. Root may execute it in the same interpreter under genuine finite native scheduler ORCHESTRATION root→phase CPU/memory admission before ordinary disk admission is possible. Those tests qualify only selection, transformation, lossless recovery, capacity mathematics and refusal behavior. Actual locking/fsync/atomic commit/native storage admission requires its own separate genuine recovery qualification.

Public effectful API:

```python
archive_released_reconciliations(
    ledger_path, *, roots, archive_directory, selections,
    expected_ledger_sha256, root_lease, phase_lease,
    root_request_id, phase_request_id, scheduler_state_path,
    expected_scheduler_policy_sha256,
    peak_storage_bytes=32 * 1024 * 1024, timeout_seconds=900,
)
```

The intended actual operation selects the two explicitly reviewed large released reconciliations, recovering approximately4.9MiB of ledger headroom. It preserves their entire original records in the exact full snapshot. This proposal has no provider, training, corpus, Legal IR completion or proof authority.

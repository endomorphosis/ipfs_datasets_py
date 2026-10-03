# Captured header context

`logic.software_contracts.codebase_header_context` derives deterministic header
models from complete Python modules captured by `RepositoryCodebaseIndex`. It
reuses the existing SecurityIR header recognizer, source spans, formalization
adapter and SMT obligation compiler. It does not load an autoencoder, run a
solver, or execute captured source. The Source384 consumer and supervisor do
not select this adapter yet.

An explicit, reviewed `WsgiHeaderProtocolContract` is required. Its callback
role and the recognizer's conversion/Unicode assumptions are premises of the
model, not properties established by this adapter. A missing protocol is an
input error. Unsupported modules remain visible as per-module abstentions;
integrity, resource and deadline failures raise instead of becoming abstentions.

## Three operations

| API | What it checks | Result |
| --- | --- | --- |
| `prepare_captured_header_context` | Exact native catalog head, complete captured source CID/size/SHA, protocol, recognizer output and producer files; checks the head again after CAS publication | Small receipt for a bounded historical CAS artifact |
| `validate_captured_header_context` | Fresh bounded CAS reads and exact deterministic replay against the selected captured head, paths, protocol, producers and receipt | The same validated historical receipt; no live tree scan |
| `validate_current_header_context` | Native `observe_current` before and after historical replay, using one deadline and parent resource lease | Observation wrapper containing the captured receipt and two native observation calls |

All results retain `current_source_verified=False` and deny proof, execution,
mutation and completion authority. Even the current wrapper describes source
observations at that call; it grants no lasting currentness or proof authority.
Callers already owning an independent fresh-source boundary may compose the
historical replay inside it without duplicating observations. No caller-provided
observation token is accepted as authority.

```python
from ipfs_datasets_py.logic.security_ir.doctor_header_contracts import (
    WsgiHeaderProtocolContract,
)
from ipfs_datasets_py.logic.software_contracts.codebase_header_context import (
    prepare_captured_header_context,
    validate_captured_header_context,
    validate_current_header_context,
)

# index, head and scheduler come from the existing native repository owners.
selection = dict(
    expected_head=head,
    paths=["headers.py"],
    protocol=WsgiHeaderProtocolContract(
        review_ref="reviewed-wsgi-protocol-contract", callback_parameter="start_response"
    ),
    scheduler=scheduler,
)
receipt = prepare_captured_header_context(index, **selection)
historical = validate_captured_header_context(index, receipt=receipt, **selection)
observed = validate_current_header_context(
    index, repository, receipt=receipt, **selection
)
```

The adapter requires exact native index, catalog and CAS owners. It reads full
captured modules rather than truncated function windows and preserves their
source maps. Selection is limited to 128 explicit paths, 4 MiB of selected
Python source, 2,000,000 bytes per modeled module, and an 8 MiB report. Existing
native resource admission is preserved; the default reservation is 512 MiB and
the default operation deadline is 90 seconds. Deadline/cancellation checks are
cooperative; they do not interrupt a parser call asynchronously.

## Qualified scope

The authored fixture and the exact permitted public Bottle fixture each yield
two modeled helpers, 12 deterministic formulas and six SMT obligations. These
counts are not learned reconstructions, discharged obligations, or whole-program
proofs. Model loads, learned formulas, provider calls, solver calls and training
steps are zero. No Lean compilation was performed by this qualification.

The integration controls cover complete-module source maps, unsupported modules,
cold reopen, source/receipt/protocol/producer tampering, catalog advancement during
artifact publication, cancellation, deadlines and native resource refusal. The
tests use an isolated native scheduler with injected host telemetry; they do not
qualify host-default admission or the full supervisor. See the raw results and
exact source pins in [the evidence package](evidence/source384-header-integration-20261003/README.md).

# Fixed A/B conditional norm composition

The canonical owner is
`ipfs_datasets_py.logic.autoformal.legal_full_norm_consequences_v1`.
Its `prepare_full_norm_consequences_v1` prepares the retained authored
Assign/Transfer/Approve component using the existing relational norm validator
and native-family Lean renderer. It accepts exactly two complete reports and
their original request bytes, with independent request and report SHA256 maps
keyed by `A` and `B`.

The supported alternatives are deliberately fixed:

- A: `forall r d s, P(Assign(r,d) or Transfer(r,d)) implies Approve(s,r)`.
- B: `forall r d s, P((Assign(r,d) or Transfer(r,d)) implies Approve(s,r))`.

Both original declarations survive unchanged in separate namespaces sharing
one interpretation prelude. A's approval theorem requires the explicit
unverified whole-norm premise and exact permission premise. B retains its
permission operator. The result includes the three conditional theorem names,
source hash, body hashes and byte ranges, input commitments, producer pins,
assumptions, null governing choices, zero training/gold masks and false authority.

```python
from ipfs_datasets_py.logic.autoformal.legal_full_norm_consequences_v1 import (
    prepare_full_norm_consequences_v1,
)

prepared = prepare_full_norm_consequences_v1(
    reports,                    # {"A": complete_report_a, "B": complete_report_b}
    request_raw,                # {"A": original_request_a_bytes, "B": original_request_b_bytes}
    expected_request_sha256=request_pins,
    expected_report_sha256=report_pins,
)
```

Obtain the pins from independently retained input descriptors. Hashing an
arbitrarily modified input does not authenticate it: the module also requires
complete replay through `legal_relational_norm_v1`. It rejects altered bodies,
producer pins, fields, modal placement and argument order. It neither reads a
dataset nor writes a project, runs Lean, acquires resources, trains a model,
chooses a statutory interpretation or grants review authority. Compilation,
source fidelity and qualified legal review remain separate operations.

This extracts `actual_shape` and `joint_source` from the historical
`artifacts/legal-ir-full-norm-native-20261017-01/full_norm_native_replay.py`.
That original replay and its receipts stay unchanged. The small fixture
`tests/unit/logic/autoformal/fixtures/legal_full_norm_consequences_v1/`
retains its exact 3,503-byte Lean output and SHA256 provenance. The historical
native result is evidence for its original run; current source-text parity
tests do not constitute a new kernel execution or semantic review.

The profile is a narrow reusable composition owner, not an unrestricted norm
composer. New signatures, binders, relations or modal shapes require a separate
explicit profile and qualification. Existing shared/incremental corpus and
native build owners remain responsible for their own supported contracts.

# Patent Center Human Handoff — Operator Runbook

**Task:** `PATLAW-154`  
**Goal:** `PATLAW-G172`  
**Track:** filing-handoff  
**Code:** `ipfs_datasets_py.processors.domains.uspto.patent_center_handoff`  
**Classes:** `PatentCenterHandoff`, `FilingStateMachine`  
**Tests:** `tests/integration/processors/domains/uspto/test_patent_center_handoff.py`

This runbook describes the **human-controlled** Patent Center handoff after a
validated filing package exists (`PATLAW-153`). The processor never signs,
pays, files, controls a browser, stores credentials or sessions, or fabricates
receipts.

## Standing rules (fail-closed)

1. **Only a natural person uses Patent Center.** Training and live submission
   happen outside this process in the operator’s own browser session.
2. **No network / browser / session / payment interface** exists on the handoff
   surface. Forbidden capabilities raise
   `ForbiddenHandoffInterfaceError`.
3. **Exact package digest binding.** Human approval, export, user submission,
   and official artifacts must bind the same package digest. Material changes
   require a new handoff.
4. **Cannot advance past `exported`** without an **external human assertion**
   (`UserSubmissionAssertion` with `external_human_action=True`) that records
   the submitted digest.
5. **Cannot advance to `receipt-verified`** without **verified official
   artifacts**. At minimum a verified, non-fabricated Electronic
   Acknowledgement Receipt bound to the package digest is required.
   Payment-only evidence is insufficient.
6. **Content-free instructions.** Training and live step lists never include
   document bodies, passwords, cookies, API keys, or payment-instrument data.
7. **Content-free observability.** Logs and audits must not include private
   document text or credentials.

## State machine

States use hyphenated labels matching the program acceptance language:

| State | Meaning | How entered |
| --- | --- | --- |
| `draft` | Handoff opened; package digest bound | `PatentCenterHandoff.start_draft` |
| `validated` | Package compiler validated the package | `mark_validated` |
| `human-approved` | Named inventor/practitioner approved the **exact** digest | `record_human_approval` |
| `exported` | Local export descriptor + training/live instructions emitted | `export_for_patent_center` |
| `user-submitted` | Natural person asserted they submitted in Patent Center | `record_user_submission` |
| `receipt-verified` | Verified official artefacts bound and accepted | `verify_receipts` |
| `invalidated` | Digest drift or operator cancel | `invalidate` |

### Allowed transitions (only)

```
draft → validated → human-approved → exported → user-submitted → receipt-verified
```

Any other edge (skips, reverse, or automatic jump to receipt-verified) raises
`InvalidTransitionError`.

### Critical guards

| From → To | Required evidence |
| --- | --- |
| `exported` → `user-submitted` | External human assertion with matching submitted digest |
| `user-submitted` → `receipt-verified` | Verified acknowledgement artifact bound to package digest |

## Operator workflow

### 1. Preconditions

- Validated filing package from `FilingPackageCompiler` (`PATLAW-153`) with a
  stable `package_digest`.
- Named inventor and/or practitioner review responsibilities recorded on the
  handoff (`inventor_reviewer`, `practitioner_reviewer`).

### 2. Open and validate

```python
from ipfs_datasets_py.processors.domains.uspto.patent_center_handoff import (
    PatentCenterHandoff,
)

ho = PatentCenterHandoff()
rec = ho.start_draft(
    matter_id="matter:…",
    package_id="pkg:…",
    package_digest="<64-char sha256>",
    inventor_reviewer="…",
    practitioner_reviewer="…",
    started_at_utc="2025-06-01T10:00:00Z",
)
rec = ho.mark_validated(rec, actor="operator", at_utc="2025-06-01T11:00:00Z")
```

### 3. Human approval of the exact digest

```python
rec = ho.record_human_approval(
    rec,
    approver_name="Practitioner Name Esq",
    approved_at_utc="2025-06-01T12:00:00Z",
    statement="I approve this exact package digest for external Patent Center handoff.",
    role="practitioner",
)
```

### 4. Export and obtain content-free instructions

```python
rec = ho.export_for_patent_center(
    rec,
    exported_by="Practitioner Name Esq",
    exported_at_utc="2025-06-01T13:00:00Z",
    export_root_label="/path/to/local/export",
    file_digests={"spec.docx": "<sha256>", "spec.pdf": "<sha256>"},
)
# rec.training_instructions  — Patent Center training environment
# rec.live_instructions      — Patent Center production environment
```

Instructions tell the human to:

1. Open Patent Center (training or live) **themselves**.
2. Authenticate and complete MFA **themselves**.
3. Upload files from the local export root and confirm digests.
4. Sign and certify under 37 C.F.R. 11.18 as a natural person.
5. Pay fees through Patent Center (no payment interface here).
6. Press **Submit** themselves.
7. Download the Electronic Acknowledgement Receipt, payment receipt, and any
   USPTO-converted artifacts.
8. Return here and **record the submitted digest**.
9. Import verified official artifacts for receipt verification.

Published entry-point labels (never opened by this code):

- Live: `https://patentcenter.uspto.gov`
- Training: `https://patentcenter-training.uspto.gov`

### 5. After Patent Center — record submission

```python
rec = ho.record_user_submission(
    rec,
    asserted_by="Practitioner Name Esq",
    asserted_at_utc="2025-06-01T15:00:00Z",
    statement="I personally submitted this package in Patent Center and recorded the digest.",
    submitted_digest="<same package digest>",
    mode="live",  # or "training"
    confirmation_number="…",  # optional USPTO confirmation
    external_human_action=True,  # required
)
```

Without `external_human_action=True`, the transition is refused
(`ExternalHumanAssertionRequiredError`). The system cannot invent a
submission.

### 6. Import and verify official artifacts

```python
from ipfs_datasets_py.processors.domains.uspto.patent_center_handoff import (
    OfficialArtifact,
    OfficialArtifactKind,
    ArtifactVerificationStatus,
)

ack = OfficialArtifact(
    artifact_id="art:ack:…",
    kind=OfficialArtifactKind.ACKNOWLEDGEMENT,
    content_digest="<sha256 of receipt bytes>",
    package_digest="<package digest>",
    verification_status=ArtifactVerificationStatus.VERIFIED,
    imported_at_utc="2025-06-01T16:00:00Z",
    imported_by="docket-clerk",
    source_receipt_id="rcpt:user-import:…",
    fabricated=False,
)
rec = ho.bind_official_artifact(rec, ack)
# optionally bind payment_receipt and uspto_converted_pdf artifacts

rec = ho.verify_receipts(
    rec, actor="docket-clerk", at_utc="2025-06-01T17:00:00Z"
)
# rec.state == "receipt-verified"
```

Full cross-check of identifiers, conversion differences, and ledger events is
owned by `PATLAW-155` (`FilingReceiptReconciler`). This handoff only enforces
that verified official artefacts exist before `receipt-verified`.

### 7. Invalidation

```python
rec = ho.invalidate(
    rec,
    actor="operator",
    at_utc="2025-06-01T18:00:00Z",
    reason="material package inputs changed; new package digest required",
)
```

Further transitions raise `HandoffInvalidatedError`.

## Proving the closed interface surface

```python
from ipfs_datasets_py.processors.domains.uspto.patent_center_handoff import (
    prove_no_forbidden_interfaces,
)

proof = prove_no_forbidden_interfaces()
assert proof["no_network_browser_session_payment"] is True
```

Integration tests assert the same property and scan the module source for
forbidden imports (`requests`, `httpx`, `selenium`, `playwright`, …).

## Validation

```bash
python -m pytest tests/integration/processors/domains/uspto/test_patent_center_handoff.py -q
```

## What this module never does

| Action | Result |
| --- | --- |
| Login / MFA / cookie storage | Forbidden |
| Browser automation (Selenium/Playwright) | Forbidden |
| Network client to Patent Center | Forbidden |
| Pay fees / payment instrument handling | Forbidden |
| Sign or certify under Rule 11.18 | Forbidden |
| Press Submit / mark submitted without human assertion | Forbidden |
| Fabricate training or live receipts | Forbidden |
| Claim that filing occurred without artefacts | Forbidden |

## Related components

| Component | Role |
| --- | --- |
| `filing_package.py` (`PATLAW-153`) | Compile/validate content-addressed package |
| `patent_center_handoff.py` (`PATLAW-154`) | Human handoff state machine (this runbook) |
| `filing_receipt_reconciler.py` (`PATLAW-155`) | Deep receipt / conversion reconciliation |
| `providers/patent_center_export.py` | Import of user-supplied Patent Center exports |
| `workflow_processor.py` | Preflight human gate for submission assurance |

## Disclaimer

This handoff is **decision support**. It is not legal advice, not a filing
authorization, and not proof of USPTO acceptance until verified official
acknowledgement evidence is bound and (where applicable) reconciled under
`PATLAW-155`.

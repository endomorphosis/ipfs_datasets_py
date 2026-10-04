# Xaman Vendor Evidence Intake Request

Task: `PORTAL-CXTP-152`

Template: `security_ir_artifacts/corpora/xaman-app/vendor-evidence-intake-template.json`

This document prepares the authorized, redacted intake request needed before the native, backend, build, and XRPL/RPC blockers can be reviewed. It is a request package only. It does not claim access to vendor-only systems, does not assert that vendor-only evidence exists, and does not treat any requested statement as true until a vendor-authorized submission is received, redacted, reviewed, and bound to an evidence manifest.

Acceptance topics covered: release provenance, native vault/biometric policy, backend payload single-use/conflict/expiry semantics, signed-build attestation, test-device trace review, XRPL/RPC trust assumptions, responsible-disclosure routing, accountable owners, expiry, and review criteria.

## Authorization Boundary

- Status: `prepared_not_sent_authorization_required`
- Prepared on: `2026-07-11T00:00:00Z`
- Intake expires: `2026-08-10T00:00:00Z`
- Required authorization before transmission: project security lead approval, legal or vendor-relations approval, and a verified vendor-approved disclosure or evidence-exchange channel.
- Permitted content: redacted attestations, signed digests, screenshots with secrets removed, policy excerpts, test summaries, trace summaries, and owner signoff.
- Prohibited content: seed material, private keys, passcodes, biometric templates, unredacted user data, production credentials, raw payload bodies, raw transaction blobs, private backend endpoints, signing keystore material, or exploit steps beyond what the vendor explicitly authorizes.

## Requested Evidence Categories

| Category | Request | Required redaction |
| --- | --- | --- |
| Release provenance | Identify the vendor release artifact family, version, build timestamp, source revision or internal build label, dependency lock inputs, CI job identity, signing certificate digest, store package digest where shareable, and release approval owner. | No signing keys, keystore passwords, CI secrets, private repository URLs, or unpublished source contents. |
| Native vault and biometric policy | Provide the Android/iOS native vault implementation policy, keystore/keychain accessibility class, hardware-backed key policy, migration behavior, biometric prompt/enrollment-change policy, and tests for passcode/biometric fallback. | No seeds, private keys, passcodes, biometric samples, device unlock credentials, or raw secure-enclave material. |
| Backend payload semantics | Provide the payload API contract or equivalent evidence for authorization, single-use resolution, PATCH conflict handling, replay rejection, expiry enforcement, cancellation/decline behavior, and concurrent submit races. | No production bearer tokens, raw payload bodies, account addresses, user identifiers, private API hostnames, or database rows. |
| Signed-build attestation | Provide a signed or owner-approved build attestation tying the release artifact to source/build inputs, dependency locks, native modules, CI environment, store upload, and signing certificate digest. | No private signing material, passwords, service-account credentials, internal CI logs with secrets, or upload tokens. |
| Test-device trace review | Provide vendor-reviewed traces or trace summaries for authentication, vault open, review, signing decision, backend patch, submit result, cancellation, expiry, replay, reconnect, and network-change paths. | No seeds, addresses, payload UUIDs, transaction blobs, raw endpoint URLs, push tokens, crash identifiers, or user data. |
| XRPL/RPC trust assumptions | State which XRPL node/RPC endpoints are trusted, how network identity and ledger finality are checked, what endpoint compromise means for the model, and whether quorum or fallback behavior is used. | No private endpoint credentials, internal node access tokens, or customer-specific ledger activity. |
| Responsible-disclosure routing | Provide the vendor-approved security contact, escalation route, embargo expectations, allowed evidence-handling channel, and rules for sending counterexamples or vulnerability detail. | No public disclosure or exploit reproduction detail until the route and authorization are confirmed in writing. |

## accountable owners

The intake request requires an accountable owner for each acceptance area before evidence can be promoted:

- `release_provenance`: vendor release engineering owner and internal evidence custodian.
- `native_vault_biometric_policy`: vendor mobile security owner and internal mobile-model reviewer.
- `backend_payload_semantics`: vendor backend/API owner and internal payload-model reviewer.
- `signed_build_attestation`: vendor build/release owner and internal release-security reviewer.
- `test_device_trace_review`: vendor QA/security validation owner and internal runtime-evidence reviewer.
- `xrpl_rpc_trust_assumptions`: vendor ledger-infrastructure owner and internal XRPL-model reviewer.
- `responsible_disclosure_routing`: vendor security-response owner, internal security lead, and legal/vendor-relations approver.

Owner signoff must include role, organization, date, evidence category, authorization statement, and whether the submission may be retained in the redacted corpus.

## Review Criteria

Evidence is acceptable for the next governance task only when all of these conditions hold:

- The submission arrives through a verified vendor-authorized channel before `2026-08-10T00:00:00Z`.
- The submitter has authority for the category or names the accountable owner who does.
- Every artifact is redacted according to the template and contains no prohibited secret or personal data.
- Each claim is bound to a digest, attestation, reviewed trace summary, policy excerpt, test result, or owner statement with date and scope.
- Release provenance and signed-build evidence do not rely on the public Testnet verifier build as vendor-release equivalence.
- Backend payload semantics explicitly cover single-use, conflict, expiry, cancellation/decline, replay, and concurrent race behavior.
- Native vault/biometric evidence explicitly covers keystore/keychain policy, hardware-backed settings where applicable, biometric enrollment-change behavior, fallback behavior, and migration risk.
- XRPL/RPC assumptions explicitly describe endpoint trust, network binding, ledger finality, fallback behavior, and modeled compromise impact.
- Responsible-disclosure routing is approved before counterexamples, vulnerability hypotheses, or exploit detail are sent.
- Reviewers record `accepted`, `needs_clarification`, or `rejected` without upgrading any request item to fact until the evidence manifest and review are created by `PORTAL-CXTP-153`.

## Non-Claims

This intake package does not prove Xaman secure, does not reproduce a vendor release, does not validate the backend service, does not validate native vault or biometric implementation, and does not approve production release use. Until vendor-authorized evidence is collected and reviewed, native, backend, build, and XRPL/RPC assumptions remain blockers.

# Xaman Self-Hosted Endpoint-Rebind Candidate

Task: `PORTAL-CXTP-154`

This is a verifier-only source candidate created from the public Xaman source
commit `942f43876265a7af44f233288ad2b1d00841d5fa`. It is not an XRPL Labs
release, is not production-usable, and does not establish wallet security.

## Why A Source Candidate Is Required

The unmodified public source has two routes that prevent a meaningful
self-hosted-ledger run:

- `NetworkService.normalizeEndpoint` sends non-default nodes through the
  vendor custom-node proxy.
- The Android `HTTPClientFactory` redirects an untrusted HTTP host to a vendor
  default host.

Changing a displayed Testnet endpoint alone would therefore not prove that
the app has avoided vendor or public Testnet services.

## Candidate Controls

The candidate only changes these tracked source files:

| File | Verifier-only control |
| --- | --- |
| `src/common/constants/endpoints.ts` | Routes API requests to an Android-emulator local API bridge. |
| `src/common/constants/network.ts` | Replaces the public Testnet rail with a self-hosted network using ID `777777`. |
| `src/services/NetworkService.ts` | Forces the local ledger bridge and rejects every other selected network ID before a connection is made. |
| `android/app/src/main/java/libs/common/HTTPClientFactory.java` | Replaces the vendor host allowlist and default fallback with the Android-emulator local host. |

The source debug manifest already declares cleartext support. This is a
debug-only transport prerequisite and is not evidence of production transport
security.

## Evidence

- Candidate manifest: `security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/endpoint-rebound-candidate.json`
- Manifest CID: `sha256:8ecdf83286a89d1b5d4862200ba5dab3c8ba85e6e6310e80ef1e6cbf1d8b9e88`
- Materialized source: `/home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/self-hosted-endpoint-rebind-candidate`

The generated manifest stores source and candidate file digests plus symbolic
route roles. It deliberately does not claim that a bridge, Android build, or
runtime trace exists.

## Required Next Evidence

1. An independent reviewer compares the materialized candidate against the
   pinned source and signs a review record that confirms the four controls and
   the absence of public or vendor endpoint fallback.
2. A reviewed loopback-only API and WebSocket bridge connects the emulator to
   a self-hosted `rippled` container without a public egress path.
3. A debug build records build inputs and APK digest. The Firebase-disabled
   verifier boundary remains separate from vendor-release equivalence.
4. A redacted trace proves the selected network category, review flow,
   signature decision, submit result, cancellation, expiry, replay, reconnect,
   and network-change handling. It must exclude seeds, account addresses,
   payloads, transaction blobs, credentials, and raw endpoints.
5. The existing runtime-conformance validator consumes only that reviewed,
   redacted trace. A missing category remains a block.

## Non-Claims

This candidate does not prove that the Xaman wallet is secure, that a vendor
release behaves the same way, that an XRPL transaction reached finality, or
that the XRPL Labs backend is secure. Those claims still require independent
runtime evidence and, for vendor-release assurance, the authorized evidence
request defined by `PORTAL-CXTP-152`.

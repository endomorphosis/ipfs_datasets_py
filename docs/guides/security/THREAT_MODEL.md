# Threat model — IPFS Datasets Python

| Field | Value |
| --- | --- |
| Interface | `IPFSDatasetsThreatModel@1` |
| Task | `IPFSDOC-060` |
| Status | `canonical` |
| Owner | security; architecture; mcp-security; logic-policy |
| Source of truth | Current package topology under `ipfs_datasets_py/`; ADRs [ADR-003](../../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md); [INTEGRATION_BOUNDARIES.md](../../architecture/INTEGRATION_BOUNDARIES.md); [SYSTEM_CONTEXT.md](../../architecture/SYSTEM_CONTEXT.md); [EXTERNAL_PROVERS.md](../../architecture/logic/EXTERNAL_PROVERS.md); [GOVERNED_AUTHORIZATION.md](../../architecture/logic/GOVERNED_AUTHORIZATION.md); [POLICY_AND_AUTHORIZATION.md](../../architecture/mcp/POLICY_AND_AUTHORIZATION.md); [PROOF_ATTESTATION_AND_ZKP.md](../../architecture/logic/PROOF_ATTESTATION_AND_ZKP.md); [STORAGE_CACHING_AND_BACKENDS.md](../../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md); [FILE_AND_MULTIMEDIA.md](../../architecture/processing/FILE_AND_MULTIMEDIA.md); [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](../../architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md); [INTERFACES_AND_TRANSPORTS.md](../../architecture/mcp/INTERFACES_AND_TRANSPORTS.md); [SECRETS_AND_CREDENTIALS.md](SECRETS_AND_CREDENTIALS.md) |
| Last verified | 2026-08-03 |
| Audience | security reviewer, architect, operator, developer, agent |
| Related | [security_governance.md](security_governance.md), [audit_logging.md](audit_logging.md), planned `AUDIT_PROVENANCE_AND_INCIDENTS.md` |
| Review cadence | after major surface changes (MCP transports, provers, wallet, authz, parsers) or at least semi-annually |

> **Hard rule:** This document describes **current** trust boundaries, controls,
> and residual risks. It does **not** claim production security for optional,
> simulated, or unprovisioned paths. **Include no real secrets** in this file
> or any linked example. Companion credential lifecycle:
> [SECRETS_AND_CREDENTIALS.md](SECRETS_AND_CREDENTIALS.md).

---

## 1. Purpose

Map **trust boundaries** and **threats** for the product’s high-risk surfaces—

1. parsers and untrusted structured input
2. archives (zip/tar/WARC and related)
3. models (LLM, embedding, OCR, neural helpers)
4. backends (IPFS, vector stores, graph DBs, optional submodules)
5. network transports (stdio, HTTP/FastAPI, gRPC, P2P/libp2p)
6. native provers and ZKP binaries
7. caches
8. credentials and secrets
9. delegated capabilities (UCAN, one-time authz capabilities)
10. PII and privacy-sensitive content
11. generated content (LLM output, synthetic proof candidates, model drafts)

—to **current controls**, **tests**, **assumptions**, **residual risks**,
**owners**, **detection**, **revocation/rotation**, and **recovery**.

Facts prefer: tests and schemas → current implementation → packaging → accepted
ADRs → maintained guides → historical material
([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

---

## 2. Security goals and non-goals

### 2.1 Goals

| Goal | Meaning in this product |
| --- | --- |
| **Fail-closed trust** | Missing, unknown, or unmodeled evidence never becomes silent allow, silent prove, or silent “production ready” ([ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)) |
| **Layered authority** | Parse ≠ validate ≠ retrieve ≠ sat ≠ proof ≠ policy ≠ authorization ≠ dispatch ≠ monitoring ≠ receipt ([ADR-003](../../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md)) |
| **Least privilege for tools** | MCP tools wrap domain logic; discovery and listing never imply execution rights |
| **Secret hygiene** | No secrets in docs, fixtures, or default logs; redaction on error and public views |
| **Integrity of identity** | Content identity (CID / digests) is not rewritten by cache hits or transport success |
| **Delegated capability honesty** | UCAN chains and one-time capabilities expire, revoke, and do not auto-promote proof to allow |

### 2.2 Non-goals

- Guaranteeing every optional extra, submodule, or prover binary is present.
- Treating simulated ZKP / stub backends as cryptographically sound.
- Providing legal advice or jurisdiction-complete compliance certification.
- Claiming transport feature parity across stdio / HTTP / gRPC / P2P.
- Replacing operator SIEM, OS hardening, or cloud IAM with package code alone.
- Documenting real secret values, private keys, or live API tokens.

### 2.3 Threat actors (simplified STRIDE-oriented)

| Actor | Intent | Typical access |
| --- | --- | --- |
| **Malicious / untrusted input author** | Craft files, archives, URLs, IR, or tool args to crash, escape, or confuse authority | Public datasets, scrapers, user uploads, MCP params |
| **Malicious MCP / API client** | Invoke tools beyond grant, replay intents, escalate via pipeline soft-skip | Stdio host, HTTP, P2P peer |
| **Compromised credential holder** | Use leaked tokens, vault material, or JWT secrets | Env, vault file, CI secrets store |
| **Network attacker** | Observe, replay, or tamper with transport and remote caches | Path between client and service / peers |
| **Malicious or compromised prover/binary** | Forge solver output, DoS via pathological input, supply-chain replace binary | Host PATH, lazy install roots, submodule assets |
| **Insider / misconfigured operator** | Disable gates, log secrets, treat UNKNOWN as green | Deploy config, `SECRET_KEY`, pipeline flags |
| **Supply-chain attacker** | Poison dependencies, Docker base images, or prover installers | Package install, CI, submodule remotes |

---

## 3. Trust boundary map

```text
                         ┌─────────────────────────────────────┐
                         │  UNTRUSTED OUTSIDE                  │
                         │  Public web · archives · HF Hub ·   │
                         │  MCP clients · peers · solver stdout│
                         │  LLM/OCR output · user files/URLs   │
                         └──────────────────┬──────────────────┘
                                            │
          trust boundary A: process / network edge
                                            │
                         ┌──────────────────▼──────────────────┐
                         │  CARRIER LAYER                      │
                         │  stdio · HTTP/FastAPI · gRPC · P2P  │
                         │  auth handshake · body size · CORS  │
                         └──────────────────┬──────────────────┘
                                            │
          trust boundary B: policy / authorization
                                            │
                         ┌──────────────────▼──────────────────┐
                         │  CONTROL PLANE (optional attach)    │
                         │  DispatchPipeline · UCAN · risk ·   │
                         │  IntentAuthorizationService ·       │
                         │  PreInvocationEnforcement           │
                         └──────────────────┬──────────────────┘
                                            │
          trust boundary C: domain execution
                                            │
                         ┌──────────────────▼──────────────────┐
                         │  DOMAIN ENGINES (in-process)        │
                         │  processors · logic · wallet ·      │
                         │  embeddings · storage routers       │
                         └──────────────────┬──────────────────┘
                                            │
          trust boundary D: optional / native / remote
                                            │
         ┌──────────────────┬───────────────┼───────────────┬──────────────┐
         ▼                  ▼               ▼               ▼              ▼
   Native provers      IPFS / kit      Vector/graph     Model routers   Caches
   Z3/CVC5/Lean/…      backends        DBs · HF          LLM/OCR         local/P2P
   Groth16 binary      cluster         Neo4j                             remote
```

| Boundary | Crosses | Trust default |
| --- | --- | --- |
| **A — edge** | Anything from clients, network, or files into the process | **Untrusted** until validated |
| **B — control plane** | Intent before tool body runs | Fail-closed when gates **configured**; pass-through if **no** pipeline attached (not an allow decision) |
| **C — domain** | Validated calls into library code | Trusted for *code integrity of this package*, not for *truth of content* |
| **D — external** | Submodules, daemons, solvers, model APIs, remote caches | **Untrusted** for security decisions; capability must be probed |

### 3.1 Assets

| Asset | Why it matters | Primary owners |
| --- | --- | --- |
| API keys, JWT/`SECRET_KEY`, vault ciphertext, DID key material | Impersonation, lateral move | Operators; mcp-server; optimizers.security |
| UCAN delegations and one-time authz capabilities | Side-effect rights | mcp-security; logic-policy |
| Proof envelopes, corpus roots, revocation snapshots | False “proved” / release green | logic-policy; security-models |
| Wallet records and redacted-derived artifacts | PII / confidentiality | wallet |
| Dataset bytes, CIDs, pin sets | Integrity and availability | storage; architecture |
| Audit / Event DAG / policy audit logs | Detection and forensics | mcp-server; audit |
| Host resources (CPU, disk, network) | DoS / cost abuse | operators |

### 3.2 Trust assumptions (global)

1. Host OS, container isolation, and CI secret stores are outside this package’s authority.
2. SHA-256 / content-addressed digests used for identity are collision-resistant for product purposes.
3. Operators set production `SECRET_KEY` / JWT secrets; development defaults are **not** production-safe.
4. Optional MCP `DispatchPipeline` is **opt-in**; absence means no MCP++ pre-dispatch gate, not “authorized.”
5. Simulated ZKP and educational prover modes do **not** provide soundness or zero-knowledge.
6. Cache hits and green health endpoints do **not** establish proof or authorization.
7. Empty git submodules and missing binaries are **availability** failures, not silent success.

---

## 4. Surface-by-surface threat catalog

Each subsection maps threats → controls → tests (representative) → residual
risk → owner → detection → revoke/rotate → recovery.

### 4.1 Parsers and untrusted structured input

| Item | Detail |
| --- | --- |
| **Scope** | JSON/YAML/IR schemas, MCP tool arguments, PDF/HTML/XML extractors, legal dockets, config files, CID-native artifacts |
| **Threats** | Injection into templates or shell; schema confusion; billion-laughs / huge payloads; type confusion promoting parse success to “valid claim”; path traversal via file fields |
| **Controls** | Layered authority: **parse ≠ validation ≠ proof** (ADR-003); MCP `validators.py` length/security checks; fail-closed on malformed IR; body size limits (`MCPPP_MAX_BODY_BYTES` on FastAPI); structured error envelopes |
| **Tests** | Validator unit coverage under `mcp_server`; IR identity / canonicalization tests under `tests/` / logic packages; security IR inventory tests (`tests/unit/tools/test_security_ir_artifact_inventory.py`) |
| **Assumptions** | Callers do not treat parse `ok` as semantic truth or allow |
| **Residual risk** | Heterogeneous historical parsers; not every domain path shares one validator; native PDF/media parsers may still panic or allocate heavily |
| **Owner** | Domain package owners (processors, logic.ir_*, mcp-server validators) |
| **Detection** | Validation error metrics; tool error rates; audit of reject reasons |
| **Revoke / rotate** | N/A for pure parsers; revoke bad schemas/profiles by pinning new IR/profile IDs |
| **Recovery** | Reject payload; do not execute; quarantine bad artifacts by CID; reprocess with stricter profile |

### 4.2 Archives (zip/tar family, WARC, web archive fetch)

| Item | Detail |
| --- | --- |
| **Scope** | `archive_handler` (file conversion), WARC/Common Crawl, Wayback / archive.is paths, multimedia unpack |
| **Threats** | Zip slip / path traversal; archive bombs (nested/high ratio); malicious members executing via path write; untrusted remote archive content treated as evidence of truth; SSRF via archive URL fetch |
| **Controls** | Treat paths/URLs as untrusted ([FILE_AND_MULTIMEDIA.md](../../architecture/processing/FILE_AND_MULTIMEDIA.md), [WEB_ARCHIVING_AND_LEGAL_INGESTION.md](../../architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md)); optional resource limits on batch processors; provenance fields for archive source ≠ authorization; fail methods on challenge/block pages |
| **Tests** | Web archiving unit tests (`tests/unit/web_archiving/`); converter/processor tests where present; integration tests for scraper engines when provisioned |
| **Assumptions** | Operators do not unpack untrusted archives as root or into shared system paths |
| **Residual risk** | Native extractors and submodule converters may not share one zip-slip suite; archive bomb limits are not uniform across every backend |
| **Owner** | processors (file conversion, web_archiving); multimedia submodule owners for converter trees |
| **Detection** | Extract failures; disk growth alerts; scraper challenge detection |
| **Revoke / rotate** | Unpin or delete bad CIDs; revoke publication credentials if archive publish path was abused |
| **Recovery** | Delete extracted tree; re-fetch from alternate archive method; mark evidence package with degraded provenance |

### 4.3 Models (LLM, embedding, OCR, neural helpers)

| Item | Detail |
| --- | --- |
| **Scope** | `llm_router`, SyMAI / neurosymbolic keys, embedding routers, OCR engines (Tesseract/Surya/EasyOCR/TrOCR), GraphRAG model stages |
| **Threats** | Prompt injection via retrieved or archived text; data exfiltration into model providers; treating model confidence as proof; model supply-chain / poisoned weights; PII sent to third-party APIs |
| **Controls** | Model output is **retrieval/candidate layer only** (ADR-003); wallet redacted analysis defaults (`wallet` redaction APIs); optional hermetic import flags; capability extras separate from base install; fail closed when models unavailable (feature degrade, not fake success) |
| **Tests** | Router and embedding tool tests; wallet redaction paths; optional model tests skipped when extras missing |
| **Assumptions** | Deployment chooses data-residency-appropriate providers; production does not log full prompts with secrets |
| **Residual risk** | Many tools can still pass raw text to models when operators enable them; redaction is pattern-based, not complete PII discovery |
| **Owner** | ml/embeddings/optimizers owners; wallet for privacy-preserving paths; operators for provider contracts |
| **Detection** | Outbound API error/rate metrics; unexpected egress; cost anomalies |
| **Revoke / rotate** | Rotate provider API keys ([SECRETS_AND_CREDENTIALS.md](SECRETS_AND_CREDENTIALS.md)); disable model extras |
| **Recovery** | Invalidate tainted embeddings/indexes; re-embed from redacted sources; revoke capabilities issued on model-only “evidence” |

### 4.4 Backends (IPFS, storage routers, vector/graph stores, submodules)

| Item | Detail |
| --- | --- |
| **Scope** | `ipfs_backend_router`, kit/accelerate submodules, pin/cluster, FAISS/Qdrant/ES, Neo4j-compatible paths, HF publication helpers |
| **Threats** | Wrong backend selection; malicious remote content with valid CID; cluster/pin retention confusion as integrity; unauthenticated remote vector DB; submodule code supply chain |
| **Controls** | Identity vs location vs cache separation ([STORAGE_CACHING_AND_BACKENDS.md](../../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md)); optional enable flags for kit; content-addressed identity (ADR-001); offline degrade without inventing pins; integration boundary ownership ([INTEGRATION_BOUNDARIES.md](../../architecture/INTEGRATION_BOUNDARIES.md)) |
| **Tests** | Backend router and storage tests; pin/cluster mocks; vector store tool tests under `tests/` |
| **Assumptions** | External daemons and DBs have their own ACLs; operators authenticate remote stores |
| **Residual risk** | Peer or daemon compromise serves unexpected bytes for a CID only if hash checks are bypassed—callers must verify CID when crossing trust domains |
| **Owner** | storage / architecture; vector_stores; knowledge_graphs; external kit owners |
| **Detection** | Backend error rates; pin failures; integrity mismatch logs |
| **Revoke / rotate** | Rotate remote DB credentials; re-pin from trusted sources; update submodule pins after review |
| **Recovery** | Fail over backend; rebuild index from canonical CIDs; clear poisoned caches (§4.7) |

### 4.5 Network transports

| Item | Detail |
| --- | --- |
| **Scope** | MCP stdio (FastMCP), HTTP/FastAPI (`fastapi_service.py`), gRPC stubs, Trio/AnyIO hosts, MCP++ / libp2p / P2P |
| **Threats** | Unauthenticated tool invocation on open HTTP; CSRF/CORS misconfig; host header attacks; oversized bodies; SSE connection exhaustion; P2P peer spoofing; transport success confused with authorization |
| **Controls** | Transport ≠ contract ≠ domain layering ([INTERFACES_AND_TRANSPORTS.md](../../architecture/mcp/INTERFACES_AND_TRANSPORTS.md)); production requires `SECRET_KEY`; CORS/`MCP_ALLOWED_HOSTS` env gates; body and SSE limits; optional UCAN required unless `MCPPP_ALLOW_UNSIGNED_DELEGATIONS`; timeouts (`MCPPP_EXEC_TIMEOUT_S`); error context sanitization on server |
| **Tests** | FastAPI / dual-runtime tests; MCP integration suites under `tests/migration_tests/` and `tests/`; P2P service tests when present |
| **Assumptions** | Stdio is as trusted as the local host process parent; remote HTTP must be network-isolated or authenticated |
| **Residual risk** | Feature parity gaps across transports; default local bind settings unsafe if exposed publicly without reverse proxy TLS and auth |
| **Owner** | mcp-server; operators for edge TLS and network policy |
| **Detection** | HTTP 401/403 rates; health/ready vs actual authz denials; P2P state snapshots |
| **Revoke / rotate** | Rotate `SECRET_KEY` / JWT secrets; revoke UCAN delegations; close P2P services |
| **Recovery** | Drain connections; restart with corrected config; invalidate sessions/tokens |

### 4.6 Native provers and ZKP binaries

| Item | Detail |
| --- | --- |
| **Scope** | Z3, CVC5, Vampire, E, Lean, Coq, CEC/Talos/ShadowProver assets, Groth16/Provekit binaries, ITP hammers |
| **Threats** | Forged solver stdout accepted as theorem proof; binary replacement; DoS via pathological formulas; simulated ZKP treated as real; toxic trusted-setup waste; timeout exhaustion |
| **Controls** | **Solver success = candidate only; kernel acceptance = theorem authority** ([EXTERNAL_PROVERS.md](../../architecture/logic/EXTERNAL_PROVERS.md)); attestation kinds non-substitutable ([PROOF_ATTESTATION_AND_ZKP.md](../../architecture/logic/PROOF_ATTESTATION_AND_ZKP.md)); UNKNOWN/NOT_MODELED/unavailable fail closed (ADR-004); timeouts and process-group ownership; capability probing without import-time side effects; explicit Groth16 opt-in vs simulation default |
| **Tests** | Logic external prover / hammer tests; crypto_exchange security model tests under `tests/logic/security_models/`; ZKP module vectors under `docs/security_verification/test_vectors/` |
| **Assumptions** | Operators install intended binaries; simulation backends never feed production release gates |
| **Residual risk** | Lazy install paths increase supply-chain surface; not all solvers reconstruct to a trusted ITP kernel |
| **Owner** | logic-proof; security-models; operators for binary provenance |
| **Detection** | Prover error/timeout tallies; attestation kind labels on envelopes; release gate failures on UNKNOWN |
| **Revoke / rotate** | Revoke proof corpus entries and VK bindings; rotate artifact roots; invalidate cache keys for prover results |
| **Recovery** | Re-run under pinned binary checksum; mark portfolio UNKNOWN; block release |

### 4.7 Caches

| Item | Detail |
| --- | --- |
| **Scope** | `caching/` (`CacheManager`, distributed/P2P cache), IPLD block cache, router instance cache, decision caches for authz, prover result caches |
| **Threats** | Cache poisoning; serving stale allow decisions; P2P shared-secret weakness; treating cache hit as content authenticity; secret material cached in plaintext |
| **Controls** | Cache must not redefine content identity ([STORAGE_CACHING_AND_BACKENDS.md](../../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md)); authz decision cache tenant-safe and bound to revocation roots ([GOVERNED_AUTHORIZATION.md](../../architecture/logic/GOVERNED_AUTHORIZATION.md)); P2P cache shared secret via env (`IPFS_DATASETS_PY_CACHE_P2P_SHARED_SECRET` / related); size/TTL eviction |
| **Tests** | Cache manager/engine tests; P2P cache guides under `docs/guides/p2p/`; related unit tests |
| **Assumptions** | Shared secrets for P2P cache are rotated and not committed |
| **Residual risk** | Multi-process cache coherence varies; remote caches may be best-effort |
| **Owner** | caching; storage; logic-policy for decision cache |
| **Detection** | Unexpected hit-rate cliffs; integrity mismatch on revalidation |
| **Revoke / rotate** | Rotate P2P cache secrets; bump cache key namespaces; flush decision cache on revocation |
| **Recovery** | Clear local/remote cache tiers; rebuild from CID sources; re-evaluate authorization without cache |

### 4.8 Credentials and secrets

| Item | Detail |
| --- | --- |
| **Scope** | Env-injected API keys, `SECRET_KEY` / `JWT_SECRET_KEY`, Discord/Twilio/SMTP/HF tokens, `SecretsVault`, optimizers `SecretsManager`, Gmail/legal email helpers, GitHub tokens for error reporting |
| **Threats** | Leak via logs, issues, MCP error payloads, git history; weak/default secrets; vault file theft; confused deputy via env injection |
| **Controls** | See [SECRETS_AND_CREDENTIALS.md](SECRETS_AND_CREDENTIALS.md): env-only injection, vault encryption (AES-GCM via DID key), Fernet secrets manager with rotation metadata, server `_sanitize_error_context`, pattern redaction, no secrets in this documentation |
| **Tests** | Auth tools tests (`tests/original_tests/_test_auth_tools.py` lineage); secrets manager unit expectations; FastAPI production secret-key guards |
| **Assumptions** | Host file permissions and secret managers (GitHub Actions secrets, k8s secrets) are correctly configured |
| **Residual risk** | Development defaults (e.g. enterprise API dev JWT fallback) unsafe if copied to production; key-name redaction may miss free-text secrets in values |
| **Owner** | operators; mcp-server; optimizers.security; messaging/wallet for domain tokens |
| **Detection** | Secret scanning in CI (operator-owned); anomalous auth failures; unexpected outbound with new tokens |
| **Revoke / rotate** | Immediate provider revoke + env/vault update + restart; JWT blacklist / short TTL |
| **Recovery** | Rotate all co-tenant secrets; invalidate sessions; audit Event DAG / policy logs for abuse window |

### 4.9 Delegated capabilities (UCAN and governed one-time capabilities)

| Item | Detail |
| --- | --- |
| **Scope** | `ucan_delegation.py` (`DelegationManager`, `RevocationList`), NL-UCAN gate, `AuthorizationCapability@1` one-time consumption, intent CID binding |
| **Threats** | Replay of consumed capability; use after revoke/expiry; overly broad attenuations; unsigned delegations when allowed; confusing pipeline allow with governed allow |
| **Controls** | Pipeline stages deny without tool execution ([POLICY_AND_AUTHORIZATION.md](../../architecture/mcp/POLICY_AND_AUTHORIZATION.md)); revocation list persist/load; exact-context pre-dispatch revalidation and atomic consume ([GOVERNED_AUTHORIZATION.md](../../architecture/logic/GOVERNED_AUTHORIZATION.md)); proof ≠ authorization; optional `MCPPP_ALLOW_UNSIGNED_DELEGATIONS` must stay off in production |
| **Tests** | UCAN / admissibility integration under logic tests; MCP policy stage tests where present |
| **Assumptions** | Hosts compose gates intentionally; default server without pipeline is not a grant |
| **Residual risk** | Soft-skip when subsystems unconfigured can yield pass-through; multi-node revocation list sync is operator responsibility |
| **Owner** | mcp-security; logic-policy |
| **Detection** | Deny tallies; `denied_by` stage; capability consume failures; revoked CID hits |
| **Revoke / rotate** | `RevocationList.revoke` / `revoke_chain`; persist revlist; rotate DID keys; invalidate decision cache |
| **Recovery** | Re-issue narrower delegations; force re-auth; disable unsigned mode; incident review of receipts |

### 4.10 PII and privacy-sensitive content

| Item | Detail |
| --- | --- |
| **Scope** | Wallet documents, legal dockets/emails, SMS/voice bridges, audit payloads, scraped personal data |
| **Threats** | PII in logs/metrics/traces; unintended model training/exfil; cross-tenant cache leakage; oversharing GraphRAG graphs |
| **Controls** | Wallet redacted-by-default analysis and redacted GraphRAG backends; MCP tool redacted authorization views; OTel low-cardinality attributes guidance ([AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md)); legal ingest treats public web as untrusted and flags PII packaging risk |
| **Tests** | Wallet service redaction unit paths; wallet MCP tools for redacted analysis |
| **Assumptions** | Operators classify datasets and apply retention outside the package when required by law |
| **Residual risk** | Pattern redaction is incomplete; many MCP tools still return raw domain text when not using wallet redaction APIs |
| **Owner** | wallet; legal-data processors; operators/DPO as applicable |
| **Detection** | Redaction_count metrics; DLP tools outside package; audit sampling |
| **Revoke / rotate** | Delete or re-encrypt wallet artifacts; rotate encryption keys; purge logs containing PII |
| **Recovery** | Re-process with stricter redaction; notify per incident process (sibling audit/incident guide) |

### 4.11 Generated content

| Item | Detail |
| --- | --- |
| **Scope** | LLM drafts, synthetic datasets, auto-healed patches, solver “proof candidates,” GraphRAG narratives, agent task outputs |
| **Threats** | Authority inflation (draft → “proved” / “approved”); poisoned training data loops; malicious code in autofix PRs; plagiarized or unsafe legal conclusions |
| **Controls** | Explicit candidate layer (ADR-003); non-authoritative attestation kinds (`simulation`, `artifact-membership`); auto-healing security constraints for CI ([auto_healing_security.md](auto_healing_security.md)); Profile G advisory placement fail-closed for side effects |
| **Tests** | Admissibility reject paths for simulation; security model release gates; copilot/auto-heal security docs + related tests |
| **Assumptions** | Humans or governed gates approve production side effects |
| **Residual risk** | Agents may still over-trust fluent text without reading authority tags |
| **Owner** | logic-policy; agent/runtime owners; security reviewers |
| **Detection** | Authority-kind telemetry; human review queues on abstain |
| **Revoke / rotate** | Retract publications; revoke capabilities issued under bad drafts |
| **Recovery** | Re-label artifacts; re-run formal gates; restore from content-addressed prior good CID |

---

## 5. Cross-cutting control summary

| Control family | Mechanism (current tree) | Trust effect |
| --- | --- | --- |
| **Layered authority** | ADR-003 vocabulary; typed proof/authz envelopes | Prevents parse/model success → allow |
| **Fail-closed outcomes** | UNKNOWN, NOT_MODELED, unavailable, denied, abstain (ADR-004) | No silent green |
| **Optional policy pipeline** | `DispatchPipeline` compliance → risk → UCAN → temporal → NL-UCAN | Deny without tool body |
| **Governed authorization** | Intent envelope → portfolio → receipt → one-time capability | Side-effect-free evaluate; atomic consume |
| **Input validation** | MCP validators; IR schemas; body size limits | Reduces injection/DoS |
| **Redaction** | Server error sanitize; wallet redact; authz public views | Limits secret/PII leakage |
| **Secrets storage** | Env; `SecretsVault`; `SecretsManager`; CI secret stores | At-rest protection when used correctly |
| **Revocation** | UCAN revlist; proof corpus revocation; token blacklist | Limits blast radius |
| **Observability** | Event DAG, policy audit log, metrics, health (not authz) | Detection only |
| **Capability probing** | Feature detection for provers/extras | Avoids fake capability |

---

## 6. Detection matrix

| Signal | Source | Suggests |
| --- | --- | --- |
| Spike in pipeline `denied_by` | Policy audit / DecisionObject | Abuse or misconfiguration |
| Capability consume failures | PreInvocationEnforcement | Replay or race |
| Sudden prover UNKNOWN/timeout | Logic portfolio receipts | DoS or binary fault |
| Auth 401/403 and SECRET_KEY fatals | FastAPI logs | Missing/rotated secrets or attack |
| Cache integrity mismatches | Storage/cache logs | Poisoning or clock/version skew |
| Redaction_count anomalies | Wallet artifacts | New PII patterns or evasion |
| Outbound model/API cost spikes | Provider billing / metrics | Exfil or runaway agent |
| Revoked CID reuse attempts | UCAN evaluator | Compromised delegation holder |

Monitoring **never** substitutes for authorization (ADR-003 monitoring layer).

---

## 7. Revocation, rotation, and recovery (operator playbooks)

### 7.1 Credential compromise

1. **Revoke** at provider (API key, OAuth, Twilio, GitHub).
2. **Rotate** env vars and vault entries; never commit replacements.
3. **Restart** processes that cached env.
4. **Invalidate** JWTs (blacklist / short TTL) and UCAN chains as needed.
5. **Audit** Event DAG / policy logs for the exposure window.
6. **Recover** services with least-privilege new credentials.

Detailed inventory: [SECRETS_AND_CREDENTIALS.md](SECRETS_AND_CREDENTIALS.md).

### 7.2 Delegated capability compromise

1. Add delegation CIDs to `RevocationList`; persist to configured store path.
2. Flush authorization decision caches bound to old revocation root.
3. Re-issue narrow, short-lived delegations.
4. Disable unsigned delegation allow-flags if enabled.

### 7.3 Poisoned content or cache

1. Identify bad CIDs / cache keys.
2. Unpin/delete and flush multi-tier caches.
3. Re-ingest from trusted provenance.
4. Rebuild embeddings/indexes from redacted or verified sources.

### 7.4 Prover / proof corpus incident

1. Mark affected envelopes non-authoritative; attach revocation snapshot.
2. Block release gates on UNKNOWN/NOT_MODELED for impacted claims.
3. Re-verify under pinned binaries and VK/circuit IDs.
4. Rotate artifact roots if keys or VKs were exposed.

### 7.5 Transport exposure

1. Cut network path (security group / ingress).
2. Rotate `SECRET_KEY` and session material.
3. Redeploy with authn, TLS terminator, corrected CORS/hosts.
4. Review tool invocations in audit trail.

---

## 8. Ownership RACI (documentation-level)

| Area | Responsible (implementation) | Accountable (trust decision) | Consulted | Informed |
| --- | --- | --- | --- | --- |
| Threat model doc | security track / docs | security + architecture | mcp-security, logic-policy | operators, agents |
| MCP transports & pipeline | mcp-server | mcp-security | operators | clients |
| Governed authz / proof | logic.admissibility / proof_corpus | logic-policy | security-models | release owners |
| Parsers / archives / media | processors / multimedia | architecture | security | operators |
| Provers / ZKP | logic.external_provers / zkp | logic-proof | security | release owners |
| Caches / IPFS backends | caching / storage / routers | architecture | operators | developers |
| Credentials | operators + secrets modules | operators | security | all developers |
| PII / wallet | wallet | wallet + operators | legal-data | security |
| Generated content gates | logic-policy + runtime | logic-policy | agent owners | users |

---

## 9. Residual risk register (top)

| ID | Risk | Likelihood | Impact | Treatment | Residual |
| --- | --- | --- | --- | --- | --- |
| R1 | MCP host without pipeline exposed on network | Med | High | Default deny at edge; attach pipeline; require UCAN | Operator must configure |
| R2 | Simulated ZKP / solver stdout treated as production proof | Med | High | Docs + attestation kinds + release gates | Agent misuse remains |
| R3 | Secret leakage via free-text logs/tool returns | Med | High | Sanitize + redaction tools + CI scanning | Incomplete pattern coverage |
| R4 | Archive/path bombs on convert paths | Med | Med | Limits + untrusted input policy | Not uniform across backends |
| R5 | P2P/cache shared secret weak or shared with GH token fallback | Low–Med | Med | Dedicated cache secrets; rotate | Misconfig possible |
| R6 | Decision cache serving post-revocation allow | Low | High | Bind caches to revocation roots; flush on revoke | Multi-node lag |
| R7 | Model prompt injection → tool args | Med | Med | Authority layering; human/gated side effects | Residual in agent hosts |
| R8 | Submodule / lazy prover supply chain | Low–Med | High | Pin SHAs; checksum binaries; least install | Upstream risk remains |

---

## 10. Representative test and evidence map

| Concern | Example evidence in tree |
| --- | --- |
| Layered / fail-closed policy | ADR-003, ADR-004; admissibility compose/gate modules |
| UCAN revocation | `ipfs_datasets_py/mcp_server/ucan_delegation.py` (`RevocationList`) |
| Error redaction | `IPFSDatasetsMCPServer._sanitize_error_context` |
| Wallet PII redaction | `wallet/service.py` redaction APIs; wallet MCP tools |
| Security models / provers | `tests/logic/security_models/crypto_exchange/*` |
| Auth tools | `tests/original_tests/_test_auth_tools.py` (and successors) |
| Web archive untrusted inputs | `tests/unit/web_archiving/*`; processing guides |
| ZKP simulation labeling | `docs/logic/zkp/ARCHIVE/THREAT_MODEL.md` (module-local; historical/sim distinction) |
| Secrets vault | `mcp_server/secrets_vault.py`; optimizers `secrets_manager.py` |

Absence of a listed test for a path means **residual uncertainty**—do not invent coverage.

---

## 11. Related documents

| Document | Role |
| --- | --- |
| [SECRETS_AND_CREDENTIALS.md](SECRETS_AND_CREDENTIALS.md) | Credential inventory, rotation, redaction, no real secrets |
| [security_governance.md](security_governance.md) | Broader governance features narrative |
| [audit_logging.md](audit_logging.md) / [audit_reporting.md](audit_reporting.md) | Audit mechanics |
| [auto_healing_security.md](auto_healing_security.md) | CI auto-heal constraints |
| [ADR-003](../../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md) / [ADR-004](../../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Normative authority and fail-closed rules |
| Architecture leaves under `docs/architecture/` | Per-domain boundaries |
| Planned `AUDIT_PROVENANCE_AND_INCIDENTS.md` | Incident lifecycle and wallet trust deep dive |

---

## 12. Validation

```bash
test -s docs/guides/security/THREAT_MODEL.md && test -s docs/guides/security/SECRETS_AND_CREDENTIALS.md && rg -n 'trust|untrusted|residual|secret|redact|rotation|revoke' docs/guides/security/THREAT_MODEL.md docs/guides/security/SECRETS_AND_CREDENTIALS.md
```

Re-verify this threat model when transports, prover backends, wallet privacy,
UCAN, or secret-handling modules change.

---

## 13. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial canonical threat model for `IPFSDOC-060` / `IPFSDatasetsThreatModel@1` |

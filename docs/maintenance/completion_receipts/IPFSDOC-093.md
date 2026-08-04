# Completion receipt — IPFSDOC-093

| Field | Value |
| --- | --- |
| Interface | `DocumentationTaskCompletionReceipt@1` |
| Task | `IPFSDOC-093` |
| Title | Rebuild the glossary and authority vocabulary |
| Status | `evidence` |
| Owner | documentation-governance / navigation (implementation agent) |
| Goal id | `IPFSDOC-G111` |
| Track | navigation |
| Attempt | 1 |
| Measured at (UTC) | 2026-08-03T08:17:27Z |
| Worktree commit (`HEAD`) | `37f99e8a2c6dff4ba58ebc9ac26507bb8b9ee60f` |
| Worktree commit tree (`HEAD^{tree}`) | `52f9ec13ced80b46c3a0ca1632e6edb4835bb5bb` |
| Supervisor tree_id (packet) | `37f99e8a2c6dff4ba58ebc9ac26507bb8b9ee60f` |
| Objective revision | `baguqeeraaqafpygoefcw35jfvdfs547a5rsic5cjxj4lisb4iqk7mxt3hq7a` |
| Branch | `implementation/ipfsdoc-093-040057e0ce21-attempt-1-1785744886` |
| Audience | maintainer, agent, daemon validation gate |

## Declared outputs

| Path | Role | Size (bytes) | Content SHA-256 (at validation) |
| --- | --- | --- | --- |
| `docs/GLOSSARY.md` | Canonical glossary + authority vocabulary | 26259 | `013bdebff63d1d9ed416066b0d311fdf1fa3872bec29c3bf4209a9876a90454a` |
| `docs/maintenance/completion_receipts/IPFSDOC-093.md` | This completion receipt | non-empty | evidence artifact (this file); content is the authoritative record |

## What changed

Rebuilt `docs/GLOSSARY.md` from a short optimizers-only word list into a
project-wide **authority vocabulary** grounded in current architecture:

- Hard inequalities and the ADR-003 layered authority stack
- Kinds of truth (discovery / availability / capability / proof / authorization / …)
- Identity terms: CID, canonical profiles, IR identity, digests, pin vs identity
- Provenance layers (operational, IR, proof/authz evidence)—non-interchangeable
- Evidence, proof, `AuthorityKind`, attestation, policy, admissibility,
  authorization, decision receipts, one-time capabilities, pre-dispatch vs dispatch
- Runtime: backends, routers, adapters, fallbacks, stubs, extras, git vs logic submodules
- IR families, formalization/portfolio, MCP, Profile G, domain/optimizer terms
- Canonical aliases, deprecated labels, and homonyms (`capability`, `submodule`,
  `policy`, `receipt`, `authority`, `adapter`, `domain`)
- Cross-links to architecture leaves, ADRs, and maintenance authority policy

Optimizer/GraphRAG terms from the prior glossary were retained as a short
domain section so existing optimizers docs still have a landing vocabulary.

## Preconditions / dependencies consulted (read-only)

Declared depends-on evidence used as architecture sources (not edited):

| Dependency / source | Use |
| --- | --- |
| IPFSDOC-013 / ADR-001 | Content identity and CID vocabulary |
| IPFSDOC-014 / ADR-003, ADR-004 | Layered authority; fail-closed vs degradation |
| IPFSDOC-015 area | Runtime / system context surfaces |
| IPFSDOC-045 / RESULT_AUTHORITY, GOVERNED_AUTHORIZATION | Authority kinds, receipts, capabilities |
| IPFSDOC-053 / MCP thin-wrapper principle | Adapter vs domain ownership |
| IPFSDOC-061 area | Wallet/trust surfaces (non-interchangeable authority) |
| `SOURCE_AUTHORITY.md`, `END_TO_END_DATA_FLOW.md`, `IR_FAMILY_AND_IDENTITY.md`, logic leaves | Term grounding |

Protected plan files were **not** modified.

## Validation command

Exact gate from the task board:

```bash
test -s docs/GLOSSARY.md && test -s docs/maintenance/completion_receipts/IPFSDOC-093.md && rg -n 'capability|CID|IR|proof|policy|receipt|provenance|adapter|backend|fallback|authority' docs/GLOSSARY.md
```

## Validation result

| Check | Result |
| --- | --- |
| `test -s docs/GLOSSARY.md` | **pass** (non-empty; 26259 bytes) |
| `test -s docs/maintenance/completion_receipts/IPFSDOC-093.md` | **pass** (this file non-empty) |
| `rg` keyword coverage on glossary | **pass** — 124 matching lines covering all required tokens: `capability`, `CID`, `IR`, `proof`, `policy`, `receipt`, `provenance`, `adapter`, `backend`, `fallback`, `authority` |
| Overall gate | **pass** (exit 0) |

### Keyword presence (required tokens)

| Token | Present in `docs/GLOSSARY.md` |
| --- | --- |
| capability | yes |
| CID | yes |
| IR | yes |
| proof | yes |
| policy | yes |
| receipt | yes |
| provenance | yes |
| adapter | yes |
| backend | yes |
| fallback | yes |
| authority | yes |

## Acceptance criteria map

| Criterion | Evidence |
| --- | --- |
| Define current project-specific terms | Glossary sections for identity, evidence/proof/authz, runtime, IR, domains, optimizers |
| Distinguish identity / evidence / authority / runtime states | Hard inequalities; layered stack; kinds of truth; homonyms table |
| Name canonical aliases and deprecated terminology | “Canonical aliases and deprecated terminology” section |
| Cross-link architecture sources | Metadata Related row + “Architecture and maintenance sources” table |
| Avoid generic dictionary text / unsupported acronym expansion | Definitions tied to package paths, interfaces, and ADRs only |
| Record validated current tree, command, and result | This receipt: commit/tree, command, pass table |

## Explicit non-claims

- This receipt is **evidence** for the measured commit/date; it is not evergreen product architecture.
- Glossary summaries do not outrank tests, implementation, or accepted ADRs when they disagree.
- No production code, packaging, or protected plan files were changed.
- Daemon commit/merge remains subject to the supervisor validation gate.

## Re-run recipe

From repository root of this worktree:

```bash
test -s docs/GLOSSARY.md && test -s docs/maintenance/completion_receipts/IPFSDOC-093.md && rg -n 'capability|CID|IR|proof|policy|receipt|provenance|adapter|backend|fallback|authority' docs/GLOSSARY.md
```

Expected: exit status `0`, non-empty files, multiple `rg` hit lines including every required keyword.

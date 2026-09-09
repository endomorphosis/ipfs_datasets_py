# PCPR-061 Datasets semantic ContextPack

These files are the Datasets-owned *declared* semantic ContextPack for
the PCPR-060 reference idea:

    Modify a typed formal-logic API while reusing unaffected proofs,
    selecting only impacted tests, rejecting stale-tree evidence, and
    producing a complete proof-carrying execution receipt.

DatasetsContextPack@1 is minted from exact source CIDs of
LogicProviderProtocol@2, the PCPR-013 canonical cutover, and the
PCPR-013 hermetic tests. Capsules bind semantic APIs, the ContextPack
contract, and ProofObligation declarations. Semantic-impact inspection
is hermetic AST analysis. Live solver-backed impact, live supervisor
admission, DuckDB/Quack writes, and Kit current-root CAS are not
performed.

- `cpython312/reference.context-pack.json` is the declared pack
  document. Exact commit and tree are bound by the PCPR-061 receipt
  `current_tree_binding` because nested admission rewrites HEAD.
  `origin/main` is not the release identity.
- Durable storage and current-root CAS remain PCPR-062.
- Missing a live Quack-fenced session emits operator-blocking task
  `pcpr-061-operator-live-context-pack-admission`.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
